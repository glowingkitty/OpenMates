#!/usr/bin/env python3
# backend/scripts/test_anthropic_opus4_5.py
#
# Integration test script for Claude Opus 4.5 via Anthropic API and OpenRouter.
# This script tests basic completion for both providers.

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

async def test_opus4_5():
    print("\n" + "="*80)
    print("CLAUDE OPUS 4.5 INTEGRATION TESTS (Anthropic & OpenRouter)")
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

    model_id = "claude-opus-4-5-20251101"
    
    # 1. Check if model is in config
    print(f"\nChecking configuration for {model_id}...")
    model_config = config_manager.get_model_pricing("anthropic", model_id)
    if model_config:
        print(f"✅ Configuration found: {model_config.get('name')}")
        openrouter_id = None
        for server in model_config.get("servers", []):
            if server.get("id") == "openrouter":
                openrouter_id = server.get("model_id")
        print(f"   Configured OpenRouter ID: {openrouter_id}")
    else:
        print(f"❌ Configuration NOT found for {model_id}")
        return 1

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, please respond with exactly: 'Opus 4.5 is online.'"}
    ]

    # 2. Test Anthropic (Direct)
    print(f"\nTesting Anthropic Direct for {model_id}...")
    try:
        response = await invoke_anthropic_chat_completions(
            task_id="test_opus4_5_anthropic",
            model_id=model_id,
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=20,
            stream=False
        )
        
        if response.success:
            print(f"✅ Anthropic Direct Success! Response: {response.direct_message_content}")
        else:
            print(f"❌ Anthropic Direct Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during Anthropic Direct test: {e}")

    # 3. Test OpenRouter with configured ID
    print(f"\nTesting OpenRouter with configured ID (resolving through provider config)...")
    try:
        # We call the wrapper which will resolve the model_id
        # We pass "anthropic/claude-opus-4-5-20251101" as model_id to trigger resolution
        response = await invoke_openrouter_chat_completions(
            task_id="test_opus4_5_openrouter_config",
            model_id=f"anthropic/{model_id}",
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0,
            max_tokens=20,
            stream=False
        )
        
        if response.success:
            print(f"✅ OpenRouter (Config ID) Success! Response: {response.direct_message_content}")
        else:
            print(f"❌ OpenRouter (Config ID) Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during OpenRouter (Config ID) test: {e}")

    print("\n" + "="*80)
    print("TESTS COMPLETED")
    print("="*80 + "\n")
    return 0

if __name__ == "__main__":
    sys.path.append("/app")
    asyncio.run(test_opus4_5())
