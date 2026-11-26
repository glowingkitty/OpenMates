# contract-test-file: infrastructure
"""Real-inference CI runs reach only their providers with dev-only keys (TASK-5616).

The keys come from the protected `real-inference` GitHub environment and pass to
the run's throwaway Vault by name: the compose profile never holds a value, the
gateway lets HTTPS through only to the keyed providers, and uploaded stack logs
are redacted. Synthetic values only; no provider, Docker or network is used.
"""

import json
from pathlib import Path

import pytest
import yaml

from scripts import ci_tcp_gateway as gateway
from scripts.ci_environment import (
    CODEX_REAL_INFERENCE_PROVIDERS,
    CODEX_REAL_INFERENCE_SPECS,
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
    assert set(json.loads(vault["CI_REAL_INFERENCE_PROVIDERS"])) == {"inception_labs", "typesafe"}
    assert {name for _field, name in CODEX_REAL_INFERENCE_PROVIDERS.values()} == CODEX_KEYS
    assert all(vault[name] is None for name in CODEX_KEYS)
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


def test_codex_provider_keys_are_redacted_from_diagnostics():
    profile = compose_profile("a" * 40, real_inference=True, codex_real_inference=True)
    value = "synthetic-inception-credential-redacted"
    name = "OPENMATES_CODEX_REAL_INCEPTION_LABS_API_KEY"
    assert redact_real_inference_logs(f"startup {value}", profile, {name: value}) == "startup <REDACTED>"
