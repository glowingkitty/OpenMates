# backend/tests/test_openai_openrouter.py
#
# Unit coverage for OpenRouter routing contracts used by provider YAML models.
# These tests avoid live provider calls and secrets; live smoke tests remain
# manual/session evidence because they consume paid OpenRouter credits.
# They guard model-id transformation and OpenRouter-native namespace passthrough.

import logging

from backend.apps.ai.llm_providers import openai_openrouter
from backend.apps.ai.utils import llm_utils


class _DummyConfigManager:
    def __init__(self, provider_configs):
        self._provider_configs = provider_configs

    def get_provider_config(self, provider_id):
        return self._provider_configs.get(provider_id)


def test_zai_glm_52_resolves_to_openrouter_model(monkeypatch):
    monkeypatch.setattr(
        llm_utils,
        "config_manager",
        _DummyConfigManager(
            {
                "zai": {
                    "models": [
                        {
                            "id": "zai-glm-5.2",
                            "default_server": "openrouter",
                            "servers": [
                                {
                                    "id": "openrouter",
                                    "model_id": "z-ai/glm-5.2",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
    )

    server_id, transformed_model_id = llm_utils.resolve_default_server_from_provider_config(
        "zai/zai-glm-5.2"
    )

    assert server_id == "openrouter"
    assert transformed_model_id == "openrouter/z-ai/glm-5.2"


def test_openrouter_native_namespace_without_config_is_passthrough(monkeypatch, caplog):
    monkeypatch.setattr(openai_openrouter, "config_manager", _DummyConfigManager({}))
    caplog.set_level(logging.WARNING)

    provider_overrides = openai_openrouter._get_provider_overrides_for_model("z-ai/glm-5.2")

    assert provider_overrides is None
    assert not caplog.records
