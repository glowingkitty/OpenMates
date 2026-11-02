"""Inventory drift tests use synthetic modules, never import SDK runtimes."""

# contract-test-file: tooling
import importlib.util
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sdk_inventory", HERE / "inventory.py")
INVENTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INVENTORY)


def test_npm_recursive_exports_classes_and_object_type_facades(tmp_path):
    (tmp_path / "index.ts").write_text(
        'export { NewPublic as RenamedPublic, helpers } from "./new.js";'
    )
    (tmp_path / "new.ts").write_text(
        "export class NewPublic { visible() {} static load() {} nested = { visible() {} }; private hidden() {} } export const helpers = { nested: { existing() {} } };"
    )
    (tmp_path / "sdk-entry.ts").write_text('export * from "./sdk.js";')
    source = """type Text = { set(value: string): void };
type Check = Text & { addEvidence(id: string): void };
export class OpenMates { plans!: { checks: Check; context: { artifacts: Text } }; }
"""
    (tmp_path / "sdk.ts").write_text(source)

    def scan():
        output = subprocess.check_output(
            ["node", str(HERE / "npm-inventory.mjs"), "--source-dir", str(tmp_path)],
            text=True,
        )
        return set(json.loads(output)["npm"])

    before = scan()
    assert "RenamedPublic.visible" in before and "RenamedPublic.hidden" not in before
    assert "RenamedPublic.load" in before
    assert "RenamedPublic.nested.visible" in before
    assert "helpers.nested.existing" in before
    assert "OpenMates.plans.checks.addEvidence" in before
    assert "OpenMates.plans.context.artifacts.set" in before
    (tmp_path / "sdk.ts").write_text(
        source.replace("checks: Check;", "checks: Check & { newlyAdded(): void };")
    )
    (tmp_path / "new.ts").write_text(
        "export class NewPublic { visible() {} static load() {} static newlyStatic() {} another() {} private hidden() {} } export const helpers = { nested: { existing() {}, newlyAdded() {} } };"
    )
    added = scan() - before
    assert {
        "RenamedPublic.another",
        "RenamedPublic.newlyStatic",
        "OpenMates.plans.checks.newlyAdded",
        "helpers.nested.newlyAdded",
    } <= added


def test_python_new_exported_module_and_dynamic_plan_facade(tmp_path):
    (tmp_path / "__init__.py").write_text(
        'from .new import NewPublic as RenamedPublic\n__all__ = ["OpenMates", "RenamedPublic"]\n'
    )
    (tmp_path / "new.py").write_text(
        "class NewPublic:\n    def visible(self): pass\n    def _hidden(self): pass\n"
    )
    (tmp_path / "sdk.py").write_text("""class _Checks:
    def add_evidence(self): pass
class OpenMates:
    def __init__(self):
        self.checks = _Checks()
        self.context = type("Context", (), {"artifacts": _Checks()})()
""")
    before = set(INVENTORY.python_inventory(tmp_path))
    assert "RenamedPublic.visible" in before and "RenamedPublic._hidden" not in before
    assert "OpenMates.context.artifacts.add_evidence" in before
    with (tmp_path / "new.py").open("a") as stream:
        stream.write("    def newly_added(self): pass\n")
    assert (
        "RenamedPublic.newly_added"
        in set(INVENTORY.python_inventory(tmp_path)) - before
    )


def test_python_exported_session_constructor_facades_detect_method_additions(tmp_path):
    (tmp_path / "__init__.py").write_text(
        'from .session import SessionClient\n__all__ = ["SessionClient"]\n'
    )
    module = tmp_path / "session.py"
    source = """class SessionPlans:
    def list(self): pass
    def _hidden(self): pass
class SessionClient:
    def __init__(self):
        self.plans = SessionPlans()
"""
    module.write_text(source)
    before = set(INVENTORY.python_inventory(tmp_path))
    assert "SessionClient.plans.list" in before
    assert "SessionClient.plans._hidden" not in before
    module.write_text(
        source.replace(
            "def list(self): pass",
            "def list(self): pass\n    def newly_added(self): pass",
        )
    )
    assert (
        "SessionClient.plans.newly_added"
        in set(INVENTORY.python_inventory(tmp_path)) - before
    )
