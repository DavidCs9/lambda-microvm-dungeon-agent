import argparse
import hashlib
import json
import sys
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_cloudformation import CloudFormationClient
from mypy_boto3_lambda_microvms import LambdaMicroVMsClient
from mypy_boto3_s3 import S3Client

DEFAULT_REGION = "us-east-2"
DEFAULT_STACK_NAME = "lambda-microvm-dungeon-agent-bootstrap"
DEFAULT_IMAGE_NAME = "dungeon-agent-fastapi"
BASE_IMAGE_ARN_TEMPLATE = "arn:aws:lambda:{region}:aws:microvm-image:al2023-1"
SOURCE_FILES = (
    Path("Dockerfile"),
    Path("README.md"),
    Path("pyproject.toml"),
    Path("uv.lock"),
)


@dataclass(frozen=True)
class BootstrapOutputs:
    artifact_bucket: str
    build_role_arn: str


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str
    s3_key: str


def create_clients(
    profile: str,
    region: str,
) -> tuple[CloudFormationClient, S3Client, LambdaMicroVMsClient]:
    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=5,
        read_timeout=60,
        retries={"mode": "adaptive", "total_max_attempts": 5},
        user_agent_extra="lambda-microvm-dungeon-agent/0.1.0",
    )
    return (
        session.client("cloudformation", config=config),
        session.client("s3", config=config),
        session.client("lambda-microvms", config=config),
    )


def package_source(project_root: Path, output_path: Path) -> Artifact:
    package_members = sorted(
        path.relative_to(project_root)
        for path in (project_root / "src" / "dungeon_agent").rglob("*.py")
    )
    members = [*SOURCE_FILES, *package_members]
    missing = [str(member) for member in members if not (project_root / member).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing source files: {', '.join(missing)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member in members:
            data = (project_root / member).read_bytes()
            info = zipfile.ZipInfo(member.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return Artifact(
        path=output_path,
        sha256=digest,
        s3_key=f"artifacts/{digest}/microvm-source.zip",
    )


def get_bootstrap_outputs(
    cloudformation: CloudFormationClient,
    stack_name: str,
) -> BootstrapOutputs:
    response = cloudformation.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if len(stacks) != 1:
        raise RuntimeError(f"Expected one stack named {stack_name}, found {len(stacks)}")

    outputs = {
        output["OutputKey"]: output["OutputValue"]
        for output in stacks[0].get("Outputs", [])
        if "OutputKey" in output and "OutputValue" in output
    }
    try:
        return BootstrapOutputs(
            artifact_bucket=outputs["ArtifactBucketName"],
            build_role_arn=outputs["MicrovmBuildRoleArn"],
        )
    except KeyError as error:
        raise RuntimeError(f"Bootstrap stack is missing output: {error.args[0]}") from error


def upload_artifact(s3: S3Client, outputs: BootstrapOutputs, artifact: Artifact) -> str:
    s3.upload_file(
        str(artifact.path),
        outputs.artifact_bucket,
        artifact.s3_key,
        ExtraArgs={
            "ContentType": "application/zip",
            "Metadata": {"sha256": artifact.sha256},
            "ServerSideEncryption": "AES256",
        },
    )
    return f"s3://{outputs.artifact_bucket}/{artifact.s3_key}"


def create_image(
    microvms: LambdaMicroVMsClient,
    *,
    image_name: str,
    artifact_uri: str,
    build_role_arn: str,
    region: str,
) -> str:
    response = microvms.create_microvm_image(
        name=image_name,
        description="FastAPI backend for the Lambda MicroVM Dungeon Agent lab",
        baseImageArn=BASE_IMAGE_ARN_TEMPLATE.format(region=region),
        buildRoleArn=build_role_arn,
        codeArtifact={"uri": artifact_uri},
        cpuConfigurations=[{"architecture": "ARM_64"}],
        resources=[{"minimumMemoryInMiB": 2048}],
        environmentVariables={"DUNGEON_WORKSPACE_DIR": "/workspace"},
        tags={"Project": "lambda-microvm-dungeon-agent", "ManagedBy": "microvm-image-tool"},
    )
    return response["imageArn"]


def wait_for_image(
    microvms: LambdaMicroVMsClient,
    image_identifier: str,
    *,
    timeout_seconds: int = 900,
    poll_seconds: int = 5,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = microvms.get_microvm_image(imageIdentifier=image_identifier)
        state = response["state"]
        if state == "CREATED":
            return state
        if state in {"CREATE_FAILED", "DELETE_FAILED", "DELETED"}:
            raise RuntimeError(f"MicroVM image entered terminal state {state}")
        time.sleep(poll_seconds)
    raise TimeoutError(f"Timed out waiting for MicroVM image {image_identifier}")


def build_image(args: argparse.Namespace) -> dict[str, str]:
    cloudformation, s3, microvms = create_clients(args.profile, args.region)
    project_root = Path(args.project_root).resolve()
    artifact = package_source(project_root, project_root / args.output)
    outputs = get_bootstrap_outputs(cloudformation, args.stack_name)
    artifact_uri = upload_artifact(s3, outputs, artifact)
    image_arn = create_image(
        microvms,
        image_name=args.image_name,
        artifact_uri=artifact_uri,
        build_role_arn=outputs.build_role_arn,
        region=args.region,
    )
    if args.wait:
        wait_for_image(microvms, image_arn)
    return {
        "artifact": str(artifact.path),
        "artifactSha256": artifact.sha256,
        "artifactUri": artifact_uri,
        "imageArn": image_arn,
    }


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package and build the lab MicroVM image.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--stack-name", default=DEFAULT_STACK_NAME)
    parser.add_argument("--image-name", default=DEFAULT_IMAGE_NAME)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output", default="dist/microvm-source.zip")
    parser.add_argument("--no-wait", action="store_false", dest="wait")
    parser.set_defaults(wait=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        print(json.dumps(build_image(args), indent=2, sort_keys=True))
    except (BotoCoreError, ClientError, FileNotFoundError, RuntimeError, TimeoutError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
