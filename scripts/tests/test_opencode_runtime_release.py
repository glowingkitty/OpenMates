import json
from pathlib import Path

import pytest

from scripts.opencode_runtime_release import prepare_release, validate_release


def test_prepare_release_atomically_activates_one_backend_binary(tmp_path: Path) -> None:
    binary = tmp_path / "build" / "opencode"
    binary.parent.mkdir()
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)
    releases = tmp_path / "releases"

    result = prepare_release(
        binary,
        releases,
        opencode_commit="a" * 40,
        control_plane_commit="b" * 40,
        version="1.17.20",
    )

    current = (releases / "current").resolve()
    assert current.name == "aaaaaaaaaaaa-bbbbbbbbbbbb"
    assert result == validate_release(current)
    assert json.loads((current / "manifest.json").read_text(encoding="utf-8"))["version"] == "1.17.20"


def test_validate_release_rejects_a_modified_binary(tmp_path: Path) -> None:
    binary = tmp_path / "opencode"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)
    releases = tmp_path / "releases"
    prepare_release(
        binary,
        releases,
        opencode_commit="a" * 40,
        control_plane_commit="b" * 40,
        version="1.17.20",
    )
    (releases / "current" / "opencode").write_text("corrupt", encoding="utf-8")

    with pytest.raises(RuntimeError, match="binary checksum"):
        validate_release(releases / "current")


def test_validate_release_rejects_a_mixed_control_plane_commit(tmp_path: Path) -> None:
    binary = tmp_path / "opencode"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)
    releases = tmp_path / "releases"
    prepare_release(
        binary,
        releases,
        opencode_commit="a" * 40,
        control_plane_commit="b" * 40,
        version="1.17.20",
    )

    with pytest.raises(RuntimeError, match="control-plane commit"):
        validate_release(releases / "current", control_plane_commit="c" * 40)


def test_prepare_release_rejects_short_control_plane_commit(tmp_path: Path) -> None:
    binary = tmp_path / "opencode"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)

    with pytest.raises(RuntimeError, match="full 40-character"):
        prepare_release(
            binary,
            tmp_path / "releases",
            opencode_commit="a" * 40,
            control_plane_commit="deadbeef",
            version="1.17.20",
        )
