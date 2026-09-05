"""The retired startup mirror must never overwrite tracked root files.

Keep the legacy function as an explicit failure for old launchers.
Package tests cover the replacement loader and checksum validation.
All inputs are synthetic; no active runtime or source root is changed.
Rollback restores a whole compatible release, not a second writer.
"""

# contract-test-file: tooling
from pathlib import Path
import pytest
from scripts.sync_opencode_runtime_hook import sync_hook


def test_legacy_mirror_is_explicitly_retired_without_writes(tmp_path: Path):
    runtime = tmp_path / "runtime"
    project = tmp_path / "project"
    runtime.mkdir()
    project.mkdir()
    target = project / "opencode.json"
    target.write_text("keep newer source")
    with pytest.raises(RuntimeError, match="retired"):
        sync_hook(runtime, project)
    assert target.read_text() == "keep newer source"
