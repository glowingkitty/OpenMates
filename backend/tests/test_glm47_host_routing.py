"""Archived GLM hosts must not be offered as primary or fallback routes."""
# contract-test-file: infrastructure

from pathlib import Path

import yaml

from backend.apps.ai.utils import llm_utils


def test_glm47_routing_excludes_retired_cerebras_host(monkeypatch):
    provider = yaml.safe_load((Path(__file__).parents[1] / "providers/zai.yml").read_text())
    monkeypatch.setattr(llm_utils.config_manager, "get_provider_config", lambda _: provider)
    primary, _ = llm_utils.resolve_default_server_from_provider_config("zai/zai-glm-4.7")
    fallbacks = llm_utils.resolve_fallback_servers_from_provider_config("zai/zai-glm-4.7")
    assert primary == "aws_bedrock"
    assert all(route.split("/", 1)[0] != "cerebras" for route in [primary, *fallbacks])
    assert any(route.startswith("openrouter/") for route in fallbacks)
