# contract-test-file: infrastructure
"""The detached Docs E2E runs a real broker worker without provider egress."""

import pytest

from scripts.ci_environment import compose_profile


def test_detached_docs_requires_isolated_storage_profile() -> None:
    with pytest.raises(ValueError, match="isolated storage capacity"):
        compose_profile("a" * 40, detached_docs=True)


def test_detached_docs_adds_only_its_real_worker_queue() -> None:
    baseline = compose_profile("a" * 40, storage_capacity=True)
    profile = compose_profile("a" * 40, storage_capacity=True, detached_docs=True)
    core = profile["services"]["core-worker"]

    assert baseline["services"]["core-worker"]["environment"]["CELERY_QUEUES"].split(",")[-1] != "app_docs"
    assert core["environment"]["CELERY_QUEUES"].split(",")[-1] == "app_docs"
    assert "--queues=" + core["environment"]["CELERY_QUEUES"] in core["command"]
    assert profile["networks"]["default"]["internal"] is True
    assert profile["services"]["api"]["environment"]["MOCK_EXTERNAL_APIS"] == "true"
    assert profile["services"]["api"]["environment"]["OPENMATES_STORAGE_CAPACITY_FIXTURES"] == "true"
    for service in ("api", "core-worker", "ai-worker"):
        environment = profile["services"][service]["environment"]
        assert not any(key in environment for key in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
