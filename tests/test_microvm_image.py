import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.microvm_image import SOURCE_FILES, package_source


def create_project(root: Path) -> None:
    for relative_path in SOURCE_FILES:
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"content for {relative_path}\n", encoding="utf-8")
    app_dir = root / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("app = None\n", encoding="utf-8")


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
            "app/main.py",
        ]


def test_package_source_rejects_missing_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing source files"):
        package_source(tmp_path, tmp_path / "artifact.zip")
