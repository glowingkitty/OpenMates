# contract-test-file: infrastructure
"""Real-inference CI runs reach only their providers with dev-only keys (TASK-5616).

The keys come from the protected `real-inference` GitHub environment and pass to
the run's throwaway Vault by name: the compose profile never holds a value, the
gateway lets HTTPS through only to the keyed providers, and uploaded stack logs
are redacted. Synthetic values only; no provider, Docker or network is used.
"""

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

from scripts import ci_environment as ci
from scripts import ci_tcp_gateway as gateway
from scripts.ci_environment import (
    CODEX_REAL_INFERENCE_PROVIDERS,
    CODEX_REAL_INFERENCE_SPECS,
    CODEX_WEB_VOICE_PROVIDERS,
    CODEX_WEB_VOICE_SPEC,
    ISOLATED_VAULT_PROVIDER_CHECK,
    REAL_INFERENCE_PROVIDERS,
    VAULT_INITIALIZE,
    compose_profile,
    redact_real_inference_logs,
    selects_codex_real_inference,
    validate_real_inference_start,
)

KEY_NAMES = [name for _field, name in REAL_INFERENCE_PROVIDERS.values()]


def test_the_profile_passes_keys_by_name_and_routes_through_the_allowlist() -> None:
    profile = compose_profile("a" * 40, real_inference=True)
    services = profile["services"]
    vault_init = services["vault-init"]["environment"]

    assert all(vault_init[name] is None for name in KEY_NAMES)  # resolved from the start step only
    assert vault_init["CI_REAL_INFERENCE"] == "1"
    assert set(json.loads(vault_init["CI_REAL_INFERENCE_PROVIDERS"])) == set(REAL_INFERENCE_PROVIDERS)
    assert services["runner-gateway"]["environment"]["OPENMATES_CI_REAL_INFERENCE_PROXY"] == "1"
    assert "OPENMATES_CI_PUBLIC_PROVIDER_PROXY" not in services["runner-gateway"]["environment"]
    assert profile["networks"]["default"]["internal"] is True
    for name in ("api", "core-worker", "ai-worker"):
        environment = services[name]["environment"]
        assert environment["HTTPS_PROXY"] == "http://runner-gateway:3128"
        assert "OPENMATES_CI_AI_FIXTURES" not in environment
        assert not any(key in environment for key in KEY_NAMES)
    ai_worker = services["ai-worker"]
    assert ai_worker["environment"]["CELERY_QUEUES"] == "app_ai,app_ai_routing"
    assert "--queues=app_ai,app_ai_routing" in ai_worker["command"]
    assert "None" not in json.dumps(profile).replace("null", "")  # no stringified placeholder


def test_without_the_flag_no_key_name_or_allowlist_is_present() -> None:
    profile = json.dumps(compose_profile("a" * 40, ai_fixtures=True))
    assert not any(name in profile for name in KEY_NAMES)
    assert "OPENMATES_CI_REAL_INFERENCE" not in profile


@pytest.mark.parametrize("option", [{"ai_fixtures": True}, {"public_provider": True}, {"storage_capacity": True}, {"workflows": True}])
def test_real_inference_never_mixes_with_replay_profiles(option) -> None:
    with pytest.raises(ValueError, match="never mixed with replay"):
        compose_profile("a" * 40, real_inference=True, **option)


def test_the_internal_workflow_runtime_runs_with_real_inference() -> None:
    profile = compose_profile("a" * 40, real_inference=True, workflow_runtime=True)
    assert "workflow-scheduler" in profile["services"]
    assert "workflow" in profile["services"]["core-worker"]["environment"]["CELERY_QUEUES"].split(",")
    assert profile["services"]["ai-worker"]["environment"]["CELERY_QUEUES"] == "app_ai,app_ai_routing"


def test_image_skills_get_their_own_keyed_worker() -> None:
    services = compose_profile("a" * 40, real_inference=True)["services"]
    images = services["images-worker"]
    assert images["environment"]["CELERY_QUEUES"] == "app_images"
    assert any("--queues=app_images" in part for part in images["command"])
    assert images["environment"]["HTTPS_PROXY"] == "http://runner-gateway:3128"
    assert images["environment"]["OPENMATES_CI_REAL_INFERENCE"] == "1"
    assert "app_images" not in services["ai-worker"]["environment"]["CELERY_QUEUES"]


def test_the_vault_seeds_and_checks_exactly_the_keyed_providers() -> None:
    assert "CI_REAL_INFERENCE_PROVIDERS" in VAULT_INITIALIZE
    assert "Real-inference key missing" in VAULT_INITIALIZE
    assert "expected=sorted(expected+list(json.loads(os.environ['CI_REAL_INFERENCE_PROVIDERS'])))" in ISOLATED_VAULT_PROVIDER_CHECK


def test_the_gateway_allows_only_the_keyed_provider_hosts() -> None:
    allowed = gateway.REAL_INFERENCE_HOSTS
    assert gateway.public_provider_target(b"CONNECT generativelanguage.googleapis.com:443 HTTP/1.1\r\n", allowed) == (
        "generativelanguage.googleapis.com"
    )
    for line in (
        b"CONNECT api.openai.com:443 HTTP/1.1\r\n",
        b"CONNECT example.org:443 HTTP/1.1\r\n",
        b"CONNECT api.mistral.ai:80 HTTP/1.1\r\n",
        b"GET http://api.mistral.ai/ HTTP/1.1\r\n",
    ):
        with pytest.raises(ValueError):
            gateway.public_provider_target(line, allowed)
    with pytest.raises(ValueError):  # replay runs keep their own (empty) list
        gateway.public_provider_target(b"CONNECT api.mistral.ai:443 HTTP/1.1\r\n")


def test_uploaded_logs_never_carry_a_key() -> None:
    profile = compose_profile("a" * 40, real_inference=True)
    google = "AIza" + "x" * 35
    logs = "\n".join((
        f"ready {google}",
        '{"name": "httpx", "message": "POST https://generativelanguage.googleapis.com/v1/models"}',
        "GET https://api.example.org/search?q=1&key=synthetic-secret",
        "x-subscription-token: synthetic-brave-token",
        "Authorization: Bearer synthetic-mistral-token",
        "worker finished synthetic-env-value-123",
    ))
    redacted = redact_real_inference_logs(logs, profile, {KEY_NAMES[2]: "synthetic-env-value-123"})
    for secret in (google, "synthetic-secret", "synthetic-brave-token", "synthetic-mistral-token", "synthetic-env-value-123"):
        assert secret not in redacted
    assert '"name": "httpx"' not in redacted
    assert "worker finished" in redacted
    replay = compose_profile("a" * 40, ai_fixtures=True)
    assert redact_real_inference_logs(logs, replay, {}) == logs  # other runs are unchanged

CODEX_KEYS = {
    "OPENMATES_CODEX_REAL_INCEPTION_LABS_API_KEY", "OPENMATES_CODEX_REAL_TYPESAFE_API_KEY",
}
CODEX_TEST_ENV = {"CI_TEST_MODE": "e2e", "CI_CODEX_REAL_INFERENCE": "1"}
TRUSTED_REAL_SPECS = CODEX_REAL_INFERENCE_SPECS | {"real-inference-other.spec.ts"}


@pytest.mark.parametrize("spec", sorted(CODEX_REAL_INFERENCE_SPECS))
def test_only_an_individually_selected_trusted_terminal_spec_enters_the_codex_lane(spec):
    assert selects_codex_real_inference([spec], TRUSTED_REAL_SPECS, CODEX_TEST_ENV)
    for selected in ([spec, "real-inference-other.spec.ts"], [spec, spec], sorted(CODEX_REAL_INFERENCE_SPECS)):
        with pytest.raises(RuntimeError, match="one exact trusted terminal spec"):
            selects_codex_real_inference(selected, TRUSTED_REAL_SPECS, CODEX_TEST_ENV)
    with pytest.raises(RuntimeError, match="one exact trusted terminal spec"):
        selects_codex_real_inference([spec], TRUSTED_REAL_SPECS - {spec}, CODEX_TEST_ENV)
    with pytest.raises(RuntimeError, match="one exact trusted terminal spec"):
        selects_codex_real_inference([spec], TRUSTED_REAL_SPECS, {"CI_TEST_MODE": "e2e"})
    with pytest.raises(RuntimeError, match="one exact trusted terminal spec"):
        selects_codex_real_inference([spec], TRUSTED_REAL_SPECS, {**CODEX_TEST_ENV, "CI_TEST_MODE": "prepare"})
    assert not selects_codex_real_inference(["real-inference-other.spec.ts"], TRUSTED_REAL_SPECS, {})
    with pytest.raises(RuntimeError, match="one exact trusted terminal spec"):
        selects_codex_real_inference(["real-inference-other.spec.ts"], TRUSTED_REAL_SPECS, CODEX_TEST_ENV)


def test_codex_profile_uses_inception_and_typesafe_by_dedicated_vault_names_only():
    profile = compose_profile("a" * 40, real_inference=True, codex_real_inference=True)
    services = profile["services"]
    vault = services["vault-init"]["environment"]
    assert vault["CI_CODEX_VAULT_PRESEEDED"] == "1"
    assert "CI_REAL_INFERENCE_PROVIDERS" not in vault
    assert {name for _field, name in CODEX_REAL_INFERENCE_PROVIDERS.values()} == CODEX_KEYS
    assert not any(name in json.dumps(profile) for name in CODEX_KEYS)
    assert not set(KEY_NAMES).intersection(vault)
    assert not any(name in json.dumps(profile) for name in KEY_NAMES)
    assert services["runner-gateway"]["environment"]["OPENMATES_CI_REAL_INFERENCE_PROXY"] == "codex"
    assert profile["networks"]["default"]["internal"] is True
    assert "images-worker" not in services
    assert all(not {"ingress"}.intersection(service.get("networks", ()))
               for name, service in services.items() if name != "runner-gateway")
    assert all(not CODEX_KEYS.intersection(service.get("environment", {}))
               for name, service in services.items() if name != "vault-init")
    legacy = compose_profile("a" * 40, real_inference=True)
    assert not any(name in json.dumps(legacy) for name in CODEX_KEYS)


def test_codex_start_fails_closed_without_both_narrow_keys_and_the_right_profile():
    profile = compose_profile("a" * 40, real_inference=True, codex_real_inference=True)
    source = {
        **CODEX_TEST_ENV, "CI_SPECS_JSON": json.dumps([min(CODEX_REAL_INFERENCE_SPECS)]),
        **dict.fromkeys(KEY_NAMES, "synthetic-legacy-key"),
        "SECRET__INCEPTION_LABS__API_KEY": "synthetic-general-purpose-inception",
    }
    with pytest.raises(RuntimeError, match="protected codex-real-inference environment") as refused:
        validate_real_inference_start(profile, source, TRUSTED_REAL_SPECS)
    assert all(name in str(refused.value) for name in CODEX_KEYS)
    assert "synthetic" not in str(refused.value)
    source.update(dict.fromkeys(CODEX_KEYS, "synthetic-dedicated-key"))
    validate_real_inference_start(profile, source, TRUSTED_REAL_SPECS)
    legacy = compose_profile("a" * 40, real_inference=True)
    with pytest.raises(RuntimeError, match="dedicated isolated provider profile"):
        validate_real_inference_start(legacy, source, TRUSTED_REAL_SPECS)
    profile["services"]["api"]["networks"] = ["default", "ingress"]
    with pytest.raises(RuntimeError, match="dedicated isolated provider profile"):
        validate_real_inference_start(profile, source, TRUSTED_REAL_SPECS)
    del profile["services"]["api"]["networks"]
    profile["services"]["vault-init"]["environment"][KEY_NAMES[0]] = None
    with pytest.raises(RuntimeError, match="dedicated isolated provider profile"):
        validate_real_inference_start(profile, source, TRUSTED_REAL_SPECS)


def test_codex_gateway_denies_google_and_other_provider_authorities():
    allowed = gateway.provider_proxy_hosts({"OPENMATES_CI_REAL_INFERENCE_PROXY": "codex"})
    assert allowed == {"api.inceptionlabs.ai", "api.typesafe.ai"}
    for host in allowed:
        line = f"CONNECT {host}:443 HTTP/1.1\r\n".encode()
        assert gateway.public_provider_target(line, allowed) == host
    for host in gateway.REAL_INFERENCE_HOSTS - {"api.typesafe.ai"}:
        with pytest.raises(ValueError, match="destination is not approved"):
            gateway.public_provider_target(f"CONNECT {host}:443 HTTP/1.1\r\n".encode(), allowed)
    assert gateway.provider_proxy_hosts({"OPENMATES_CI_REAL_INFERENCE_PROXY": "1"}) == gateway.REAL_INFERENCE_HOSTS
    assert gateway.provider_proxy_hosts({}) is None
    with pytest.raises(RuntimeError, match="never share"):
        gateway.provider_proxy_hosts({
            "OPENMATES_CI_REAL_INFERENCE_PROXY": "codex", "OPENMATES_CI_PUBLIC_PROVIDER_PROXY": "1",
        })


def test_codex_workflow_binds_exact_specs_and_narrow_secrets_to_one_step():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/isolated-tests.yml"
    job = yaml.safe_load(path.read_text())["jobs"]["test"]
    dedicated = next(step for step in job["steps"] if step.get("name") == "Start isolated terminal real-inference backend")
    legacy = next(step for step in job["steps"] if step.get("name") == "Start isolated backend")
    for spec in CODEX_REAL_INFERENCE_SPECS:
        exact = f"inputs.specs_json == '[{json.dumps(spec)}]'"
        assert exact in job["environment"]
        assert exact in dedicated["if"]
        assert exact in legacy["if"]
    assert "'codex-real-inference'" in job["environment"]
    assert "'real-inference'" in job["environment"]
    assert {key for key in dedicated["env"] if key.endswith("_API_KEY")} == CODEX_KEYS
    assert {key for key in legacy["env"] if key.endswith("_API_KEY")} == set(KEY_NAMES)
    assert all(key not in job["env"] for key in CODEX_KEYS)
    assert "refs/heads/dev" in dedicated["run"]
    assert '"$GITHUB_SHA"' in dedicated["run"]


def test_codex_workflow_pins_consumer_checkout_and_checks_preparation_producer():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/isolated-tests.yml"
    job = yaml.safe_load(path.read_text())["jobs"]["test"]
    consumer_commit = job["env"]["CI_HARNESS_COMMIT"]
    for spec in CODEX_REAL_INFERENCE_SPECS:
        assert f"inputs.specs_json == '[{json.dumps(spec)}]'" in consumer_commit
    assert "inputs.mode == 'e2e'" in consumer_commit
    assert "github.sha || inputs.harness_commit || github.sha" in consumer_commit
    checkout = next(step for step in job["steps"] if step.get("with", {}).get("path") == "tooling")
    assert checkout["with"]["ref"] == "${{ env.CI_HARNESS_COMMIT }}"
    restore = next(step for step in job["steps"] if step.get("id") == "artifacts")
    assert restore["env"]["CI_PREPARATION_HARNESS_COMMIT"] == "${{ inputs.harness_commit || github.sha }}"
    assert '--harness-commit "$CI_PREPARATION_HARNESS_COMMIT"' in restore["run"]
    assert '--source "$BUILD_COMMIT_SHA"' in restore["run"]
    assert '--candidate-tree "$CI_CANDIDATE_TREE"' in restore["run"]


def test_codex_provider_keys_are_redacted_from_diagnostics():
    profile = compose_profile("a" * 40, real_inference=True, codex_real_inference=True)
    value = "synthetic-inception-credential-redacted"
    name = "OPENMATES_CODEX_REAL_INCEPTION_LABS_API_KEY"
    assert redact_real_inference_logs(f"startup {value}", profile, {name: value}) == "startup <REDACTED>"


@pytest.fixture(params=["terminal", "voice"])
def scoped_lane(request, tmp_path, monkeypatch):
    web_voice = request.param == "voice"
    spec = CODEX_WEB_VOICE_SPEC if web_voice else min(CODEX_REAL_INFERENCE_SPECS)
    profile = compose_profile("a" * 40, real_inference=True,
                              codex_real_inference=not web_voice, codex_web_voice=web_voice)
    providers = CODEX_WEB_VOICE_PROVIDERS if web_voice else CODEX_REAL_INFERENCE_PROVIDERS
    results = tmp_path / "test-results"
    private = results / "ci-private"
    private.mkdir(parents=True)
    compose_path = private / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(ci, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(ci, "SOURCE", str(tmp_path))
    monkeypatch.setattr(ci, "require_runner", lambda: None)
    for name in (*ci.PROVIDER_KEY_ALIASES, "CI_CODEX_REAL_INFERENCE", "CI_CODEX_WEB_VOICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CI_CODEX_WEB_VOICE" if web_voice else "CI_CODEX_REAL_INFERENCE", "1")
    monkeypatch.setenv("CI_TEST_MODE", "e2e")
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps([spec]))
    return results, providers


@pytest.mark.parametrize("failed", [False, True])
def test_scoped_vault_stdin_seed_never_reaches_console_or_saved_artifacts(
    scoped_lane, monkeypatch, capsys, failed,
):
    results, providers = scoped_lane
    secrets = {name: f"SYNTHETIC_{provider.upper()}_BULK_DIAGNOSTIC_SENTINEL"
               for provider, (_field, name) in providers.items()}
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(KEY_NAMES[0], "SYNTHETIC_LEGACY_NOT_FOR_SCOPED")
    container = "a" * 64
    image = "sha256:" + "b" * 64
    calls = []
    raw = " xi-api-key: " + " ".join(secrets.values())
    def docker(args, **kwargs):
        assert ci.PROVIDER_KEY_ALIASES.isdisjoint(os.environ)
        assert all(name not in str(args) for name in secrets)
        assert all(value not in str(args) for value in secrets.values())
        assert args[:3] == ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]
        calls.append((args, kwargs))
        if "up" in args:
            assert args[-1] == "vault"
            return SimpleNamespace(stdout=raw, stderr=raw)
        if "ps" in args:
            return SimpleNamespace(stdout=container, stderr=raw)
        assert args[3:7] == ["exec", "-i", container, "vault"]
        if failed and "kv/data/providers/inception_labs" in args:
            raise subprocess.CalledProcessError(7, args, output=raw, stderr=raw)
        return SimpleNamespace(stdout=raw, stderr=raw)
    def inspect(args, **kwargs):
        assert kwargs["stderr"] is subprocess.PIPE
        assert ci.PROVIDER_KEY_ALIASES.isdisjoint(os.environ)
        return image if "image" in args else f"{image} {ci.SCOPED_CODEX_VAULT_IMAGE} true"
    monkeypatch.setattr(ci.subprocess, "run", docker)
    monkeypatch.setattr(ci.subprocess, "check_output", inspect)
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "seed"])
    if failed:
        with pytest.raises(SystemExit, match="1"):
            ci.main()
    else:
        ci.main()
    output = capsys.readouterr()
    assert not any(secret in output.out + output.err for secret in secrets.values())
    report = results / "ci-vault-seed.json"
    assert json.loads(report.read_text()) == {"outcome": "failed" if failed else "ready"}
    for file in results.rglob("*.json"):
        assert all(value not in file.read_text() for value in secrets.values())
    assert calls[2][0][-2:] == ["sys/mounts/kv", "-"]
    assert json.loads(calls[2][1]["input"]) == {"type": "kv", "options": {"version": "2"}}
    if not failed:
        payloads = {args[-2]: json.loads(options["input"])
                    for args, options in calls[3:]}
        assert payloads == {
            f"kv/data/providers/{provider}": {"data": {field: secrets[name]}}
            for provider, (field, name) in providers.items()
        }


@pytest.mark.parametrize("failed", [False, True])
def test_scoped_start_and_logs_keep_closed_receipts_when_subprocess_outputs_contain_credentials(
    scoped_lane, monkeypatch, capsys, failed,
):
    results, providers = scoped_lane
    raw = "SYNTHETIC_PROVIDER_SECRET_IN_BOOTSTRAP_STDERR"
    calls = []
    def compose(*args, **kwargs):
        calls.append(args)
        if args[0] == "up":
            if failed:
                raise subprocess.CalledProcessError(7, args, output=raw, stderr=raw)
            return SimpleNamespace(stdout=raw, stderr=raw)
        assert args == ("ps", "-aq")
        return SimpleNamespace(stdout="a" * 64, stderr=raw)
    def inspect(args, **kwargs):
        assert ".State.Health" in args[-2]
        assert args[-2] != "{{json .State}}"
        return json.dumps({"service": "vault", "status": "running", "exit_code": 0,
                           "health": "healthy", "started": "2026-11-26T13:06:00Z",
                           "finished": "2026-11-26T13:06:00Z", "unparsed": raw})
    def verify_seed(actual, *, seeded_only):
        assert actual == providers and seeded_only
    monkeypatch.setattr(ci, "compose", compose)
    monkeypatch.setattr(ci, "docker_output", inspect)
    monkeypatch.setattr(ci, "verify_scoped_vault_provider_namespace", verify_seed)
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "start"])
    if failed:
        with pytest.raises(SystemExit, match="1"):
            ci.main()
    else:
        ci.main()
    startup = (results / "ci-startup-phases.json").read_text()
    assert raw not in startup
    assert json.loads(startup)["outcome"] == ("failed" if failed else "ready")
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "logs"])
    for label in ("", "spec-1"):
        monkeypatch.setenv("CI_DIAGNOSTIC_LABEL", label)
        ci.main()
        report = results / (f"ci-stack-{label}.log" if label else "ci-stack.log")
        assert raw not in report.read_text()
        assert json.loads(report.read_text())["services"][0]["health"] == "healthy"
    output = capsys.readouterr()
    assert raw not in output.out + output.err
    assert not any(call[0] == "logs" for call in calls)


def test_scoped_namespace_checks_exact_paths_before_and_after_candidate_bootstrap(scoped_lane, monkeypatch):
    _, providers = scoped_lane
    names = sorted(providers)
    monkeypatch.setattr(ci, "scoped_vault_container", lambda: "verified-vault")
    def list_names(container, *args):
        assert container == "verified-vault"
        assert args == ("list", "-format=json", "kv/metadata/providers")
        return json.dumps(names)
    monkeypatch.setattr(ci, "scoped_vault_command", list_names)
    ci.verify_scoped_vault_provider_namespace(providers, seeded_only=True)
    names.extend(["core_server", "vapid"])
    ci.verify_scoped_vault_provider_namespace(providers)
    names.append("unexpected")
    with pytest.raises(RuntimeError, match="does not match"):
        ci.verify_scoped_vault_provider_namespace(providers)


@pytest.mark.parametrize("failed", [False, True])
def test_scoped_teardown_never_prints_failure_diagnostic_details(scoped_lane, monkeypatch, capsys, failed):
    results, _ = scoped_lane
    raw = "SYNTHETIC_PROVIDER_KEY_IN_CLEANUP_DIAGNOSTIC"
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    def cleanup(args, **kwargs):
        assert kwargs["capture_output"] is True and "down" in args
        if failed:
            raise subprocess.CalledProcessError(3, args, output=raw, stderr=raw)
        return SimpleNamespace(stdout=raw, stderr=raw)
    def inspect(args, **kwargs):
        assert kwargs["stderr"] is subprocess.PIPE
        return ""
    monkeypatch.setattr(ci.subprocess, "run", cleanup)
    monkeypatch.setattr(ci.subprocess, "check_output", inspect)
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "stop"])
    if failed:
        with pytest.raises(SystemExit, match="1"):
            ci.main()
        assert not (results / "ci-cleanup.json").exists()
    else:
        ci.main()
        receipt = (results / "ci-cleanup.json").read_text()
        assert raw not in receipt
        assert json.loads(receipt)["containers_remaining"] == 0
    output = capsys.readouterr()
    assert raw not in output.out + output.err


def test_scoped_workflow_uploads_only_closed_receipts_and_expected_proof_files():
    path = Path(__file__).resolve().parents[2] / ".github/workflows/isolated-tests.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["test"]["steps"]
    scoped = next(step for step in steps if step.get("name") == "Upload bounded scoped Codex receipts and proof media")
    ordinary = next(step for step in steps if step.get("with", {}).get("name") == "isolated-test-results"
                    and step is not scoped)
    for flag in ("CI_CODEX_REAL_INFERENCE", "CI_CODEX_WEB_VOICE"):
        assert f"env.{flag} != '1'" in ordinary["if"]
    paths = scoped["with"]["path"]
    assert "ci-results.json" in paths and "ci-startup-phases.json" in paths
    assert "steps.scoped_proof.outcome == 'success' && steps.scoped_proof.outputs.paths" in paths
    assert "frontend/apps/web_app/test-results" not in paths
    assert "steps.scoped_recipe_progress.outcome == 'success' && steps.scoped_recipe_progress.outputs.path" in paths
    progress_gate = next(step for step in steps if step.get("id") == "scoped_recipe_progress")
    assert progress_gate["if"].startswith("always()")
    assert f'inputs.specs_json == \'["{ci.SCOPED_RECIPE_SPEC}"]\'' in progress_gate["if"]
    assert progress_gate["run"].strip().endswith(" recipe-progress")
    proof_gate = next(step for step in steps if step.get("id") == "scoped_proof")
    assert "success()" in proof_gate["if"] and proof_gate["run"].endswith(" proof")
    assert scoped["if"].startswith("always()")
    assert ci.SCOPED_PROOF_FILES == {
        "real-inference-tui-chat-processing.spec.ts": (
            "rust-terminal-real-chat-processing/raw-terminal.mp4",
        ),
        "real-inference-tui-artifact-steering.spec.ts": (
            "rust-terminal-artifact-steering/raw-terminal.mp4",
            "rust-terminal-artifact-revised-source/raw-terminal.mp4",
        ),
        CODEX_WEB_VOICE_SPEC: ("signed-in-voice-with-audio.webm", "real-web-voice-timing.json"),
    }
    for freeform in ("trace.zip", "transcript.txt", "ci-spec-", "ci-web.log", "test-results/\n",
                     "/video.webm", "voice-proof-local", "proof-audio-manifest"):
        assert freeform not in paths
    unkeyed = next(step for step in steps if step.get("name") ==
                   "Start and verify scoped Codex backend without provider environment")
    assert "env" not in unkeyed and " start\n" in unkeyed["run"] and " verify\n" in unkeyed["run"]


@pytest.mark.parametrize("option", ["configs", "secrets", "post_start", "env_file"])
def test_scoped_seed_rejects_vault_service_overrides(scoped_lane, option):
    _, providers = scoped_lane
    profile = json.loads(ci.COMPOSE_PATH.read_text())
    profile["services"]["vault"][option] = ["candidate-config"]
    credentials = {alias: "synthetic-secret" for _, alias in providers.values()}
    selection = json.loads(os.environ["CI_SPECS_JSON"])
    with pytest.raises(RuntimeError, match="dedicated isolated provider profile"):
        ci.validate_real_inference_start(profile, {**os.environ, **credentials}, set(selection))


def test_scoped_proof_slot_matches_the_actual_playwright_e2e_executor():
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts/ci_run_tests.py").read_text()
    assert "for index, name in enumerate(specs):" in runner  # Python enumerate starts at zero.
    assert '--output",\n                                    f"test-results/ci-{index}"' in runner
    assert ci.SCOPED_PLAYWRIGHT_OUTPUT == Path("frontend/apps/web_app/test-results/ci-0")


def scoped_proof_fixture(root, spec, *, slot="ci-0"):
    case = root / ci.SCOPED_PLAYWRIGHT_OUTPUT.parent / slot / "scoped-case-chromium"
    for name in ci.SCOPED_PROOF_FILES[spec]:
        output = case / name
        output.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".json"):
            output.write_text(json.dumps({
                "sourceCommit": "a" * 40, "sameEncryptedChat": True, "sampleRate": 48000,
                "lastVoicedToCueMs": None, "lastVoicedToSubstantiveMs": 625.25,
                "lastVoicedToFinalTranscriptMs": 192, "lastVoicedToPlaybackMs": 625.25,
            }))
        else:
            output.write_bytes(b"synthetic recording")
    return case


@pytest.mark.parametrize("spec", sorted(ci.SCOPED_PROOF_FILES))
def test_success_uploads_only_expected_nonempty_proof_from_slot_zero(tmp_path, spec):
    scoped_proof_fixture(tmp_path, spec, slot="ci-1")
    with pytest.raises(ValueError, match="output directory"):
        ci.scoped_proof_paths(tmp_path, spec, "a" * 40)
    case = scoped_proof_fixture(tmp_path, spec)
    for extra in ("video.webm", "trace.zip", "transcript.txt", "login-video.mp4"):
        (case / extra).write_bytes(b"synthetic excluded output")
    expected = [(case / name).relative_to(tmp_path) for name in ci.SCOPED_PROOF_FILES[spec]]
    assert ci.scoped_proof_paths(tmp_path, spec, "a" * 40) == expected
    (tmp_path / expected[0]).write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        ci.scoped_proof_paths(tmp_path, spec, "a" * 40)


def test_scoped_proof_refuses_symlinks_and_duplicate_recordings(tmp_path):
    spec = "real-inference-tui-chat-processing.spec.ts"
    case = scoped_proof_fixture(tmp_path, spec)
    expected = case / ci.SCOPED_PROOF_FILES[spec][0]
    target = case / "login-video.mp4"
    target.write_bytes(b"synthetic login media")
    expected.unlink()
    expected.symlink_to(target)
    with pytest.raises(ValueError, match="regular parent paths"):
        ci.scoped_proof_paths(tmp_path, spec, "a" * 40)
    expected.unlink()
    expected.write_bytes(b"synthetic recording")
    duplicate = case.parent / "second-case" / expected.relative_to(case)
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"duplicate")
    with pytest.raises(ValueError, match="one scoped proof file"):
        ci.scoped_proof_paths(tmp_path, spec, "a" * 40)


@pytest.mark.parametrize("changes", [
    {"lastVoicedToSubstantiveMs": float("nan")},
    {"lastVoicedToSubstantiveMs": "synthetic unapproved data"},
    {"lastVoicedToCueMs": 9999},
    {"sampleRate": True},
    {"sourceCommit": "b" * 40},
    {"sameEncryptedChat": False},
    {"debug": "synthetic unapproved data"},
])
def test_scoped_voice_timing_rejects_open_or_invalid_values(tmp_path, changes):
    case = scoped_proof_fixture(tmp_path, CODEX_WEB_VOICE_SPEC)
    receipt = case / "real-web-voice-timing.json"
    receipt.write_text(json.dumps({**json.loads(receipt.read_text()), **changes}))
    with pytest.raises(ValueError, match="invalid"):
        ci.scoped_proof_paths(tmp_path, CODEX_WEB_VOICE_SPEC, "a" * 40)


def test_scoped_proof_step_fails_closed_before_writing_any_upload_path(scoped_lane, tmp_path, monkeypatch, capsys):
    spec = json.loads(os.environ["CI_SPECS_JSON"])[0]
    case = scoped_proof_fixture(tmp_path, spec)
    gate_output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gate_output))
    monkeypatch.setenv("BUILD_COMMIT_SHA", "a" * 40)
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "proof"])
    required = case / ci.SCOPED_PROOF_FILES[spec][-1]
    original = required.read_bytes()
    required.unlink()
    with pytest.raises(SystemExit, match="1"):
        ci.main()
    assert not gate_output.exists()
    assert "Scoped CI proof requires" in capsys.readouterr().err
    required.write_bytes(original)
    ci.main()
    assert len(gate_output.read_text().splitlines()) == len(ci.SCOPED_PROOF_FILES[spec]) + 2
    assert gate_output.read_text().count("subject/frontend/apps/web_app/test-results/ci-0/") == len(ci.SCOPED_PROOF_FILES[spec])


def test_failed_recipe_keeps_only_the_bounded_progress_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_TEST_MODE", "e2e")
    monkeypatch.setenv("CI_CODEX_REAL_INFERENCE", "1")
    monkeypatch.delenv("CI_CODEX_WEB_VOICE", raising=False)
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps([ci.SCOPED_RECIPE_SPEC]))
    monkeypatch.setenv("CI_SCOPED_PROOF_PASSED", "0")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(ci, "SOURCE", str(tmp_path))
    monkeypatch.setattr(ci, "require_runner", lambda: None)
    monkeypatch.setattr(sys, "argv", ["ci_environment.py", "recipe-progress"])

    # No receipt is available if the browser test never starts.
    ci.main()
    assert not output.exists()

    case = tmp_path / ci.SCOPED_PLAYWRIGHT_OUTPUT / "scoped-case-chromium"
    case.mkdir(parents=True)
    path = case / ci.SCOPED_RECIPE_PROGRESS
    path.write_text('{"schemaVersion":1,"phases":{"started":0,"original_sent":624}}')
    (case / "trace.zip").write_bytes(b"synthetic excluded output")
    ci.main()
    assert output.read_text() == f"path=subject/{path.relative_to(tmp_path).as_posix()}\n"

    # A successful recipe needs its terminal marker, and the chat lane cannot
    # publish a recipe checkpoint even if the file happens to be present.
    monkeypatch.setenv("CI_SCOPED_PROOF_PASSED", "1")
    with pytest.raises(SystemExit, match="1"):
        ci.main()
    path.write_text('{"schemaVersion":1,"phases":{"started":0,"passed":1000}}')
    assert ci.scoped_recipe_progress_path(tmp_path, required=True) == path.relative_to(tmp_path)
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps(["real-inference-tui-chat-processing.spec.ts"]))
    with pytest.raises(SystemExit, match="1"):
        ci.main()


@pytest.mark.parametrize("payload", [
    '{"schemaVersion":1,"phases":{"started":0,"synthetic-secret":100}}',
    '{"schemaVersion":1,"phases":{"started":0,"original_sent":"synthetic-secret"}}',
    '{"schemaVersion":1,"phases":{"started":0,"original_sent":3600001}}',
    '{"schemaVersion":1,"phases":{"started":"synthetic-secret","started":0}}',
    '{"schemaVersion":1,"phases":{"started":0},"detail":"synthetic-secret"}',
])
def test_scoped_recipe_progress_rejects_unknown_or_unbounded_data(payload, tmp_path):
    case = tmp_path / ci.SCOPED_PLAYWRIGHT_OUTPUT / "scoped-case-chromium"
    case.mkdir(parents=True)
    (case / ci.SCOPED_RECIPE_PROGRESS).write_text(payload)
    with pytest.raises(ValueError) as refused:
        ci.scoped_recipe_progress_path(tmp_path, required=False)
    assert "synthetic-secret" not in str(refused.value)
