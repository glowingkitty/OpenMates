# contract-test-file: tooling
"""Keep marker-only chat epoch activation inside its disposable marker-only CI stack."""

import contextlib
import io
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import ci_environment


def _runner_profile(tmp_path, monkeypatch, **options):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    profile = ci_environment.compose_profile("a" * 40, **options)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    return runner, profile, compose_path


@pytest.mark.parametrize("initial,pending", [
    ({"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}, False),
    ({"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}, False),
    ({"protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0}, False),
    ({"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 1}, False),
    ({"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}, True),
])
@pytest.mark.parametrize("spec_name", [
    "maps-discovery-chat.spec.ts",
    "audio-recording-deferred-send.spec.ts",
    "connection-resilience.spec.ts",
    "skill-web-search.spec.ts",
])
def test_marker_chat_epoch_activates_only_fresh_idle_state(tmp_path, monkeypatch, initial, pending, spec_name):
    runner, profile, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    state = initial.copy()
    calls = []

    class Cache:
        async def close(self):
            pass

    class Directus:
        def __init__(self, cache_service):
            pass

        async def close(self):
            pass

    class Recovery:
        def __init__(self, directus):
            pass

        async def execute(self, operation, body):
            calls.append(operation)
            if operation == "get_cutover_state":
                return state.copy()
            if operation == "set_sends_paused":
                state["sends_paused"] = body["sends_paused"]
                return state.copy()
            if operation == "activate_protocol_epoch":
                assert state == {"protocol_epoch": 0, "sends_paused": True, "legacy_in_flight": 0}
                if pending:
                    raise RuntimeError("legacy_batches_pending")
                state["protocol_epoch"] = 1
                return {**state, "activated": True}
            raise AssertionError(operation)

    class Controller:
        def __init__(self, cache, directus):
            pass

        async def get_state(self, **kwargs):
            return state.copy()

    modules = {
        "backend.core.api.app.services.chat_recovery_service": ("ChatRecoveryService", Recovery),
        "backend.core.api.app.services.chat_recovery_cutover": ("ChatRecoveryCutoverController", Controller),
        "backend.core.api.app.services.cache": ("CacheService", Cache),
        "backend.core.api.app.services.directus": ("DirectusService", Directus),
    }
    for name, (attribute, cls) in modules.items():
        module = ModuleType(name)
        setattr(module, attribute, cls)
        monkeypatch.setitem(sys.modules, name, module)
    for key, value in profile["services"]["api"]["environment"].items():
        if isinstance(value, str):
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE", "1")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)

    def compose(*args, **kwargs):
        assert args[:6] == ("exec", "-T", "-e", "OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE=1", "api", "python")
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                exec(args[-1], {"__name__": "__main__"})
        except RuntimeError as exc:
            raise subprocess.CalledProcessError(1, args, stderr=str(exc)) from exc
        return SimpleNamespace(stdout=output.getvalue())

    monkeypatch.setattr(runner, "compose", compose)
    if initial == {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0} and not pending:
        assert runner.activate_isolated_marker_chat_epoch(spec_name) == {
            "protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0,
        }
        assert calls == ["get_cutover_state", "set_sends_paused", "activate_protocol_epoch",
                         "set_sends_paused"]
    else:
        with pytest.raises(RuntimeError, match="activation failed"):
            runner.activate_isolated_marker_chat_epoch(spec_name)
        if pending:
            assert calls == ["get_cutover_state", "set_sends_paused", "activate_protocol_epoch",
                             "set_sends_paused"]
            assert state["sends_paused"] is False
        else:
            assert calls == ["get_cutover_state"]


@pytest.mark.parametrize("profile_options,mutation", [
    ({}, None),
    ({"ai_fixtures": True}, lambda p: p["services"]["api"]["environment"].pop("OPENMATES_CI_AI_FIXTURES")),
    ({"ai_fixtures": True}, lambda p: p["services"]["api"]["environment"].update(OPENMATES_CI_ISOLATED="0")),
    ({"ai_fixtures": True}, lambda p: p["networks"]["default"].update(internal=False)),
    ({"public_provider": True}, None),
    ({"storage_capacity": True}, None),
])
def test_maps_epoch_rejects_other_profiles(tmp_path, monkeypatch, profile_options, mutation):
    runner, profile, path = _runner_profile(tmp_path, monkeypatch, **profile_options)
    if mutation:
        mutation(profile)
        path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="isolated marker-only AI profile"):
        runner.activate_isolated_marker_chat_epoch("maps-discovery-chat.spec.ts")


def test_maps_epoch_rejects_other_spec_and_bad_receipt(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="exact browser spec"):
        runner.activate_isolated_marker_chat_epoch("storage-capacity-replay.spec.ts")
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(
        stdout='{"protocol_epoch": 1, "sends_paused": true, "legacy_in_flight": 0}\n'))
    with pytest.raises(RuntimeError, match="incomplete"):
        runner.activate_isolated_marker_chat_epoch("maps-discovery-chat.spec.ts")


def test_maps_epoch_requires_github_runner(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "require_runner", ci_environment.require_runner)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="GitHub-hosted"):
        runner.activate_isolated_marker_chat_epoch("maps-discovery-chat.spec.ts")


def test_capacity_epoch_profile_guard_remains_separate(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: pytest.fail("Docker was reached"))
    with pytest.raises(RuntimeError, match="exact isolated capacity profile"):
        runner.activate_isolated_recovery_epoch()


def test_send_and_reconnect_batch_activates_epoch_once_before_browser(tmp_path, monkeypatch):
    runner, _, _ = _runner_profile(tmp_path, monkeypatch, ai_fixtures=True)
    web = tmp_path / "web"
    (web / "tests").mkdir(parents=True)
    specs = ["skill-web-search.spec.ts", "connection-resilience.spec.ts"]
    for spec in specs:
        (web / "tests" / spec).write_text("// authenticated marker fixture")
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(runner, "WEB", web)
    monkeypatch.setattr(runner, "RESULTS", results)
    monkeypatch.setattr(runner, "reserved_account_slot", lambda _: 1)
    monkeypatch.setattr(runner, "provision_account", lambda _, identity_index: {
        "OPENMATES_TEST_ACCOUNT_EMAIL": f"fixture-{identity_index}@example.com",
    })
    calls = []
    receipt = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}

    def activate(spec):
        calls.append(("activate", spec))
        return receipt

    monkeypatch.setattr(runner, "activate_isolated_marker_chat_epoch", activate)
    monkeypatch.setattr(runner, "activate_isolated_recovery_epoch", lambda: pytest.fail("Capacity activation reached"))

    class Process:
        def terminate(self):
            pass

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(runner, "wait_web", lambda _: None)

    def browser(command, **kwargs):
        calls.append(("browser", command[4]))
        assert calls[0] == ("activate", specs[0])
        from pathlib import Path
        Path(kwargs["env"]["PLAYWRIGHT_JSON_OUTPUT_NAME"]).write_text(
            json.dumps({"stats": {"expected": 1}})
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", browser)
    outcomes = runner.run_e2e(specs)
    assert calls == [("activate", specs[0]), *(('browser', 'tests/' + spec) for spec in specs)]
    assert all(result["exit_code"] == 0 for result in outcomes)
    assert all(result["accounts"]["recovery_protocol_epoch"] == 1 for result in outcomes)
