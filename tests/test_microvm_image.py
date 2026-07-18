import hashlib
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from dungeon_agent.operations.image_builder import (
    SOURCE_FILES,
    Artifact,
    existing_artifact,
    package_source,
    publish_image,
)


def create_project(root: Path) -> None:
    for relative_path in SOURCE_FILES:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"content for {relative_path}\n", encoding="utf-8")
    api_dir = root / "src" / "dungeon_agent" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "main.py").write_text("app = None\n", encoding="utf-8")
    locale_dir = root / "src" / "dungeon_agent" / "resources" / "locales"
    locale_dir.mkdir(parents=True)
    (locale_dir / "es.json").write_text('{"code":"es"}\n', encoding="utf-8")


def test_package_source_is_deterministic(tmp_path: Path) -> None:
    create_project(tmp_path)

    first = package_source(tmp_path, tmp_path / "dist" / "first.zip")
    second = package_source(tmp_path, tmp_path / "dist" / "second.zip")

    assert first.sha256 == second.sha256
    assert first.s3_key == f"artifacts/{first.sha256}/microvm-source.zip"
    assert hashlib.sha256(first.path.read_bytes()).hexdigest() == first.sha256

    with zipfile.ZipFile(first.path) as archive:
        assert archive.namelist() == [
            "Dockerfile",
            "README.md",
            "pyproject.toml",
            "uv.lock",
            "src/dungeon_agent/api/main.py",
            "src/dungeon_agent/resources/locales/es.json",
        ]


def test_package_source_rejects_missing_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing source files"):
        package_source(tmp_path, tmp_path / "artifact.zip")


def test_existing_artifact_uses_content_digest(tmp_path: Path) -> None:
    path = tmp_path / "source.zip"
    path.write_bytes(b"release source")

    artifact = existing_artifact(path)

    assert artifact.sha256 == hashlib.sha256(b"release source").hexdigest()
    assert artifact.s3_key.endswith("/microvm-source.zip")


def test_publish_updates_an_existing_image() -> None:
    client = Mock()
    client.get_microvm_image.return_value = {"imageArn": "arn:existing"}
    client.update_microvm_image.return_value = {"imageArn": "arn:existing"}
    artifact = Artifact(Path("source.zip"), "a" * 64, "artifacts/source.zip")

    image_arn, operation = publish_image(
        client,
        image_name="dungeon-agent-fastapi",
        artifact=artifact,
        artifact_uri="s3://bucket/source.zip",
        build_role_arn="arn:aws:iam::123456789012:role/build-role",
        region="us-east-2",
        release_version="v1.2.3",
    )

    assert (image_arn, operation) == ("arn:existing", "updated")
    client.get_microvm_image.assert_called_once_with(
        imageIdentifier=(
            "arn:aws:lambda:us-east-2:123456789012:microvm-image:dungeon-agent-fastapi"
        )
    )
    client.update_microvm_image.assert_called_once()
    client.tag_resource.assert_called_once_with(Resource="arn:existing", Tags={"Release": "v1.2.3"})
