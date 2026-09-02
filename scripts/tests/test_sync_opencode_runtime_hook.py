# contract-test-file: tooling
from pathlib import Path

import pytest

from scripts.sync_opencode_runtime_hook import (
    DEPRECATED_RUNTIME_PATHS,
    HOOK_PATH,
    RUNTIME_MIRRORS,
    sync_hook,
)


def test_sync_hook_atomically_updates_shared_runtime_mirror(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    project = tmp_path / "project"
    source = runtime / HOOK_PATH
    target = project / HOOK_PATH
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("export const OpenMatesHooks = async () => ({});\n", encoding="utf-8")
    target.write_text("stale\n", encoding="utf-8")
    (runtime / "opencode.json").write_text('{"agent":{}}\n', encoding="utf-8")
    (project / "opencode.json").write_text('{"agent":{"build":{"steps":8}}}\n', encoding="utf-8")
    specification_skill = Path(".agents/skills/define-specification/SKILL.md")
    legacy_contract_skill = Path(".agents/skills/define-contract/SKILL.md")
    (runtime / specification_skill).parent.mkdir(parents=True)
    (runtime / specification_skill).write_text("# Current Specification workflow\n", encoding="utf-8")
    (project / legacy_contract_skill).parent.mkdir(parents=True)
    (project / legacy_contract_skill).write_text("# Legacy contract workflow\n", encoding="utf-8")

    first = sync_hook(runtime, project)
    second = sync_hook(runtime, project)

    assert first["changed"] is True
    assert second["changed"] is False
    assert target.read_bytes() == source.read_bytes()
    assert (project / "opencode.json").read_bytes() == (runtime / "opencode.json").read_bytes()
    assert (project / specification_skill).read_bytes() == (runtime / specification_skill).read_bytes()
    assert not (project / legacy_contract_skill).exists()
    assert specification_skill in RUNTIME_MIRRORS
    assert legacy_contract_skill in DEPRECATED_RUNTIME_PATHS


def test_sync_hook_rejects_invalid_or_same_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must differ"):
        sync_hook(tmp_path, tmp_path)
    runtime = tmp_path / "runtime"
    source = runtime / HOOK_PATH
    source.parent.mkdir(parents=True)
    source.write_text("not a plugin\n", encoding="utf-8")
    (runtime / "opencode.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not export"):
        sync_hook(runtime, tmp_path / "project")
