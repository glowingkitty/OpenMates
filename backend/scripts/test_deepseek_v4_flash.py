#!/usr/bin/env python3
# backend/scripts/test_deepseek_v4_flash.py
#
# Live verification script for DeepSeek V4 Flash via OpenRouter.
# Confirms the provider YAML entry resolves, AtlasCloud provider routing is
# configured, and the OpenRouter chat completion path can invoke the model.

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def test_deepseek_v4_flash() -> int:
    from backend.apps.ai.llm_providers.openai_openrouter import (
        invoke_openrouter_chat_completions,
    )
    from backend.core.api.app.utils.config_manager import config_manager
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    provider_id = "deepseek"
    model_id = "deepseek-v4-flash"
    openrouter_model_id = "deepseek/deepseek-v4-flash"

    print("\n" + "=" * 80)
    print("DEEPSEEK V4 FLASH OPENROUTER TEST")
    print("=" * 80 + "\n")

    model_config = config_manager.get_model_pricing(provider_id, model_id)
    if not model_config:
        print(f"FAIL: Missing provider config for {provider_id}/{model_id}")
        return 1

    servers = model_config.get("servers", [])
    openrouter_server = next(
        (
            server
            for server in servers
            if server.get("id") == "openrouter"
            and server.get("model_id") == openrouter_model_id
        ),
        None,
    )
    if not openrouter_server:
        print("FAIL: Missing OpenRouter server mapping")
        return 1

    provider_overrides = model_config.get("provider_overrides", {})
    if provider_overrides.get("order") != ["atlas-cloud"]:
        print(f"FAIL: Expected AtlasCloud provider order, got {provider_overrides}")
        return 1

    print(f"Config OK: {model_config.get('name')}")
    print(f"OpenRouter model: {openrouter_model_id}")
    print(f"Provider routing: {provider_overrides}")

    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
    except Exception as exc:
        print(f"FAIL: Could not initialize SecretsManager: {exc}")
        return 1

    response = await invoke_openrouter_chat_completions(
        task_id="test_deepseek_v4_flash_openrouter",
        model_id=openrouter_model_id,
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly: deepseek-v4-flash-ok",
            }
        ],
        secrets_manager=secrets_manager,
        temperature=0,
        max_tokens=32,
        stream=False,
    )

    if not response.success:
        print(f"FAIL: OpenRouter call failed: {response.error_message}")
        return 1

    content = (response.direct_message_content or "").strip()
    if "deepseek-v4-flash-ok" not in content.lower():
        print(f"FAIL: Unexpected response: {content}")
        return 1

    print(f"OpenRouter OK: {content}")
    if response.usage:
        print(f"Usage: {response.usage.total_tokens} tokens")

    print("\nTEST PASSED\n")
    return 0


if __name__ == "__main__":
    sys.path.append("/app")
    raise SystemExit(asyncio.run(test_deepseek_v4_flash()))
