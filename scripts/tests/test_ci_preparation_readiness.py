# contract-test-file: tooling
"""Pure canonical readiness contracts; no Cargo/product/network/CI execution."""

import ast
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
from scripts import (
    ci_native_release as native,
    ci_artifacts as artifacts,
    ci_results,
    ci_client_owned_lifecycle as lifecycle,
    ci_coordinator as coordinator,
    ci_environment as runtime,
)

SOURCE = "a" * 40
TREE = "b" * 40
HARNESS = "c" * 40
SPEC = "cli-rust-request-performance.spec.ts"
ROOT = Path(__file__).resolve().parents[2]


def load_profile_helpers():
    spec = importlib.util.spec_from_file_location(
        "actual_private_profile_helpers",
        Path(__file__).with_name("test_ci_native_private_profile.py"),
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize(
    "incompatible",
    [
        [],
        [("libc6", "/lib/i386-linux-gnu/libc.so.6")],
        [("libc6,x32", "/libx32/libc.so.6")],
        [
            ("libc6", "/lib/i386-linux-gnu/libc.so.6"),
            ("libc6,x32", "/libx32/libc.so.6"),
        ],
    ],
)
def test_exact_x64_cache_selection_ignores_only_glibc_proven_incompatible_flags(
    incompatible,
):
    rows = {
        "libc.so.6": [
            ("libc6,x86-64", "/lib/x86_64-linux-gnu/libc.so.6"),
            *incompatible,
        ]
    }
    assert native.cache_dependency(rows, "libc.so.6") == Path(
        "/lib/x86_64-linux-gnu/libc.so.6"
    )


@pytest.mark.parametrize(
    "entries",
    [
        [("libc6", "/lib/i386-linux-gnu/libc.so.6")],
        [("libc6,x32", "/libx32/libc.so.6")],
        [("libc6,x86-64", "/lib/x86_64-linux-gnu/libc.so.6")] * 2,
        [
            ("libc6,x86-64", "/lib/x86_64-linux-gnu/libc.so.6"),
            ("libc6,x86-64", "/usr/lib/x86_64-linux-gnu/libc.so.6"),
        ],
        [
            ("libc6,x86-64", "/lib/x86_64-linux-gnu/libc.so.6"),
            ("libc6,unknown", "/lib/unknown/libc.so.6"),
        ],
        [
            ("libc6,x86-64", "/lib/x86_64-linux-gnu/libc.so.6"),
            ('libc6,x32, hwcap: "x"', "/libx32/libc.so.6"),
        ],
        [
            (
                'libc6,x86-64, hwcap: "x86-64-v3"',
                "/lib/x86_64-linux-gnu/glibc-hwcaps/x86-64-v3/libc.so.6",
            )
        ],
        [("libc6,x86-64", "/unbound/libc.so.6")],
    ],
)
def test_cache_selection_still_refuses_unknown_compatible_ambiguity_hwcaps_and_paths(
    entries,
):
    with pytest.raises(native.Refused):
        native.cache_dependency({"libc.so.6": entries}, "libc.so.6")


def diagnostic_fixture(tmp_path, monkeypatch):
    subject = tmp_path / "subject"
    subject.mkdir(mode=0o700)
    (subject / "test-results").mkdir(mode=0o700)
    tooling = tmp_path / "tooling"
    (tooling / "scripts").mkdir(mode=0o700, parents=True)
    tooling.chmod(0o700)
    monkeypatch.setattr(
        native, "__file__", str(tooling / "scripts/ci_native_release.py")
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    return subject, tooling, native.diagnostic_identity(SOURCE, TREE, HARNESS)


def test_finite_first_failure_is_persisted_before_real_owned_child_cleanup(
    tmp_path, monkeypatch
):
    subject, tooling, identity = diagnostic_fixture(tmp_path, monkeypatch)
    out = tmp_path / "owned"
    out.mkdir(mode=0o700)
    attempt = {}
    observed = []
    original = lifecycle.drain

    def before(value):
        assert value["reason"] == "exited" and value["returncode"] == 7
        native.diagnostic_checkpoint(
            subject,
            identity,
            "release",
            failure=native.Refused("child_failed"),
            child_code=value["returncode"],
            before_cleanup=True,
        )

    def drain(child, *args, **kwargs):
        value = json.loads((subject / native.DIAGNOSTIC_PRIVATE).read_text())
        assert value["firstFailure"] == {
            "stage": "release",
            "code": "child_failed",
            "childExitCode": 7,
            "recordedBeforeCleanup": True,
        }
        observed.append(True)
        return original(child, *args, **kwargs)

    monkeypatch.setattr(lifecycle, "drain", drain)
    code = lifecycle.run_owned(
        [sys.executable, "-I", "-B", "-c", "raise SystemExit(7)"],
        cwd=subject,
        env={"PATH": os.defpath},
        out=out,
        attempt=attempt,
        timeout=3,
        before_cleanup=before,
    )
    assert code == 7 and observed == [True] and attempt["cleanupVerified"] is True
    first = json.loads((subject / native.DIAGNOSTIC_PRIVATE).read_text())[
        "firstFailure"
    ]
    native.diagnostic_checkpoint(
        subject,
        identity,
        "release",
        failure=RuntimeError("PRIVATE_PASSWORD=secret /private/path"),
        cleanup=True,
    )
    value = native.publish_diagnostic(subject, SOURCE, TREE, HARNESS)
    assert (
        value["firstFailure"] == first
        and value["cleanupVerified"] is True
        and value["proofAccepted"] is False
    )
    assert "PRIVATE_PASSWORD" not in json.dumps(
        value
    ) and "/private/path" not in json.dumps(value)
    assert (tooling / native.DIAGNOSTIC_PUBLIC).is_file() and not (
        subject / native.DIAGNOSTIC_PUBLIC
    ).exists()


def test_advisory_callback_failure_cannot_skip_owned_cleanup_or_replace_exit(
    tmp_path, monkeypatch
):
    out = tmp_path / "owned"
    out.mkdir(mode=0o700)
    attempt = {}

    def unavailable(_):
        raise RuntimeError("private diagnostic unavailable")

    code = lifecycle.run_owned(
        [sys.executable, "-I", "-B", "-c", "raise SystemExit(9)"],
        cwd=tmp_path,
        env={"PATH": os.defpath},
        out=out,
        attempt=attempt,
        timeout=3,
        before_cleanup=unavailable,
    )
    assert code == 9 and attempt["cleanupVerified"] is True


@pytest.mark.parametrize(
    "malicious",
    [{"raw": "PRIVATE"}, {"schemaVersion": 1, "identity": "PRIVATE"}, ["PRIVATE"]],
)
def test_projection_never_publishes_malformed_or_extra_private_fields(
    tmp_path, monkeypatch, malicious
):
    subject, tooling, identity = diagnostic_fixture(tmp_path, monkeypatch)
    p = subject / native.DIAGNOSTIC_PRIVATE
    p.parent.mkdir(mode=0o700)
    p.write_text(json.dumps(malicious))
    p.chmod(0o600)
    value = native.publish_diagnostic(subject, SOURCE, TREE, HARNESS)
    assert value["firstFailure"][
        "code"
    ] == "diagnostic_unavailable" and "PRIVATE" not in json.dumps(value)
    assert set(value) == {
        "schemaVersion",
        "kind",
        "identity",
        "status",
        "stage",
        "firstFailure",
        "cleanupVerified",
        "observedBeforeCleanup",
        "proofAccepted",
    }


def test_normal_reader_exposes_only_valid_exact_native_diagnostic_and_keeps_defaults_unchanged(
    tmp_path, monkeypatch
):
    subject, tooling, identity = diagnostic_fixture(tmp_path, monkeypatch)
    native.diagnostic_checkpoint(
        subject,
        identity,
        "runtime",
        failure=native.Refused("loader_cache_ambiguous"),
        before_cleanup=True,
        cleanup=True,
    )
    native.publish_diagnostic(subject, SOURCE, TREE, HARNESS)
    native_key = artifacts.preparation_key(
        SOURCE, include_cli=True, include_upload=False, include_native_cli=True
    )
    job = {
        "mode": "prepare",
        "source": SOURCE,
        "candidate_tree": TREE,
        "run_id": 123,
        "preparation_key": native_key,
    }
    result = {"harness_commit": HARNESS}
    actual = ci_results.attach_native_preparation_diagnostic(result, job, tmp_path)
    assert (
        actual["native_preparation_diagnostic"]["status"] == "retained"
        and actual["native_preparation_diagnostic"]["proofAccepted"] is False
    )
    assert (
        actual["native_preparation_diagnostic"]["receipt"]["firstFailure"]["code"]
        == "loader_cache_ambiguous"
    )
    legacy = {"harness_commit": HARNESS}
    old = deepcopy(legacy)
    job["preparation_key"] = artifacts.preparation_key(SOURCE, include_cli=True)
    assert ci_results.attach_native_preparation_diagnostic(legacy, job, tmp_path) == old
    job["preparation_key"] = native_key
    job["candidate_tree"] = "f" * 40
    refused = ci_results.attach_native_preparation_diagnostic(
        {"harness_commit": HARNESS}, job, tmp_path
    )
    assert refused["native_preparation_diagnostic"] == {
        "status": "unavailable",
        "code": "diagnostic_unavailable",
        "proofAccepted": False,
    }


def test_actual_queue_never_dispatches_essential_or_saved65_after_native_producer_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(coordinator.time, "sleep", lambda _: None)
    q = coordinator.Queue(tmp_path / "queue.db")
    key = artifacts.preparation_key(SOURCE, include_cli=True, include_native_cli=True)
    preparation = {"key": key, "harness_commit": HARNESS, "cli": True, "upload": False}
    producer = q.enqueue("owner", SOURCE, [], "prepare", preparation=preparation)
    consumers = [
        q.enqueue(
            "owner", SOURCE, [name], preparation={**preparation, "id": producer["id"]}
        )
        for name in sorted(native.SCOPES)
    ]

    class Remote:
        def __init__(self):
            self.sent = []
            self.visible = []

        def budget(self):
            return {"remaining": 5000, "reset": 500}

        def runs(self):
            return self.visible

        def dispatch(self, job):
            self.sent.append(job)

    remote = Remote()
    q.tick(remote, 100)
    remote.visible = [
        {
            "display_title": producer["token"],
            "status": "completed",
            "conclusion": "failure",
            "id": 42,
            "html_url": "https://example.invalid/42",
        }
    ]
    q.tick(remote, 140)
    assert len(remote.sent) == 1 and remote.sent[0]["mode"] == "prepare"
    assert all(q.status(child["id"])[0]["state"] == "failure" for child in consumers)


def test_fixed_workflow_requires_optin_native_and_only_sanitized_diagnostic_enters_public_inventory():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    )
    steps = next(iter(workflow["jobs"].values()))["steps"]
    native_step = next(
        s for s in steps if "ci_artifacts.py native-build" in s.get("run", "")
    )
    assert (
        native_step["if"]
        == "inputs.mode == 'prepare' && env.CI_NATIVE_PREPARED == 'true'"
        and native_step.get("continue-on-error", False) is False
    )
    projection = next(
        s for s in steps if s.get("id") == "native-preparation-diagnostic"
    )
    assert (
        projection["if"].startswith("always() && inputs.mode == 'prepare'")
        and "ci_artifacts.py native-diagnostic" in projection["run"]
    )
    upload = next(
        s for s in steps if s.get("with", {}).get("name") == "isolated-test-results"
    )
    assert (
        "${{ steps.native-preparation-diagnostic.outputs.path }}"
        in upload["with"]["path"]
    )
    assert (
        "native-cli.tar.gz" not in upload["with"]["path"]
        and "native-release-build" not in upload["with"]["path"]
    )
    checkout = next(s for s in steps if s.get("with", {}).get("path") == "tooling")
    assert set(checkout["with"]["sparse-checkout"].split()) == {
        "scripts",
        ".github/workflows",
    }


def test_actual_protected_request_env_prepare_selects_only_source_committed_fixture_and_private_network(
    tmp_path, monkeypatch
):
    helper = load_profile_helpers()
    candidate, compose, profile = helper.prepare_profile(
        tmp_path, monkeypatch, [SPEC], candidate_ai_specs=(SPEC,)
    )
    assert SPEC in runtime.PRIVATE_BACKEND_SPECS
    assert profile["networks"] == {"default": {"internal": True}, "ingress": {}}
    services = profile["services"]
    assert "ai-worker" in services and "runner-gateway" in services
    assert services["api"]["environment"]["OPENMATES_CI_AI_FIXTURES"] == "1"
    assert services["ai-worker"]["environment"]["OPENMATES_CI_AI_FIXTURES"] == "1"
    for name, service in services.items():
        env = service.get("environment", {})
        assert not {
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "ANTHROPIC_API_KEY",
            "BREVO_API_KEY",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "ALL_PROXY",
            "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
        }.intersection(env)
        assert "network_mode" not in service
        if name != "runner-gateway":
            assert "ports" not in service
    assert compose.stat().st_mode & 0o777 == 0o600


def marker_activation(tmp_path, profile, calls):
    tree = ast.parse((ROOT / "scripts/ci_run_tests.py").read_text())
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name == "activate_isolated_marker_chat_epoch"
        or isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "MARKER_CHAT_EPOCH_SPECS"
            for t in n.targets
        )
    ]
    assert len(nodes) == 2
    p = tmp_path / "profile.json"
    p.write_text(json.dumps(profile))
    from types import SimpleNamespace

    def compose(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            stdout=json.dumps(
                {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}
            )
        )

    context = {
        "json": json,
        "subprocess": subprocess,
        "require_runner": lambda: None,
        "COMPOSE_PATH": p,
        "compose": compose,
    }
    exec(
        compile(
            ast.Module(body=nodes, type_ignores=[]),
            "actual-protected-marker-function",
            "exec",
        ),
        context,
    )
    return context["activate_isolated_marker_chat_epoch"]


def test_actual_protected_request_epoch_function_uses_committed_fixture_only(tmp_path):
    calls = []
    profile = runtime.compose_profile(SOURCE, ai_fixtures=True, private_backend=True)
    activate = marker_activation(tmp_path, profile, calls)
    assert activate(SPEC) == {
        "protocol_epoch": 1,
        "sends_paused": False,
        "legacy_in_flight": 0,
    }
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:7] == (
        "exec",
        "-T",
        "-e",
        "OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE=1",
        "api",
        "python",
        "-c",
    ) and kwargs == {"capture": True, "timeout": 60}


@pytest.mark.parametrize(
    "fault",
    ["nested", "similar", "public-network", "proxy", "missing-worker", "wrong-queue"],
)
def test_actual_protected_request_epoch_refuses_scope_or_private_fixture_drift(
    tmp_path, fault
):
    calls = []
    profile = runtime.compose_profile(SOURCE, ai_fixtures=True, private_backend=True)
    selected = SPEC
    if fault == "nested":
        selected = "nested/" + SPEC
    if fault == "similar":
        selected = SPEC.replace(".spec.ts", "-extra.spec.ts")
    if fault == "public-network":
        profile["networks"]["default"]["internal"] = False
    if fault == "proxy":
        profile["services"]["api"]["environment"]["HTTPS_PROXY"] = (
            "http://fixture.invalid"
        )
    if fault == "missing-worker":
        del profile["services"]["ai-worker"]
    if fault == "wrong-queue":
        profile["services"]["ai-worker"]["environment"]["CELERY_QUEUES"] = "other"
    activate = marker_activation(tmp_path, profile, calls)
    with pytest.raises(RuntimeError):
        activate(selected)
    assert calls == []


def clean_python_literal():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/isolated-tests.yml").read_text()
    )
    steps = next(iter(workflow["jobs"].values()))["steps"]
    setup = next(s for s in steps if s.get("id") == "setup-python")
    capability = next(
        i
        for i, s in enumerate(steps)
        if s.get("name")
        == "Resolve optional native capability from exact preparation key"
    )
    assert capability < steps.index(setup)
    assert (
        setup["with"]["update-environment"] == "${{ env.CI_NATIVE_PREPARED != 'true' }}"
    )
    verify = next(
        s
        for s in steps
        if s.get("name") == "Verify clean Python for native preparation and consumption"
    )
    assert verify["if"] == "env.CI_NATIVE_PREPARED == 'true'"
    return verify["run"].split("<<'PYCLEAN'\n", 1)[1].rsplit("\nPYCLEAN", 1)[0]


@pytest.mark.parametrize("loader", ["LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT"])
def test_actual_clean_python_bootstrap_refuses_setup_export_or_other_loader_before_child(
    tmp_path, monkeypatch, loader
):
    monkeypatch.setenv(loader, "/private/setup-python/lib")
    monkeypatch.setenv("CI_SETUP_PYTHON", sys.executable)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: pytest.fail("loader environment must refuse before execution"),
    )
    with pytest.raises(SystemExit, match="native_python_environment_refused"):
        exec(compile(clean_python_literal(), "fixed-workflow-python", "exec"), {})


@pytest.mark.parametrize("code", [0, 1])
def test_actual_clean_python_bootstrap_requires_clean_selected_python_before_path_activation(
    tmp_path, monkeypatch, code
):
    for key in list(os.environ):
        if key.startswith("LD_"):
            monkeypatch.delenv(key)
    destination = tmp_path / "github-path"
    monkeypatch.setenv("GITHUB_PATH", str(destination))
    monkeypatch.setenv("CI_SETUP_PYTHON", sys.executable)
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, code)

    monkeypatch.setattr(subprocess, "run", run)
    if code:
        with pytest.raises(SystemExit, match="native_python_bootstrap_refused"):
            exec(compile(clean_python_literal(), "fixed-workflow-python", "exec"), {})
        assert not destination.exists()
    else:
        exec(compile(clean_python_literal(), "fixed-workflow-python", "exec"), {})
        assert destination.read_text() == str(Path(sys.executable).parent) + "\n"
    assert len(calls) == 1 and calls[0][0] == [
        sys.executable,
        "-I",
        "-c",
        "import sys,ssl;assert sys.version_info[:2]==(3,13)",
    ]
    assert calls[0][1] == dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_actual_pre_setup_system_python_resolves_fixed_native_key_without_optional_dependencies(
    enabled,
):
    # This is the real stdlib-only CLI executed before setup-python, not a mock
    # of the key policy or its imports. It performs no build/download/admission.
    key = artifacts.preparation_key(
        SOURCE, include_cli=True, include_upload=False, include_native_cli=enabled
    )
    result = subprocess.run(
        [
            "/usr/bin/python3",
            str(ROOT / "scripts/ci_artifacts.py"),
            "native-capability",
            "--source",
            SOURCE,
            "--key",
            key,
        ],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=10,
    )
    assert (
        result.returncode == 0
        and result.stdout == (b"true\n" if enabled else b"false\n")
        and result.stderr == b""
    )


def test_actual_require_refusal_projects_only_closed_error_suffix():
    with pytest.raises(native.Refused) as failure:
        native.require(False, "loader_environment")
    assert native.diagnostic_error(failure.value) == "loader_environment"
    assert (
        native.diagnostic_error(
            native.Refused("native_release:PRIVATE_PASSWORD=/private/path")
        )
        == "invalid"
    )
    assert (
        native.diagnostic_error(RuntimeError("PRIVATE_PASSWORD=/private/path"))
        == "unclassified"
    )


@pytest.mark.parametrize(
    "field", ["status", "stage", "firstFailure.stage", "firstFailure.code"]
)
@pytest.mark.parametrize("wrong", [[], {}, None, True, 1])
def test_valid_shape_wrong_type_enums_are_finite_unavailable_in_publisher_and_reader(
    tmp_path, monkeypatch, field, wrong
):
    subject, tooling, identity = diagnostic_fixture(tmp_path, monkeypatch)
    value = native.diagnostic_checkpoint(
        subject,
        identity,
        "runtime",
        failure=native.Refused("loader_environment"),
        before_cleanup=True,
    )
    container, key = (
        (value["firstFailure"], field.split(".")[1]) if "." in field else (value, field)
    )
    container[key] = wrong
    assert native.diagnostic_valid(value, identity) is False
    private = subject / native.DIAGNOSTIC_PRIVATE
    private.write_text(json.dumps(value))
    private.chmod(0o600)
    projected = native.publish_diagnostic(subject, SOURCE, TREE, HARNESS)
    assert (
        projected["firstFailure"]["code"] == "diagnostic_unavailable"
        and projected["proofAccepted"] is False
    )
    public = tooling / native.DIAGNOSTIC_PUBLIC
    public.write_text(json.dumps(value))
    key = artifacts.preparation_key(
        SOURCE, include_cli=True, include_upload=False, include_native_cli=True
    )
    job = {
        "mode": "prepare",
        "source": SOURCE,
        "candidate_tree": TREE,
        "run_id": 123,
        "preparation_key": key,
    }
    result = ci_results.attach_native_preparation_diagnostic(
        {"harness_commit": HARNESS}, job, tmp_path
    )
    assert result["native_preparation_diagnostic"] == {
        "status": "unavailable",
        "code": "diagnostic_unavailable",
        "proofAccepted": False,
    }
