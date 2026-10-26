# contract-test-file: infrastructure
"""Selected-media CI cutover admits exactly its private upload fixture."""

import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def load_voice_tests():
    path = Path(__file__).with_name("test_ci_voice_recovery_epoch.py")
    spec = importlib.util.spec_from_file_location("_authored_media_voice_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = load_voice_tests()
media = helpers.voice


def profile():
    return helpers.environment.compose_profile(
        "c" * 40,
        ai_fixtures=True,
        object_storage=True,
        uploads=True,
        account_emails=["ci-one@example.com"],
    )


def activate(
    tmp_path, candidate, *, spec=media.AUTHORED_MEDIA_RECOVERY_SPEC, stdout=None
):
    path = tmp_path / "compose.json"
    path.write_text(json.dumps(candidate))
    calls = []
    receipt = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}
    result = media.activate_isolated_authored_media_recovery_epoch(
        spec,
        compose_path=path,
        require_runner=lambda: None,
        compose=lambda *args, **kwargs: calls.append((args, kwargs))
        or SimpleNamespace(stdout=json.dumps(receipt) if stdout is None else stdout),
    )
    return result, calls


# contract-test: tooling
def test_media_profile_uses_only_its_dedicated_guarded_api_transition(tmp_path):
    candidate = profile()
    assert "speech-worker" not in candidate["services"]
    assert (
        candidate["services"]["ai-worker"]["environment"]["CELERY_QUEUES"]
        == "app_ai,app_ai_routing"
    )
    receipt, calls = activate(tmp_path, candidate)
    assert receipt == {
        "protocol_epoch": 1,
        "sends_paused": False,
        "legacy_in_flight": 0,
    }
    assert calls == [
        (
            (
                "exec",
                "-T",
                "-e",
                "OPENMATES_CI_AUTHORED_MEDIA_RECOVERY_EPOCH_FIXTURE=1",
                "api",
                "python",
                "-c",
                media.AUTHORED_MEDIA_EPOCH_PROGRAM,
            ),
            {"capture": True, "timeout": 60},
        )
    ]


@pytest.mark.parametrize(
    "spec",
    [
        media.VOICE_RECOVERY_SPEC,
        "authored-results-flow.spec.ts",
        "components/authored-results-matrix.spec.ts",
        "../authored-results-media.spec.ts",
        "",
    ],
)
# contract-test: tooling
def test_wrong_spec_never_reads_profile_or_runs_container(tmp_path, spec):
    with pytest.raises(RuntimeError, match="exact media browser spec"):
        media.activate_isolated_authored_media_recovery_epoch(
            spec,
            compose_path=tmp_path / "missing",
            require_runner=lambda: None,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


@pytest.mark.parametrize(
    "name",
    [
        "api",
        "core-worker",
        "ai-worker",
        "object-storage",
        "uploads",
        "clamav",
        "runner-gateway",
    ],
)
# contract-test: tooling
def test_missing_required_service_fails_before_container(tmp_path, name):
    candidate = profile()
    candidate["services"].pop(name)
    with pytest.raises(RuntimeError, match="upload profile"):
        activate(tmp_path, candidate)


@pytest.mark.parametrize(
    "path,value",
    [
        (("networks", "default", "internal"), False),
        (("networks", "ingress", "external"), True),
        (("services", "api", "environment", "OPENMATES_CI_AI_FIXTURES"), "0"),
        (("services", "ai-worker", "environment", "MOCK_EXTERNAL_APIS"), "false"),
        (("services", "api", "environment", "SERVER_ENVIRONMENT"), "production"),
        (
            ("services", "api", "environment", "S3_ENDPOINT_URL"),
            "https://external.invalid",
        ),
        (
            ("services", "ai-worker", "environment", "CMS_URL"),
            "https://external.invalid",
        ),
        (
            ("services", "core-worker", "environment", "VAULT_URL"),
            "https://external.invalid",
        ),
        (
            ("services", "uploads", "environment", "S3_ENDPOINT_URL"),
            "https://external.invalid",
        ),
        (("services", "api", "networks"), ["default", "ingress"]),
        (("services", "core-worker", "networks"), ["default", "ingress"]),
        (("services", "uploads", "networks"), ["default", "public"]),
        (("services", "object-storage", "networks", "default", "aliases"), []),
        (("services", "clamav", "network_mode"), "host"),
        (("services", "ai-worker", "network_mode"), "host"),
        (("services", "api", "ports"), ["127.0.0.1:8000:8000"]),
        (("services", "uploads", "ports"), ["0.0.0.0:8001:8000"]),
        (
            ("services", "ai-worker", "environment", "CELERY_QUEUES"),
            "app_ai,app_ai_routing,app_videos",
        ),
        (("services", "ai-worker", "command"), ["celery", "--queues=app_ai"]),
        (
            ("services", "ai-worker", "command"),
            [
                "celery",
                "--queues=app_ai,app_ai_routing",
                "--queues=app_ai,app_ai_routing",
            ],
        ),
        (("services", "uploads", "environment", "CLAMAV_HOST"), "remote.invalid"),
        (("services", "uploads", "environment", "CLAMAV_PORT"), "3311"),
        (
            ("services", "uploads", "environment", "DEV_CORE_API_URL"),
            "https://api.dev.openmates.org",
        ),
        (("services", "clamav", "environment", "CLAMAV_NO_CLAMD"), "true"),
        (
            ("services", "uploads", "depends_on", "clamav"),
            {"condition": "service_started"},
        ),
    ],
)
# contract-test: tooling
def test_profile_drift_fails_before_any_container_command(tmp_path, path, value):
    candidate = profile()
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    manifest = tmp_path / "compose.json"
    manifest.write_text(json.dumps(candidate))
    with pytest.raises(RuntimeError):
        media.activate_isolated_authored_media_recovery_epoch(
            media.AUTHORED_MEDIA_RECOVERY_SPEC,
            compose_path=manifest,
            require_runner=lambda: None,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


@pytest.mark.parametrize(
    "service", ["api", "core-worker", "ai-worker", "uploads", "runner-gateway"]
)
@pytest.mark.parametrize(
    "key",
    sorted(
        media._PROXY_KEYS
        | media._OTHER_EPOCH_GUARDS
        | {
            media._AUTHORED_MEDIA_GUARD,
            "OPENMATES_STORAGE_CAPACITY_FIXTURES",
            "OPENMATES_CI_PUBLIC_PROVIDER_PROXY",
        }
    ),
)
# contract-test: tooling
def test_proxy_or_baked_in_fixture_identity_fails_closed(tmp_path, service, key):
    candidate = profile()
    candidate["services"][service].setdefault("environment", {})[key] = "1"
    manifest = tmp_path / "compose.json"
    manifest.write_text(json.dumps(candidate))
    with pytest.raises(RuntimeError):
        media.activate_isolated_authored_media_recovery_epoch(
            media.AUTHORED_MEDIA_RECOVERY_SPEC,
            compose_path=manifest,
            require_runner=lambda: None,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"protocol_epoch":true,"sends_paused":false,"legacy_in_flight":0}',
        '{"protocol_epoch":1,"sends_paused":false,"legacy_in_flight":false}',
        '{"protocol_epoch":1,"sends_paused":true,"legacy_in_flight":0}',
        '{"protocol_epoch":1,"sends_paused":false,"legacy_in_flight":1}',
    ],
)
# contract-test: tooling
def test_missing_or_incomplete_receipt_never_claims_activation(tmp_path, stdout):
    with pytest.raises(RuntimeError):
        activate(tmp_path, profile(), stdout=stdout)


# contract-test: tooling
def test_container_failure_is_not_success_and_does_not_expose_output(tmp_path):
    manifest = tmp_path / "compose.json"
    manifest.write_text(json.dumps(profile()))

    def compose(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1, ["compose"], output="private-output", stderr="private-error"
        )

    with pytest.raises(RuntimeError, match="activation failed") as error:
        media.activate_isolated_authored_media_recovery_epoch(
            media.AUTHORED_MEDIA_RECOVERY_SPEC,
            compose_path=manifest,
            require_runner=lambda: None,
            compose=compose,
        )
    assert "private" not in str(error.value)


def execute_program(monkeypatch, **kwargs):
    return helpers.execute_program(
        monkeypatch,
        program=media.AUTHORED_MEDIA_EPOCH_PROGRAM,
        fixture_guard=media._AUTHORED_MEDIA_GUARD,
        **kwargs,
    )


# contract-test: tooling
def test_media_program_reuses_canonical_pause_activate_resume_and_checks_both_receipts(
    monkeypatch, capsys
):
    execute_program(monkeypatch)
    assert helpers.execute_program.last_calls == [
        "get_cutover_state",
        "set_sends_paused",
        "activate_protocol_epoch",
        "set_sends_paused",
        "durable",
        "cached",
    ]
    assert helpers.execute_program.last_closed == ["directus", "cache"]
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
def test_media_program_every_transition_and_ack_fail_closed(monkeypatch, capsys, fault):
    with pytest.raises(RuntimeError):
        execute_program(monkeypatch, fault=fault)
    assert capsys.readouterr().out == ""
    if fault in {"pause-ack", "activation-ack", "resume-ack"}:
        assert helpers.execute_program.last_calls[-1] == "set_sends_paused"
    if fault in {"existing-epoch", "legacy-in-flight", "already-paused"}:
        assert helpers.execute_program.last_calls == ["get_cutover_state"]


@pytest.mark.parametrize(
    "extra",
    [
        {media._AUTHORED_MEDIA_GUARD: None},
        {media._AUTHORED_MEDIA_GUARD: "0"},
        {"OPENMATES_CI_VOICE_RECOVERY_EPOCH_FIXTURE": "1"},
        {"OPENMATES_CI_MARKER_CHAT_EPOCH_FIXTURE": "1"},
        {"OPENMATES_CI_RECOVERY_EPOCH_FIXTURE": "1"},
        {"OPENMATES_STORAGE_CAPACITY_FIXTURES": "true"},
        {"OPENMATES_CI_PUBLIC_PROVIDER_PROXY": "1"},
        {"HTTPS_PROXY": "http://proxy.invalid"},
    ],
)
# contract-test: tooling
def test_executed_media_program_requires_exclusive_fixture_guard(
    monkeypatch, capsys, extra
):
    with pytest.raises(RuntimeError):
        execute_program(monkeypatch, extra_env=extra)
    assert helpers.execute_program.last_calls == []
    assert helpers.execute_program.last_closed == []
    assert capsys.readouterr().out == ""


# contract-test: tooling
def test_runner_gate_precedes_profile_read(tmp_path):
    def require_runner():
        raise RuntimeError("not a GitHub runner")

    with pytest.raises(RuntimeError, match="GitHub runner"):
        media.activate_isolated_authored_media_recovery_epoch(
            media.AUTHORED_MEDIA_RECOVERY_SPEC,
            compose_path=tmp_path / "missing",
            require_runner=require_runner,
            compose=lambda *_a, **_kw: pytest.fail("Container command reached"),
        )


# contract-test: tooling
def test_voice_stack_does_not_become_media_authority(tmp_path):
    with pytest.raises(RuntimeError, match="ordinary AI worker queues"):
        activate(tmp_path, helpers.profile())
    with pytest.raises(RuntimeError, match="exact voice browser spec"):
        helpers.activate(tmp_path, profile(), spec=media.AUTHORED_MEDIA_RECOVERY_SPEC)
