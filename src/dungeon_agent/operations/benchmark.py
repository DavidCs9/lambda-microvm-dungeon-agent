import argparse
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_lambda_microvms import LambdaMicroVMsClient

from dungeon_agent.microvm import HttpResult, request_json, require_success, wait_for_state

DEFAULT_REGION = "us-east-2"


@dataclass(frozen=True)
class BenchmarkResult:
    microvm_id: str
    endpoint: str
    launch_ms: float
    warm_median_ms: float
    suspend_ms: float
    resume_ms: float
    first_request_after_resume_ms: float
    post_resume_warm_median_ms: float
    state_preserved: bool


def create_client(profile: str, region: str) -> LambdaMicroVMsClient:
    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=5,
        read_timeout=30,
        retries={"mode": "adaptive", "total_max_attempts": 5},
        user_agent_extra="lambda-microvm-dungeon-agent/0.1.0",
    )
    return session.client("lambda-microvms", config=config)


def median_latency(results: Sequence[HttpResult]) -> float:
    return statistics.median(result.latency_ms for result in results)


def run_benchmark(
    client: LambdaMicroVMsClient, image_arn: str, image_version: str
) -> BenchmarkResult:
    ingress_connector = (
        f"arn:aws:lambda:{client.meta.region_name}:aws:network-connector:"
        "aws-network-connector:ALL_INGRESS"
    )
    internet_egress_connector = (
        f"arn:aws:lambda:{client.meta.region_name}:aws:network-connector:"
        "aws-network-connector:INTERNET_EGRESS"
    )
    launch_started = time.perf_counter()
    run_response = client.run_microvm(
        imageIdentifier=image_arn,
        imageVersion=image_version,
        ingressNetworkConnectors=[ingress_connector],
        egressNetworkConnectors=[internet_egress_connector],
        idlePolicy={
            "maxIdleDurationSeconds": 300,
            "suspendedDurationSeconds": 300,
            "autoResumeEnabled": True,
        },
        maximumDurationInSeconds=1_800,
        logging={"disabled": {}},
    )
    microvm_id = run_response["microvmId"]
    endpoint = run_response["endpoint"]
    try:
        wait_for_state(client, microvm_id, "RUNNING")
        launch_ms = (time.perf_counter() - launch_started) * 1_000

        token_response = client.create_microvm_auth_token(
            microvmIdentifier=microvm_id,
            expirationInMinutes=30,
            allowedPorts=[{"port": 8080}],
        )
        token = token_response["authToken"]["X-aws-proxy-auth"]

        health = request_json(endpoint, token, "GET", "/health")
        require_success(health, "health check")
        warm_results = [request_json(endpoint, token, "GET", "/health") for _ in range(5)]
        for result in warm_results:
            require_success(result, "warm health check")

        persisted_state = request_json(
            endpoint,
            token,
            "PUT",
            "/v1/language",
            {"language": "es"},
        )
        require_success(persisted_state, "persist state")
        expected_world = persisted_state.body

        suspend_started = time.perf_counter()
        client.suspend_microvm(microvmIdentifier=microvm_id)
        wait_for_state(client, microvm_id, "SUSPENDED")
        suspend_ms = (time.perf_counter() - suspend_started) * 1_000

        resume_started = time.perf_counter()
        client.resume_microvm(microvmIdentifier=microvm_id)
        wait_for_state(client, microvm_id, "RUNNING")
        resume_ms = (time.perf_counter() - resume_started) * 1_000

        resumed_world = request_json(endpoint, token, "GET", "/v1/world")
        require_success(resumed_world, "read world after resume")
        post_resume_results = [request_json(endpoint, token, "GET", "/health") for _ in range(5)]
        for result in post_resume_results:
            require_success(result, "post-resume health check")

        return BenchmarkResult(
            microvm_id=microvm_id,
            endpoint=endpoint,
            launch_ms=launch_ms,
            warm_median_ms=median_latency(warm_results),
            suspend_ms=suspend_ms,
            resume_ms=resume_ms,
            first_request_after_resume_ms=resumed_world.latency_ms,
            post_resume_warm_median_ms=median_latency(post_resume_results),
            state_preserved=resumed_world.body == expected_world,
        )
    finally:
        client.terminate_microvm(microvmIdentifier=microvm_id)
        wait_for_state(client, microvm_id, "TERMINATED")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and clean up the MicroVM latency lab.")
    parser.add_argument("--profile", default="personal")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--image-arn", required=True)
    parser.add_argument("--image-version", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        result = run_benchmark(
            create_client(args.profile, args.region), args.image_arn, args.image_version
        )
        output = asdict(result)
        output["terminated"] = True
        print(json.dumps(output, indent=2, sort_keys=True))
    except (BotoCoreError, ClientError, OSError, RuntimeError, TimeoutError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
