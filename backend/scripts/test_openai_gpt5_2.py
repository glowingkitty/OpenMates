#!/usr/bin/env python3
# backend/scripts/test_openai_gpt5_2.py
#
# Integration test script for GPT-5.2 via OpenAI API.
# This script tests basic completion, streaming, and tool use.

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

async def test_gpt5_2():
    print("\n" + "="*80)
    print("GPT-5.2 INTEGRATION TESTS")
    print("="*80 + "\n")

    # Import required modules
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.apps.ai.llm_providers.openai_client import invoke_openai_chat_completions
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

    model_id = "gpt-5.2"
    
    # 1. Check if model is in config
    print(f"\nChecking configuration for {model_id}...")
    model_config = config_manager.get_model_pricing("openai", model_id)
    if model_config:
        print(f"✅ Configuration found: {model_config.get('name')} - {model_config.get('description')}")
        print(f"   Features: {model_config.get('features')}")
    else:
        print(f"❌ Configuration NOT found for {model_id}")
        return 1

    # 2. Test Basic Completion (Non-streaming)
    print(f"\nTesting Basic Completion (Non-streaming) for {model_id}...")
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, who are you? Please respond with 'I am GPT-5.2' if you are that model."}
    ]
    
    try:
        response = await invoke_openai_chat_completions(
            task_id="test_gpt5_2_basic",
            model_id=model_id,
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0.7,
            max_tokens=100,
            stream=False
        )
        
        if response.success:
            print(f"✅ Success! Response: {response.direct_message_content}")
            if response.usage:
                print(f"   Usage: {response.usage.total_tokens} tokens")
        else:
            print(f"❌ Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during basic completion: {e}")

    # 3. Test Streaming
    print(f"\nTesting Streaming for {model_id}...")
    try:
        stream_iter = await invoke_openai_chat_completions(
            task_id="test_gpt5_2_stream",
            model_id=model_id,
            messages=[{"role": "user", "content": "Count from 1 to 5 slowly."}],
            secrets_manager=secrets_manager,
            temperature=0.7,
            max_tokens=100,
            stream=True
        )
        
        print("   Stream output: ", end="", flush=True)
        full_text = ""
        async for chunk in stream_iter:
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                full_text += chunk
        print("\n✅ Streaming completed.")
    except Exception as e:
        print(f"\n❌ Error during streaming: {e}")

    # 4. Test Tool Use
    print(f"\nTesting Tool Use for {model_id}...")
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
        response = await invoke_openai_chat_completions(
            task_id="test_gpt5_2_tools",
            model_id=model_id,
            messages=[{"role": "user", "content": "What time is it in UTC?"}],
            secrets_manager=secrets_manager,
            tools=test_tools,
            tool_choice="auto",
            stream=False
        )
        
        if response.success:
            if response.tool_calls_made:
                print(f"✅ Success! Model called tool: {response.tool_calls_made[0].function_name}")
                print(f"   Arguments: {response.tool_calls_made[0].function_arguments_parsed}")
            else:
                print(f"⚠️  Success but no tool call made. Content: {response.direct_message_content}")
        else:
            print(f"❌ Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during tool use test: {e}")

    # 5. Test OpenRouter Fallback
    print(f"\nTesting OpenRouter Fallback for {model_id}...")
    try:
        # We call the OpenRouter wrapper with the provider prefix to test resolution
        response = await invoke_openrouter_chat_completions(
            task_id="test_gpt5_2_openrouter",
            model_id=f"openai/{model_id}",
            messages=[{"role": "user", "content": "Hello via OpenRouter. Who are you?"}],
            secrets_manager=secrets_manager,
            temperature=0.7,
            max_tokens=100,
            stream=False
        )
        
        if response.success:
            print(f"✅ OpenRouter Success! Response: {response.direct_message_content}")
            if response.usage:
                print(f"   Usage: {response.usage.total_tokens} tokens")
        else:
            print(f"❌ OpenRouter Failed: {response.error_message}")
    except Exception as e:
        print(f"❌ Error during OpenRouter fallback test: {e}")

    # 6. Test Automatic Fallback (OpenAI Direct -> OpenRouter)
    print(f"\nTesting Automatic Fallback (OpenAI Direct -> OpenRouter) for {model_id}...")
    try:
        from unittest.mock import patch
        
        # We mock _invoke_openai_direct_api to fail, which should trigger automatic fallback in invoke_openai_chat_completions
        # since gpt-5.2 is configured with both openai and openrouter servers.
        from backend.apps.ai.llm_providers.openai_client import UnifiedOpenAIResponse
        
        async def mock_failed_direct_api(*args, **kwargs):
            print("      (Simulating OpenAI Direct API failure...)")
            return UnifiedOpenAIResponse(
                task_id=kwargs.get("task_id", "test_fallback"),
                model_id=kwargs.get("model_id", "gpt-5.2"),
                success=False,
                error_message="Simulated OpenAI Direct failure"
            )
            
        with patch("backend.apps.ai.llm_providers.openai_client._invoke_openai_direct_api", side_effect=mock_failed_direct_api):
            response = await invoke_openai_chat_completions(
                task_id="test_gpt5_2_auto_fallback",
                model_id=model_id,
                messages=[{"role": "user", "content": "Hello. This request should automatically fallback to OpenRouter."}],
                secrets_manager=secrets_manager,
                temperature=0.7,
                max_tokens=100,
                stream=False
            )
            
            if response.success:
                print(f"✅ Automatic Fallback Success! Response: {response.direct_message_content}")
                print("   (This confirms the client automatically tried OpenRouter when OpenAI Direct failed)")
            else:
                print(f"❌ Automatic Fallback Failed: {response.error_message}")
                
    except Exception as e:
        print(f"❌ Error during automatic fallback test: {e}")

    print("\n" + "="*80)
    print("TESTS COMPLETED")
    print("="*80 + "\n")
    return 0

if __name__ == "__main__":
    # Ensure we can find the backend modules if running from script
    # The root of the project should be in the sys.path
    # In docker it's /app
    sys.path.append("/app")
    asyncio.run(test_gpt5_2())
