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
