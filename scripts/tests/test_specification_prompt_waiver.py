# contract-test-file: tooling
"""Synthetic provenance fixtures; no live message, session, approval or server mutation."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
waiver = importlib.import_module("specification_prompt_waiver")

TEXT = "The Apple work is already requested. Stop asking for Specification approval. Keep its tests and contracts."
QUOTE = "Stop asking for Specification approval."
SOURCE = {
    "provider": "codex",
    "session_id": "original-human-chat",
    "message_id": hashlib.sha256(TEXT.encode()).hexdigest(),
}
SESSION = {"task": "TASK-1: Apple work", "codex_task_id": SOURCE["session_id"]}


def fixture(tmp_path):
    root = tmp_path / "repo"
    control = tmp_path / "control"
    bundle = root / "specifications/features/apple-watch"
    bundle.mkdir(parents=True)
    (bundle / "specification.yml").write_text(
        yaml.safe_dump({"id": "feature.apple-watch"})
    )
    plan = root / "docs/plans/apple-work/plan.yml"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "profile": "concise",
                "id": "apple-work",
                "title": "Apple work",
                "status": "implementing",
                "goal": "Implement the requested Apple work.",
                "task": "TASK-1",
                "references": ["specifications/features/apple-watch/specification.yml"],
                "approval_prompt_waiver": {
                    "source": "Existing human instruction",
                    "instruction": QUOTE,
                },
            }
        )
    )
    packet = waiver.build_export(
        root,
        "local1",
        SESSION,
        plan="docs/plans/apple-work/plan.yml",
        specifications=["feature.apple-watch"],
        source=SOURCE,
        quote=QUOTE,
        read_message=lambda _: {"role": "user", "text": TEXT},
    )
    artifact = tmp_path / "private-export.json"
    data = (json.dumps(packet, sort_keys=True) + "\n").encode()
    waiver.write_private(artifact, data)
    return root, control, plan, packet, artifact, hashlib.sha256(data).hexdigest()


def install(root, control, artifact, sha, *, session_id="admin1", session=None):
    session = dict(session or SESSION)
    binding = waiver.import_export(control, artifact, sha, session_id, session)
    session[waiver.STATE_KEY] = [binding]
    (control / ".claude").mkdir(parents=True, exist_ok=True)
    (control / ".claude/sessions.json").write_text(
        json.dumps({"sessions": {session_id: session}})
    )
    return binding


def test_verified_evidence_carries_same_instruction_across_host_without_fingerprint_approval(
    tmp_path,
):
    root, control, _, packet, artifact, sha = fixture(tmp_path)
    approvals = control / "scripts/.specifications-approvals-state.json"
    approvals.parent.mkdir(parents=True)
    original = b'{"sessions":{"historical":{"unchanged":"approval"}}}'
    approvals.write_bytes(original)
    binding = install(root, control, artifact, sha)
    assert waiver.permits_prompt_waiver(root, control, "admin1", "feature.apple-watch")
    assert not waiver.permits_prompt_waiver(root, control, "admin1", "feature.billing")
    assert not waiver.permits_prompt_waiver(
        root, control, "other", "feature.apple-watch"
    )
    assert binding["originating_session"] == "local1"
    assert packet["decision"]["surface"] == "specification-approval-prompt"
    assert "fingerprint" not in binding
    assert TEXT not in (control / ".claude/sessions.json").read_text()
    assert approvals.read_bytes() == original
    assert artifact.stat().st_mode & 0o777 == 0o600
    assert waiver.evidence_path(control, sha).stat().st_mode & 0o777 == 0o600


def test_export_rejects_nonhuman_missing_quote_wrong_message_and_unbound_chat(tmp_path):
    root, _, _, _, _, _ = fixture(tmp_path)
    base = dict(
        plan="docs/plans/apple-work/plan.yml",
        specifications=["feature.apple-watch"],
        source=SOURCE,
        quote=QUOTE,
    )
    for reader in [
        lambda _: {"role": "assistant", "text": TEXT},
        lambda _: {"role": "user", "text": "Unrelated text"},
        lambda _: {"role": "user", "text": TEXT + "changed"},
    ]:
        with pytest.raises(ValueError):
            waiver.build_export(root, "local1", SESSION, **base, read_message=reader)
    with pytest.raises(ValueError):
        waiver.build_export(
            root,
            "local1",
            {**SESSION, "codex_task_id": "someone-else"},
            **base,
            read_message=lambda _: {"role": "user", "text": TEXT},
        )
    with pytest.raises(ValueError):
        waiver.build_export(
            root,
            "local1",
            SESSION,
            **{**base, "specifications": ["feature.unrelated"]},
            read_message=lambda _: {"role": "user", "text": TEXT},
        )


def test_import_rejects_other_task_wrong_transfer_hash_or_modified_scope(tmp_path):
    root, control, _, packet, artifact, sha = fixture(tmp_path)
    with pytest.raises(ValueError):
        waiver.import_export(control, artifact, "0" * 64, "admin1", SESSION)
    with pytest.raises(ValueError):
        waiver.import_export(
            control, artifact, sha, "admin1", {"task": "TASK-2: Other work"}
        )
    changed = copy.deepcopy(packet)
    changed["scope"]["specification_ids"].append("feature.unrelated")
    with pytest.raises(ValueError):
        waiver.validate_export(changed)
    changed = copy.deepcopy(packet)
    changed["evidence"]["role"] = "assistant"
    with pytest.raises(ValueError):
        waiver.validate_export(changed)
    assert not (control / ".claude/sessions.json").exists()


def test_gate_rejects_copied_binding_changed_task_removed_plan_scope_and_damaged_evidence(
    tmp_path,
):
    root, control, plan, _, artifact, sha = fixture(tmp_path)
    install(root, control, artifact, sha)
    state_path = control / ".claude/sessions.json"
    original = json.loads(state_path.read_text())
    copied = copy.deepcopy(original)
    copied["sessions"]["another"] = copied["sessions"]["admin1"]
    state_path.write_text(json.dumps(copied))
    assert not waiver.permits_prompt_waiver(
        root, control, "another", "feature.apple-watch"
    )
    changed = copy.deepcopy(original)
    changed["sessions"]["admin1"]["task"] = "TASK-2: Changed owner"
    state_path.write_text(json.dumps(changed))
    assert not waiver.permits_prompt_waiver(
        root, control, "admin1", "feature.apple-watch"
    )
    state_path.write_text(json.dumps(original))
    value = yaml.safe_load(plan.read_text())
    value["references"] = []
    plan.write_text(yaml.safe_dump(value))
    assert not waiver.permits_prompt_waiver(
        root, control, "admin1", "feature.apple-watch"
    )
    value["references"] = ["specifications/features/apple-watch/specification.yml"]
    plan.write_text(yaml.safe_dump(value))
    assert waiver.permits_prompt_waiver(root, control, "admin1", "feature.apple-watch")
    waiver.evidence_path(control, sha).write_bytes(b"damaged")
    assert not waiver.permits_prompt_waiver(
        root, control, "admin1", "feature.apple-watch"
    )


def load_specifications():
    name = "waiver_test_specifications"
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "specifications.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_valid_bundle(root):
    # Minimal valid bundle uses the real validator and changed-gate path.
    bundle = root / "specifications/features/apple-watch/specification.yml"
    bundle.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "feature.apple-watch",
                "version": 1,
                "status": "draft",
                "title": "Watch",
                "summary": "Requested Watch behavior.",
                "scope": {"includes": ["Watch"], "excludes": ["Other work"]},
                "assertions": [
                    {
                        "id": "watch.guest",
                        "type": "behavior",
                        "must": "Show the guest workspace.",
                    }
                ],
                "applies_to": {
                    "rest_api": {"required": False},
                    "cli": {"required": False},
                    "sdks": {
                        "required": False,
                        "implementations": {
                            "npm": {"required": False},
                            "pip": {"required": False},
                        },
                    },
                    "gui": {
                        "required": True,
                        "implementations": {
                            "web": {"required": False},
                            "apple": {"required": True},
                        },
                    },
                },
                "examples": {"file": "examples.yml", "required_groups": ["guest"]},
            }
        )
    )
    (bundle.parent / "examples.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "specification": "feature.apple-watch@1",
                "guest": [
                    {
                        "id": "open",
                        "given": "Signed out",
                        "when": "Opening",
                        "then": "Show guest",
                    }
                ],
            }
        )
    )
    return bundle


def test_actual_changed_gate_keeps_schema_unknown_assertions_and_generated_checks(
    tmp_path, monkeypatch
):
    root, control, _, _, artifact, sha = fixture(tmp_path)
    install(root, control, artifact, sha)
    specs = load_specifications()
    monkeypatch.setattr(specs, "_control_plane_root", lambda _: control)
    bundle = write_valid_bundle(root)
    paths = [str(bundle.relative_to(root))]
    approvals = control / "no-new-approvals.json"
    assert (
        specs.check_changed_files(
            root, paths, session_id="admin1", approvals_path=approvals
        )
        == []
    )
    assert (
        specs.check_approval(
            approvals, "admin1", "feature.apple-watch", "unapproved-fingerprint"
        )
        is not None
    )
    test = root / "WatchGuestTests.swift"
    test.write_text(
        "import XCTest\nclass WatchGuestTests: XCTestCase {\n// contract-test: supporting surface=gui.apple assertions=watch.UNKNOWN\nfunc testGuest() {}\n}\n"
    )
    errors = specs.check_changed_files(
        root, paths + [test.name], session_id="admin1", approvals_path=approvals
    )
    assert any("unknown" in error.lower() for error in errors)
    generated = root / "specifications/generated"
    generated.mkdir()
    monkeypatch.setattr(
        specs,
        "check_generated_integrity",
        lambda *args, **kwargs: ["generated drift sentinel"],
    )
    assert "generated drift sentinel" in specs.check_changed_files(
        root, paths, session_id="admin1", approvals_path=approvals
    )
    broken = yaml.safe_load(bundle.read_text())
    broken["assertions"] = []
    bundle.write_text(yaml.safe_dump(broken))
    assert specs.check_changed_files(
        root, paths, session_id="admin1", approvals_path=approvals
    )


def test_primary_plan_gate_honors_only_ceremony_and_retains_versions_assertions_and_docs(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    root, control, plan, _, artifact, sha = fixture(tmp_path)
    install(root, control, artifact, sha)
    write_valid_bundle(root)
    specs = load_specifications()
    monkeypatch.setattr(specs, "_control_plane_root", lambda _: control)
    data = {
        "schema_version": 3,
        "status": "implementing",
        "specification_refs": [
            {"id": "feature.apple-watch", "version": 1, "role": "primary"}
        ],
        "specification_impact": {
            "specification_update_required": True,
            "affected_assertions": ["watch.guest"],
        },
        "documentation_impact": {
            k: {"status": "unchanged", "reason": "No documentation change"}
            for k in ["generated_reference", "user_docs", "semantic_layer"]
        },
    }
    monkeypatch.setitem(
        sys.modules, "plan_validate", SimpleNamespace(validate_plan=lambda _: data)
    )
    args = dict(
        specifications_root=root / "specifications",
        session_id="admin1",
        approvals_path=control / "no-approvals.json",
    )
    assert specs.verify_plan_specifications(plan, **args) == []
    data["specification_refs"][0]["version"] = 2
    assert any(
        "expects version" in e for e in specs.verify_plan_specifications(plan, **args)
    )
    data["specification_refs"][0]["version"] = 1
    data["specification_impact"]["affected_assertions"] = ["watch.UNKNOWN"]
    assert any(
        "unknown Specification assertion" in e
        for e in specs.verify_plan_specifications(plan, **args)
    )
    data["specification_impact"]["affected_assertions"] = ["watch.guest"]
    data["documentation_impact"] = {}
    assert any(
        "documentation impact missing" in e
        for e in specs.verify_plan_specifications(plan, **args)
    )


def test_session_command_export_import_is_private_metadata_only_and_exactly_scoped(
    tmp_path, monkeypatch, capsys
):
    import ast
    import types

    root, control, _, _, _, _ = fixture(tmp_path)
    state = {
        "sessions": {
            "local1": dict(SESSION),
            "admin1": {"task": "TASK-1: Same authorized work"},
            "unrelated": {"task": "TASK-2: Other"},
        }
    }
    monkeypatch.setattr(
        waiver.decisions, "read_user_message", lambda _: {"role": "user", "text": TEXT}
    )
    monkeypatch.setitem(sys.modules, "scripts.specification_prompt_waiver", waiver)
    import scripts

    monkeypatch.setattr(scripts, "specification_prompt_waiver", waiver, raising=False)
    tree = ast.parse((SCRIPTS / "sessions.py").read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "cmd_specification"
    )
    env = {
        "argparse": types.SimpleNamespace(Namespace=types.SimpleNamespace),
        "Path": Path,
        "json": json,
        "hashlib": hashlib,
        "sys": sys,
        "CONTROL_PLANE_ROOT": control,
        "_load_sessions": lambda: state,
        "_resolve_session_id": lambda data, session_id: session_id,
        "_session_checkout_root": lambda _: root,
        "_mutate_sessions": lambda callback: callback(state),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "sessions.py", "exec"), env)
    export = root / ".runtime/private-waiver.json"
    env["cmd_specification"](
        types.SimpleNamespace(
            specification_action="export-prompt-waiver",
            session="local1",
            output=str(export),
            plan="docs/plans/apple-work/plan.yml",
            specification=["feature.apple-watch"],
            source_session=SOURCE["session_id"],
            message_id=SOURCE["message_id"],
            quote=QUOTE,
        )
    )
    output = json.loads(capsys.readouterr().out)
    assert not output["approval_recorded"]
    assert TEXT not in json.dumps(output) and QUOTE not in json.dumps(output)
    before_other = copy.deepcopy(state["sessions"]["unrelated"])
    env["cmd_specification"](
        types.SimpleNamespace(
            specification_action="import-prompt-waiver",
            session="admin1",
            evidence=str(export),
            sha256=output["sha256"],
        )
    )
    imported = json.loads(capsys.readouterr().out)
    assert (
        not imported["approval_recorded"]
        and imported["prompt_waiver"]["session_id"] == "admin1"
    )
    assert TEXT not in json.dumps(state)
    assert state["sessions"]["unrelated"] == before_other
    assert waiver.STATE_KEY not in state["sessions"]["local1"]
    with pytest.raises(SystemExit):
        env["cmd_specification"](
            types.SimpleNamespace(
                specification_action="export-prompt-waiver",
                session="local1",
                output=str(root / "tracked-source.json"),
                plan="docs/plans/apple-work/plan.yml",
                specification=["feature.apple-watch"],
                source_session=SOURCE["session_id"],
                message_id=SOURCE["message_id"],
                quote=QUOTE,
            )
        )
    assert not (root / "tracked-source.json").exists()


def test_direct_script_export_works_without_scripts_package_or_injected_waiver_module(
    tmp_path,
):
    """Run the actual sessions main/parser with only sibling imports available.

    Unrelated control-plane transports are inert test dependencies; the actual
    waiver module, original-message reader, parser and command handler execute.
    No namespace/package injection can hide a missing sibling import fallback.
    """
    import os
    import shutil
    import subprocess

    root, _, _, _, _, _ = fixture(tmp_path)
    isolated = root / "scripts"
    isolated.mkdir()
    for name in [
        "sessions.py",
        "specification_prompt_waiver.py",
        "_workflow_decisions.py",
    ]:
        shutil.copy2(SCRIPTS / name, isolated / name)
    (isolated / "ci_impact.py").write_text(
        "# No impact classification requested by this test.\n"
    )
    (isolated / "product_runtime_translations.py").write_text(
        "# No runtime translation operation requested.\n"
    )
    (isolated / "engineering_control_plane.py").write_text(
        "from pathlib import Path\nclass ControlPlaneApiError(RuntimeError): pass\n"
        "ENV_FILE = Path('never-read-private-env')\n"
        "def control_plane_api_request(*args, **kwargs): raise AssertionError('network forbidden')\n"
    )
    (isolated / "session_binding.py").write_text(
        "def resolve_session(data, *, session_id='', **kwargs):\n"
        "    if session_id not in data.get('sessions', {}): raise RuntimeError('unknown test session')\n"
        "    return session_id\n"
    )
    (root / ".claude").mkdir()
    (root / ".claude/sessions.json").write_text(
        json.dumps({"sessions": {"local1": dict(SESSION)}})
    )
    home = tmp_path / "private-codex-fixture"
    messages = home / "sessions"
    messages.mkdir(parents=True)
    (messages / ("rollout-" + SOURCE["session_id"] + ".jsonl")).write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": TEXT}],
                },
            }
        )
        + "\n"
    )
    artifact = root / ".runtime/direct-export.json"
    launcher = (
        "import importlib.util,runpy,sys; "
        "sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1)]; "
        "assert importlib.util.find_spec('scripts') is None; "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    args = [
        sys.executable,
        "-I",
        "-c",
        launcher,
        str(isolated),
        str(Path(yaml.__file__).parents[1]),
        str(isolated / "sessions.py"),
        "specification",
        "export-prompt-waiver",
        "--session",
        "local1",
        "--plan",
        "docs/plans/apple-work/plan.yml",
        "--specification",
        "feature.apple-watch",
        "--source-session",
        SOURCE["session_id"],
        "--message-id",
        SOURCE["message_id"],
        "--quote",
        QUOTE,
        "--output",
        str(artifact),
    ]
    env = dict(os.environ)
    env["CODEX_HOME"] = str(home)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert not output["approval_recorded"] and artifact.is_file()
    assert TEXT not in result.stdout and QUOTE not in result.stdout
    assert output["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    state = json.loads((root / ".claude/sessions.json").read_text())
    assert waiver.STATE_KEY not in state["sessions"]["local1"]
