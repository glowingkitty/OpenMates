# contract-test-file: infrastructure
"""Real-inference CI runs reach only their providers with dev-only keys (TASK-5616).

The keys come from the protected `real-inference` GitHub environment and pass to
the run's throwaway Vault by name: the compose profile never holds a value, the
gateway lets HTTPS through only to the keyed providers, and uploaded stack logs
are redacted. Synthetic values only; no provider, Docker or network is used.
"""

import json

import pytest

from scripts import ci_tcp_gateway as gateway
from scripts.ci_environment import (
    ISOLATED_VAULT_PROVIDER_CHECK,
    REAL_INFERENCE_PROVIDERS,
    VAULT_INITIALIZE,
    compose_profile,
    redact_real_inference_logs,
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
