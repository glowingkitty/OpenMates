#!/usr/bin/env python3
# backend/scripts/test_anthropic_sonnet_4_6.py
#
# Integration test script for Claude Sonnet 4.6 via Anthropic API and OpenRouter.
# Tests basic completion, streaming, tool use, and the OpenRouter fallback path.
#
# Run from project root:
#   docker exec api python /app/backend/scripts/test_anthropic_sonnet_4_6.py

import asyncio
import sys
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def test_sonnet_4_6():
    print("\n" + "="*80)
    print("CLAUDE SONNET 4.6 INTEGRATION TESTS (Anthropic Direct & OpenRouter)")
    print("="*80 + "\n")

    # Import required modules
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.apps.ai.llm_providers.anthropic_client import invoke_anthropic_chat_completions
    from backend.apps.ai.llm_providers.openai_openrouter import invoke_openrouter_chat_completions
    from backend.core.api.app.utils.config_manager import config_manager

    # Initialize SecretsManager
    print("Initializing SecretsManager and Vault connection...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized.")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        return 1

    model_id = "claude-sonnet-4-6"

    # 1. Check if model is in config
    print(f"\nChecking configuration for {model_id}...")
    model_config = config_manager.get_model_pricing("anthropic", model_id)
    if model_config:
        print(f"✅ Configuration found: {model_config.get('name')} - {model_config.get('description')}")
        openrouter_id = None
        for server in model_config.get("servers", []):
            if server.get("id") == "openrouter":
                openrouter_id = server.get("model_id")
        print(f"   Configured OpenRouter ID: {openrouter_id}")
    else:
        print(f"❌ Configuration NOT found for {model_id}")
        return 1

    base_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, please respond with exactly: 'Sonnet 4.6 is online.'"}
    ]

    # 2. Test Anthropic Direct — non-streaming
    print(f"\nTesting Anthropic Direct (non-streaming) for {model_id}...")
    try:
        response = await invoke_anthropic_chat_completions(
            task_id="test_sonnet46_anthropic",
            model_id=model_id,
            messages=base_messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=20,
            stream=False
        )

        if response.success:
            print(f"✅ Anthropic Direct Success! Response: {response.direct_message_content}")
            if response.usage:
                print(f"   Usage: {response.usage.total_tokens} tokens")
        else:
            print(f"❌ Anthropic Direct Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during Anthropic Direct test: {e}")

    # 3. Test Streaming via Anthropic Direct
    print(f"\nTesting Anthropic Direct (streaming) for {model_id}...")
    try:
        stream_iter = await invoke_anthropic_chat_completions(
            task_id="test_sonnet46_stream",
            model_id=model_id,
            messages=[{"role": "user", "content": "Count from 1 to 5."}],
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=50,
            stream=True
        )

        print("   Stream output: ", end="", flush=True)
        full_text = ""
        async for chunk in stream_iter:
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                full_text += chunk
        print(f"\n✅ Streaming completed ({len(full_text)} chars).")
    except Exception as e:
        print(f"\n❌ Error during streaming test: {e}")

    # 4. Test Tool Use via Anthropic Direct
    print(f"\nTesting Tool Use (Anthropic Direct) for {model_id}...")
    test_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Get the current time in a specific timezone",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timezone": {
                            "type": "string",
                            "description": "The timezone, e.g. UTC, EST, etc."
                        }
                    },
                    "required": ["timezone"]
                }
            }
        }
    ]

    try:
        response = await invoke_anthropic_chat_completions(
            task_id="test_sonnet46_tools",
            model_id=model_id,
            messages=[{"role": "user", "content": "What time is it in UTC?"}],
            secrets_manager=secrets_manager,
            tools=test_tools,
            tool_choice="auto",
            stream=False
        )

        if response.success:
            if response.tool_calls_made:
                print(f"✅ Tool Use Success! Model called tool: {response.tool_calls_made[0].function_name}")
                print(f"   Arguments: {response.tool_calls_made[0].function_arguments_parsed}")
            else:
                print(f"⚠️  Success but no tool call made. Content: {response.direct_message_content}")
        else:
            print(f"❌ Tool Use Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during tool use test: {e}")

    # 5. Test OpenRouter path directly
    print(f"\nTesting OpenRouter path for {model_id}...")
    try:
        # Use the openrouter model_id from provider config (dot notation for OpenRouter)
        openrouter_model_id = "anthropic/claude-sonnet-4.6"
        response = await invoke_openrouter_chat_completions(
            task_id="test_sonnet46_openrouter",
            model_id=openrouter_model_id,
            messages=base_messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=20,
            stream=False
        )

        if response.success:
            print(f"✅ OpenRouter Success! Response: {response.direct_message_content}")
            if response.usage:
                print(f"   Usage: {response.usage.total_tokens} tokens")
        else:
            print(f"❌ OpenRouter Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during OpenRouter test: {e}")

    print("\n" + "="*80)
    print("TESTS COMPLETED")
    print("="*80 + "\n")
    return 0


if __name__ == "__main__":
    # Ensure backend modules are importable when running inside Docker (/app)
    sys.path.append("/app")
    asyncio.run(test_sonnet_4_6())
