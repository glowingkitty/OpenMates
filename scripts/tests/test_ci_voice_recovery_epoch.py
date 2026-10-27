# contract-test-file: infrastructure
"""Voice CI setup retains storage, provider egress and cutover authority."""

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


def load(name):
    path = Path(__file__).resolve().parents[1] / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_voice_test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voice = load("ci_voice_recovery_epoch")
environment = load("ci_environment")


def profile():
    return environment.compose_profile(
        "c" * 40,
        ai_fixtures=True,
        object_storage=True,
        uploads=True,
        voice_camera=True,
        account_emails=["ci-one@example.com", "ci-two@example.com"],
    )


def activate(tmp_path, candidate, *, spec=voice.VOICE_RECOVERY_SPEC, receipt=None):
    path = tmp_path / "compose.json"
    path.write_text(json.dumps(candidate))
    calls = []
    if receipt is None:
        receipt = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}
    result = voice.activate_isolated_voice_recovery_epoch(
        spec,
        compose_path=path,
        require_runner=lambda: None,
        compose=lambda *args, **kwargs: (
            calls.append((args, kwargs)) or SimpleNamespace(stdout=json.dumps(receipt))
        ),
    )
    return result, calls


# contract-test: tooling
def test_voice_profile_executes_only_guarded_api_transition(tmp_path):
    receipt, calls = activate(tmp_path, profile())
    assert receipt == {
        "protocol_epoch": 1,
        "sends_paused": False,
        "legacy_in_flight": 0,
    }
    assert len(calls) == 1
    args, options = calls[0]
    assert args[:7] == (
        "exec",
        "-T",
        "-e",
        "OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE=1",
        "api",
        "python",
        "-c",
    )
    assert args[7] == voice.VOICE_EPOCH_PROGRAM
    assert options == {"capture": True, "timeout": 60}


@pytest.mark.parametrize(
    "path,value",
    [
        (("services", "object-storage"), None),
        (("services", "uploads"), None),
        (("services", "clamav"), None),
        (("services", "speech-worker"), None),
        (("networks", "default", "internal"), False),
        (("services", "api", "environment", "OPENMATES_CI_AI_FIXTURES"), "0"),
        (("services", "ai-worker", "environment", "OPENMATES_CI_AI_FIXTURES"), "0"),
        (("services", "speech-worker", "environment", "OPENMATES_CI_AI_FIXTURES"), "0"),
        (("services", "api", "environment", "SERVER_ENVIRONMENT"), "production"),
        (
            ("services", "api", "environment", "S3_ENDPOINT_URL"),
            "https://external.invalid",
        ),
        (("services", "api", "environment", "CMS_URL"), "https://external.invalid"),
        (("services", "api", "environment", "VAULT_URL"), "https://external.invalid"),
        (
            ("services", "api", "environment", "OPENMATES_STORAGE_CAPACITY_FIXTURES"),
            "true",
        ),
        (("services", "ai-worker", "environment", "CELERY_QUEUES"), "app_ai"),
        (
            ("services", "speech-worker", "environment", "CELERY_QUEUES"),
            "app_music,app_ai",
        ),
        (("services", "object-storage", "networks", "default", "aliases"), []),
        (
            ("services", "uploads", "environment", "S3_ENDPOINT_URL"),
            "https://external.invalid",
        ),
        (("services", "api", "networks"), ["default", "ingress"]),
        (("services", "core-worker", "networks"), ["default", "ingress"]),
        (("services", "ai-worker", "command"), ["celery", "--queues=app_ai"]),
        (
            ("services", "speech-worker", "command"),
            ["celery", "--queues=app_music,app_ai"],
        ),
        (("services", "ai-worker", "network_mode"), "host"),
        (
            (
                "services",
                "runner-gateway",
                "environment",
                "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
            ),
            "1",
        ),
        (
            ("services", "speech-worker", "environment", "HTTPS_PROXY"),
            "http://proxy.invalid",
        ),
        (
            ("services", "speech-worker", "environment", "http_proxy"),
            "http://proxy.invalid",
        ),
        (
            ("services", "speech-worker", "environment", "ALL_PROXY"),
            "http://proxy.invalid",
        ),
    ],
)
# contract-test: tooling
def test_profile_drift_fails_before_any_container_command(tmp_path, path, value):
    candidate = profile()
    target = candidate
    for key in path[:-1]:
        target = target[key]
    if value is None:
        target.pop(path[-1])
    else:
        target[path[-1]] = value
    manifest = tmp_path / "compose.json"
    manifest.write_text(json.dumps(candidate))
    with pytest.raises(RuntimeError):
        voice.activate_isolated_voice_recovery_epoch(
            voice.VOICE_RECOVERY_SPEC,
            compose_path=manifest,
            require_runner=lambda: None,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


# contract-test: tooling
def test_wrong_spec_is_rejected_before_profile_read_or_container_access(tmp_path):
    with pytest.raises(RuntimeError, match="exact voice browser spec"):
        voice.activate_isolated_voice_recovery_epoch(
            "assistant-speech-player.spec.ts",
            compose_path=tmp_path / "absent",
            require_runner=lambda: None,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {"protocol_epoch": True, "sends_paused": False, "legacy_in_flight": 0},
        {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": False},
        {"protocol_epoch": 1, "sends_paused": True, "legacy_in_flight": 0},
        {"protocol_epoch": 1, "sends_paused": 0, "legacy_in_flight": 0},
        {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 1},
    ],
)
# contract-test: tooling
def test_incomplete_receipt_never_claims_activation(tmp_path, receipt):
    with pytest.raises(RuntimeError, match="incomplete"):
        activate(tmp_path, profile(), receipt=receipt)


def execute_program(
    monkeypatch, *, fault=None, program=None, fixture_guard=None, extra_env=None
):
    for key in (
        voice._PROXY_KEYS
        | voice._OTHER_EPOCH_GUARDS
        | {
            voice._AUTHORED_MEDIA_GUARD,
            "OPENMATES_STORAGE_CAPACITY_FIXTURES",
            "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
        }
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        **voice._FIXTURE_ENV,
        **voice._PRIVATE_ENDPOINTS,
        fixture_guard or "OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE": "1",
    }.items():
        monkeypatch.setenv(key, value)
    for key, value in (extra_env or {}).items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    if fault == "inner-production":
        monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    state = {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}
    if fault == "existing-epoch":
        state["protocol_epoch"] = 1
    if fault == "legacy-in-flight":
        state["legacy_in_flight"] = 1
    if fault == "already-paused":
        state["sends_paused"] = True
    calls, closed = [], []

    class Cache:
        async def close(self):
            closed.append("cache")

    class Directus:
        def __init__(self, **_kwargs):
            pass

        async def close(self):
            closed.append("directus")

    class Service:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, payload):
            calls.append(operation)
            assert payload["protocol_version"] == 1
            if operation == "set_sends_paused":
                state["sends_paused"] = payload["sends_paused"]
                if fault == "pause-ack" and payload["sends_paused"]:
                    return {**state, "sends_paused": False}
                if fault == "resume-ack" and not payload["sends_paused"]:
                    return {**state, "sends_paused": True}
            if operation == "activate_protocol_epoch":
                assert state["protocol_epoch"] == 0 and state["sends_paused"] is True
                state["protocol_epoch"] = 1
                return {**state, "activated": fault != "activation-ack"}
            return dict(state)

    class Controller:
        def __init__(self, *_args):
            pass

        async def get_state(self, *, authoritative=False):
            calls.append("durable" if authoritative else "cached")
            if fault == ("durable-ack" if authoritative else "cache-ack"):
                return {**state, "sends_paused": True}
            return dict(state)

    for module_name, name, value in [
        ("chat_recovery_service", "ChatRecoveryService", Service),
        ("chat_recovery_cutover", "ChatRecoveryCutoverController", Controller),
        ("cache", "CacheService", Cache),
        ("directus", "DirectusService", Directus),
    ]:
        qualified = "backend.core.api.app.services." + module_name
        module = ModuleType(qualified)
        setattr(module, name, value)
        monkeypatch.setitem(sys.modules, qualified, module)
    try:
        exec(
            compile(
                program or voice.VOICE_EPOCH_PROGRAM, "<isolated-epoch-fixture>", "exec"
            ),
            {},
        )
    finally:
        execute_program.last_calls, execute_program.last_closed = calls, closed


# contract-test: tooling
def test_actual_activation_program_uses_canonical_pause_activate_resume(
    monkeypatch, capsys
):
    execute_program(monkeypatch)
    assert execute_program.last_calls == [
        "get_cutover_state",
        "set_sends_paused",
        "activate_protocol_epoch",
        "set_sends_paused",
        "durable",
        "cached",
    ]
    assert execute_program.last_closed == ["directus", "cache"]
    assert json.loads(capsys.readouterr().out) == {
        "protocol_epoch": 1,
        "sends_paused": False,
        "legacy_in_flight": 0,
    }


@pytest.mark.parametrize(
    "fault",
    [
        "inner-production",
        "existing-epoch",
        "legacy-in-flight",
        "already-paused",
        "pause-ack",
        "activation-ack",
        "resume-ack",
        "durable-ack",
        "cache-ack",
    ],
)
# contract-test: tooling
def test_inner_boundary_and_every_transition_ack_fail_closed(
    monkeypatch, capsys, fault
):
    with pytest.raises(RuntimeError):
        execute_program(monkeypatch, fault=fault)
    assert capsys.readouterr().out == ""
    if fault in {"pause-ack", "activation-ack", "resume-ack"}:
        assert execute_program.last_calls[-1] == "set_sends_paused"
    if fault in {"existing-epoch", "legacy-in-flight", "already-paused"}:
        assert execute_program.last_calls == ["get_cutover_state"]


# contract-test: tooling
def test_runner_gate_is_required_before_reading_a_profile(tmp_path):
    def require_runner():
        raise RuntimeError("not a GitHub runner")

    with pytest.raises(RuntimeError, match="GitHub runner"):
        voice.activate_isolated_voice_recovery_epoch(
            voice.VOICE_RECOVERY_SPEC,
            compose_path=tmp_path / "absent",
            require_runner=require_runner,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


# contract-test: tooling
def test_browser_runner_preserves_two_accounts_and_activates_before_playwright(
    tmp_path, monkeypatch
):
    # Import the prepared runner and its prepared dependencies, not the bound
    # worktree's older harness. All process/account transports remain inert.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    monkeypatch.setitem(sys.modules, "ci_environment", environment)
    runner = load("ci_run_tests")
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    (web / "tests" / voice.VOICE_RECOVERY_SPEC).write_text(
        "// authenticated voice fixture"
    )
    results = tmp_path / "results"
    results.mkdir()
    manifest = tmp_path / "compose.json"
    manifest.write_text(json.dumps(profile()))
    for name, value in [
        ("ROOT", tmp_path),
        ("WEB", web),
        ("RESULTS", results),
        ("COMPOSE_PATH", manifest),
    ]:
        monkeypatch.setattr(runner, name, value)
    monkeypatch.setattr(
        runner,
        "playwright_command",
        lambda: ["/synthetic/node", "/synthetic/playwright/cli.js"],
    )
    monkeypatch.setattr(runner, "wait_web", lambda _child: None)
    monkeypatch.setattr(runner, "reserved_account_slot", lambda _spec: 1)
    calls = []

    class Process:
        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_a, **_kw: Process())

    def provision(slot, *, identity_index):
        calls.append(("account", slot, identity_index))
        return {"OPENMATES_TEST_ACCOUNT_EMAIL": f"fixture-{identity_index}@example.com"}

    def activation(spec, **kwargs):
        assert spec == voice.VOICE_RECOVERY_SPEC and kwargs["compose_path"] == manifest
        assert (
            kwargs["require_runner"] is runner.require_runner
            and kwargs["compose"] is runner.compose
        )
        calls.append(("activate",))
        return {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}

    def browser(command, **kwargs):
        calls.append(("browser",))
        Path(kwargs["env"]["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(
            json.dumps({"stats": {"expected": 1}})
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner, "provision_account", provision)
    monkeypatch.setattr(runner, "activate_isolated_voice_recovery_epoch", activation)
    monkeypatch.setattr(
        runner,
        "activate_isolated_marker_chat_epoch",
        lambda *_a: pytest.fail("Marker activation reached"),
    )
    monkeypatch.setattr(
        runner,
        "activate_isolated_recovery_epoch",
        lambda: pytest.fail("Capacity activation reached"),
    )
    monkeypatch.setattr(runner.subprocess, "run", browser)
    receipts = runner.run_e2e([voice.VOICE_RECOVERY_SPEC])
    assert calls == [
        ("account", 14, 0),
        ("account", 15, 1),
        ("activate",),
        ("browser",),
    ]
    assert len(receipts) == 1 and receipts[0]["exit_code"] == 0
    assert receipts[0]["accounts"]["recovery_protocol_epoch"] == 1


# contract-test: tooling
def test_existing_marker_and_capacity_guards_stay_separate(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    monkeypatch.setitem(sys.modules, "ci_environment", environment)
    runner = load("ci_run_tests")
    manifest = tmp_path / "compose.json"
    manifest.write_text(json.dumps(profile()))
    monkeypatch.setattr(runner, "COMPOSE_PATH", manifest)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(
        runner, "compose", lambda *_a, **_kw: pytest.fail("Container command reached")
    )
    assert voice.VOICE_RECOVERY_SPEC not in runner.MARKER_CHAT_EPOCH_SPECS
    assert voice.VOICE_RECOVERY_SPEC not in runner.CAPACITY_EPOCH_SPECS
    with pytest.raises(RuntimeError, match="isolated marker-only AI profile"):
        runner.activate_isolated_marker_chat_epoch("stop-new-chat-draft.spec.ts")
    with pytest.raises(RuntimeError, match="exact isolated capacity profile"):
        runner.activate_isolated_recovery_epoch()
