# contract-test-file: tooling
"""Validate disposable CI environment boundaries without starting Docker.

The runner profile must never mount operator secrets or the Docker socket.
All API and worker source mounts must identify the same checkout revision.
A local invocation must fail before invoking any Docker command.
See docs/plans/isolated-github-tests/plan.yml.
"""

import pytest
from scripts.ci_environment import compose_profile, require_runner


def test_profile_is_private_and_source_bound():
    profile = compose_profile("a" * 40)
    assert profile["name"] == "openmates-ci"
    for service in profile["services"].values():
        assert service["labels"]["org.openmates.source"] == "a" * 40
        assert service["extra_hosts"]["api.dev.openmates.org"] == "127.0.0.2"
        assert not service.get("privileged")
        assert not service.get("env_file")
        assert all(
            ".env:" not in str(mount) and "docker.sock" not in str(mount)
            for mount in service.get("volumes", [])
        )
    assert (
        profile["services"]["api"]["image"]
        == profile["services"]["core-worker"]["image"]
    )


def test_fresh_credentials_and_runner_only(monkeypatch):
    a = compose_profile("a" * 40)
    b = compose_profile("a" * 40)
    assert (
        a["services"]["cms-database"]["environment"]
        != b["services"]["cms-database"]["environment"]
    )
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError, match="GitHub-hosted"):
        require_runner()


def test_named_volumes_have_one_explicit_fixture_writer():
    services = compose_profile("a" * 40)["services"]
    for service in services.values():
        for mount in service.get("volumes", []):
            if isinstance(mount, dict):
                assert mount["volume"]["nocopy"] is True
    for name in ("api", "core-worker"):
        assert (
            services[name]["depends_on"]["fixture-init"]["condition"]
            == "service_completed_successfully"
        )
    assert services["fixture-init"]["volumes"][0]["source"] == "api-cache"


def test_vault_initializer_issues_scoped_token_and_uses_startup_validator(
    tmp_path, monkeypatch
):
    import httpx
    import requests
    from scripts.ci_environment import VAULT_INITIALIZE

    policies = {}

    class Response:
        status_code = 204

        def raise_for_status(self):
            return None

        def json(self):
            return {"auth": {"client_token": "scoped-ci-token"}}

    def request(method, url, **kwargs):
        if "/sys/policies/acl/" in url:
            policies[url.rsplit("/", 1)[1]] = kwargs["json"]["policy"]
        if url.endswith("auth/token/create"):
            assert set(kwargs["json"]["policies"]) == {"api-service", "api-encryption"}
            assert kwargs["json"]["ttl"] == "2h"
        return Response()

    monkeypatch.setattr(requests, "request", request)
    monkeypatch.setattr(
        requests, "post", lambda url, **kwargs: request("post", url, **kwargs)
    )

    def lookup(request):
        assert request.headers["X-Vault-Token"] == "scoped-ci-token"
        return httpx.Response(
            200, json={"data": {"policies": list(policies), "ttl": 7200}}
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(lookup)),
    )
    monkeypatch.setenv("VAULT_TOKEN", "synthetic-root-token")
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "synthetic-internal-token")
    program = VAULT_INITIALIZE.replace("/vault-data/", str(tmp_path) + "/")
    exec(compile(program, "<ci-vault-init>", "exec"), {})
    assert (tmp_path / "api.token").read_text() == "scoped-ci-token"
    assert "transit/encrypt/*" in policies["api-encryption"]
    assert "kv/data/providers/*" in policies["api-service"]


def test_api_and_worker_receive_the_private_cms_admin_identity():
    services = compose_profile("a" * 40)["services"]
    cms = services["cms"]["environment"]
    for service in ("api", "core-worker", "cms-setup"):
        environment = services[service]["environment"]
        assert environment["DATABASE_ADMIN_EMAIL"] == cms["ADMIN_EMAIL"]
        assert environment["DATABASE_ADMIN_PASSWORD"] == cms["ADMIN_PASSWORD"]


def test_committed_ai_fixtures_have_worker_and_no_external_network():
    profile = compose_profile("a" * 40, ai_fixtures=True)
    assert profile["networks"]["default"]["internal"] is True
    worker = profile["services"]["ai-worker"]
    assert worker["environment"]["CELERY_QUEUES"] == "app_ai"
    assert "--queues=app_ai" in worker["command"]
    assert worker["image"] == profile["services"]["api"]["image"]
    assert "ai-worker" not in compose_profile("a" * 40)["services"]


def test_cleanup_removes_only_disposable_accounts_and_records_evidence(tmp_path, monkeypatch):
    from scripts import ci_environment as runtime
    import json
    private = tmp_path / "test-results/ci-private"
    private.mkdir(parents=True)
    (private / "compose.json").write_text("{}")
    (private / "account.env").write_text("synthetic")
    monkeypatch.setattr(runtime, "SOURCE", str(tmp_path))
    monkeypatch.setattr(runtime, "COMPOSE_PATH", private / "compose.json")
    monkeypatch.setattr(runtime, "require_runner", lambda: None)
    monkeypatch.setattr(runtime, "compose", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setattr(runtime.sys, "argv", ["ci_environment.py", "stop"])
    monkeypatch.setenv("GITHUB_RUN_ID", "synthetic-run")
    runtime.main()
    assert not private.exists()
    assert json.loads((tmp_path / "test-results/ci-cleanup.json").read_text())["private_account_files_removed"] is True


def test_runtime_uses_candidate_development_feature_configuration():
    profile = compose_profile("a" * 40, ai_fixtures=True)
    for service in ("api", "core-worker", "ai-worker"):
        assert profile["services"][service]["environment"]["BACKEND_CONFIG_FILE"] == "/app/backend/config/backend_config.dev.yml"


def test_fixture_network_only_exposes_uncredentialed_tcp_gateway():
    profile = compose_profile("a" * 40, ai_fixtures=True)
    services = profile["services"]
    assert "ports" not in services["api"] and "ports" not in services["cms"]
    assert services["runner-gateway"]["ports"] == ["127.0.0.1:8000:8000", "127.0.0.1:8055:8055"]
    assert services["runner-gateway"]["environment"] == {"OPENMATES_CI_GATEWAY": "github-isolated"}
    assert all("ingress" not in service.get("networks", []) for name, service in services.items() if name != "runner-gateway")


def test_replay_allowlist_contains_only_this_runs_new_identities(monkeypatch):
    from backend.shared.python_utils.e2e_user_detection import is_configured_test_account_profile
    import hashlib
    import base64
    import os
    monkeypatch.setenv("OPENMATES_TEST_ACCOUNT_1_EMAIL", "legacy@example.net")
    fresh = ["ci-first@example.com", "ci-second@example.com"]
    profile = compose_profile("a" * 40, ai_fixtures=True, account_emails=fresh)
    env = profile["services"]["api"]["environment"]
    assert "OPENMATES_TEST_ACCOUNT_1_EMAIL" not in env
    for key in list(os.environ):
        if key.startswith("OPENMATES_TEST_ACCOUNT"):
            monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    def hashed(email):
        return base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    assert is_configured_test_account_profile({"hashed_email": hashed(fresh[0])})
    assert not is_configured_test_account_profile({"hashed_email": hashed("legacy@example.net")})
    assert not is_configured_test_account_profile({"hashed_email": hashed("ci-other-run@example.com")})
    with pytest.raises(ValueError, match="unique generated"):
        compose_profile("a" * 40, account_emails=[fresh[0], fresh[0]])


def test_object_storage_uses_fresh_local_credentials_and_real_pinned_server():
    a = compose_profile("a" * 40, object_storage=True)
    b = compose_profile("a" * 40, object_storage=True)
    services = a["services"]
    store = services["object-storage"]
    assert "@sha256:" in store["image"]
    assert store["ports"] == ["127.0.0.1:9000:9000"]
    assert store["environment"] != b["services"]["object-storage"]["environment"]
    for name in ("api", "core-worker"):
        assert services[name]["environment"]["S3_ENDPOINT_URL"] == "http://storage.ci.test:9000"
        assert services[name]["environment"]["S3_REGIONS"] == "nbg1"
        assert services[name]["depends_on"]["object-storage"]["condition"] == "service_healthy"
    assert services["vault-init"]["environment"]["CI_STORAGE_ACCESS_KEY"] == store["environment"]["AWS_ACCESS_KEY_ID"]
    assert "object-storage" not in compose_profile("a" * 40)["services"]
