"""Immutable workflow package contracts for the OpenCode release tooling.

Synthetic checkouts and dependency modules isolate tests from live configuration.
Packaging must leave the canonical source root untouched and bind capabilities.
The active release pointer is changed only after all package checks succeed.
See docs/architecture/agent-workflow-decisions.md for rollout and rollback.
"""

# contract-test-file: tooling
import json
import pytest
from scripts.sync_opencode_runtime_hook import (
    prepare_runtime_package,
    validate_runtime_package,
)


def fixture(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    hook = root / ".opencode/plugins/openmates-hooks.js"
    hook.parent.mkdir(parents=True)
    hook.write_text("export const OpenMatesHooks = async () => ({});\n")
    (root / "opencode.json").write_text(json.dumps({"instructions": ["guide.md"]}))
    (root / "guide.md").write_text("Use activity_add for milestones.")
    (root / ".agents/skills").mkdir(parents=True)
    deps = tmp_path / "deps"
    (deps / "@opencode-ai/plugin").mkdir(parents=True)
    (deps / "@opencode-ai/plugin/package.json").write_text('{"version":"1.17.20"}')
    return root, deps


def test_package_is_separate_and_detects_tampering(tmp_path):
    root, deps = fixture(tmp_path)
    original = (root / "opencode.json").read_bytes()
    package = tmp_path / "package"
    prepare_runtime_package(
        root, package, dependency_source=deps, control_plane_commit="a" * 40
    )
    assert (root / "opencode.json").read_bytes() == original
    config = json.loads((package / "opencode.json").read_text())
    assert config["instructions"] == [str(root / "guide.md")]
    assert config["skills"]["paths"] == [str(root / ".agents/skills")]
    assert validate_runtime_package(package)["control_plane_commit"] == "a" * 40
    (package / "plugins/openmates-hooks.js").write_text("changed")
    with pytest.raises(RuntimeError, match="checksum"):
        validate_runtime_package(package)


def test_missing_dependency_or_existing_package_is_rejected(tmp_path):
    root, deps = fixture(tmp_path)
    with pytest.raises(RuntimeError, match="dependency"):
        prepare_runtime_package(
            root,
            tmp_path / "out",
            dependency_source=tmp_path / "missing",
            control_plane_commit="a" * 40,
        )
    with pytest.raises(RuntimeError, match="outside"):
        prepare_runtime_package(
            root,
            root / "package",
            dependency_source=deps,
            control_plane_commit="a" * 40,
        )
