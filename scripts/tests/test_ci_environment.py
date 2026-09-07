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
