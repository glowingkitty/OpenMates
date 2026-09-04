import json
from pathlib import Path

import pytest

from scripts.opencode_runtime_release import prepare_release, validate_release


# contract-test-file: tooling


def write_binary(path: Path, *, database_name: str = "opencode.db") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "db" ] && [ "$2" = "path" ]; then\n'
        f'  printf "%s/opencode/{database_name}\\n" "$XDG_DATA_HOME"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_prepare_release_atomically_activates_one_backend_binary(tmp_path: Path) -> None:
    binary = write_binary(tmp_path / "build" / "opencode")
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
    binary = write_binary(tmp_path / "opencode")
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
    binary = write_binary(tmp_path / "opencode")
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
    binary = write_binary(tmp_path / "opencode")

    with pytest.raises(RuntimeError, match="full 40-character"):
        prepare_release(
            binary,
            tmp_path / "releases",
            opencode_commit="a" * 40,
            control_plane_commit="deadbeef",
            version="1.17.20",
        )


def test_validate_release_rejects_nonproduction_database_path(tmp_path: Path) -> None:
    binary = write_binary(tmp_path / "opencode", database_name="opencode-.db")
    releases = tmp_path / "releases"

    with pytest.raises(RuntimeError, match="production opencode.db storage path"):
        prepare_release(
            binary,
            releases,
            opencode_commit="a" * 40,
            control_plane_commit="b" * 40,
            version="1.17.20",
        )

    assert not (releases / "current").exists()
