#!/usr/bin/env python3
# backend/scripts/test_deepseek_v3_2.py
#
# Integration test script for DeepSeek V3.2 via Google Vertex AI (primary) and OpenRouter (fallback).
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

async def test_deepseek_v3_2():
    print("\n" + "="*80)
    print("DEEPSEEK V3.2 INTEGRATION TESTS")
    print("="*80 + "\n")

    # Import required modules
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.apps.ai.llm_providers.google_client import invoke_google_chat_completions
    from backend.apps.ai.llm_providers.openai_openrouter import invoke_openrouter_chat_completions
    from backend.core.api.app.utils.config_manager import config_manager

    # Initialize SecretsManager
    print("Initializing SecretsManager and Vault connection...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("SecretsManager initialized.")
    except Exception as e:
        print(f"Failed to initialize SecretsManager: {e}")
        return 1

    model_id = "deepseek-v3.2"
    vertex_model_id = "deepseek-ai/deepseek-v3.2-maas"  # Google Vertex AI MaaS model ID (publisher/model format)
    openrouter_model_id = "deepseek/deepseek-v3.2"  # OpenRouter model ID
    
    # 1. Check if model is in config
    print(f"\nChecking configuration for {model_id}...")
    model_config = config_manager.get_model_pricing("deepseek", model_id)
    if model_config:
        print(f"Configuration found: {model_config.get('name')} - {model_config.get('description', '')[:80]}...")
        print(f"   Features: {model_config.get('features')}")
        print(f"   Default server: {model_config.get('default_server')}")
        servers = model_config.get('servers', [])
        print(f"   Available servers: {[s.get('id') for s in servers]}")
    else:
        print(f"Configuration NOT found for {model_id}")
        print("   This means the config_manager hasn't loaded the new provider file yet.")
        print("   The provider YAML file was created, so we'll proceed with direct tests.")

    # 2. Test Basic Completion via Google Vertex AI (Non-streaming)
    print("\n" + "-"*60)
    print("TEST 1: Basic Completion via Google Vertex AI (Non-streaming)")
    print("-"*60)
    print(f"Using model_id: {vertex_model_id}")
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello! Please introduce yourself briefly. What model are you?"}
    ]
    
    try:
        response = await invoke_google_chat_completions(
            task_id="test_deepseek_v3_2_vertex_basic",
            model_id=vertex_model_id,
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0.7,
            max_tokens=150,
            stream=False
        )
        
        if response.success:
            print(f"Success! Response: {response.direct_message_content}")
            if response.usage:
                print(f"   Usage: {response.usage.total_token_count} tokens")
        else:
            print(f"Failed: {response.error_message}")
    except Exception as e:
        print(f"Error during Vertex AI basic completion: {e}")
        logger.exception("Vertex AI basic completion error")

    # 3. Test Streaming via Google Vertex AI
    print("\n" + "-"*60)
    print("TEST 2: Streaming via Google Vertex AI")
    print("-"*60)
    print(f"Using model_id: {vertex_model_id}")
    try:
        stream_iter = await invoke_google_chat_completions(
            task_id="test_deepseek_v3_2_vertex_stream",
            model_id=vertex_model_id,
            messages=[{"role": "user", "content": "Count from 1 to 5, one number per line."}],
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
        print("\nStreaming completed.")
    except Exception as e:
        print(f"\nError during Vertex AI streaming: {e}")
        logger.exception("Vertex AI streaming error")

    # 4. Test Tool Use via Google Vertex AI
    print("\n" + "-"*60)
    print("TEST 3: Tool Use via Google Vertex AI")
    print("-"*60)
    print(f"Using model_id: {vertex_model_id}")
    test_tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Get the current weather in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA"
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                            "description": "The temperature unit to use"
                        }
                    },
                    "required": ["location"]
                }
            }
        }
    ]
    
    try:
        response = await invoke_google_chat_completions(
            task_id="test_deepseek_v3_2_vertex_tools",
            model_id=vertex_model_id,
            messages=[{"role": "user", "content": "What's the weather like in Paris, France?"}],
            secrets_manager=secrets_manager,
            tools=test_tools,
            tool_choice="auto",
            stream=False
        )
        
        if response.success:
            if response.tool_calls_made:
                print(f"Success! Model called tool: {response.tool_calls_made[0].function_name}")
                print(f"   Arguments: {response.tool_calls_made[0].function_arguments_parsed}")
            else:
                print(f"Success but no tool call made. Content: {response.direct_message_content}")
        else:
            print(f"Failed: {response.error_message}")
    except Exception as e:
        print(f"Error during Vertex AI tool use test: {e}")
        logger.exception("Vertex AI tool use error")

    # 5. Test OpenRouter Fallback
    print("\n" + "-"*60)
    print("TEST 4: Basic Completion via OpenRouter (Fallback)")
    print("-"*60)
    print(f"Using model_id: {openrouter_model_id}")
    try:
        response = await invoke_openrouter_chat_completions(
            task_id="test_deepseek_v3_2_openrouter",
            model_id=openrouter_model_id,
            messages=[{"role": "user", "content": "Hello via OpenRouter! Please introduce yourself briefly."}],
            secrets_manager=secrets_manager,
            temperature=0.7,
            max_tokens=150,
            stream=False
        )
        
        if response.success:
            print(f"OpenRouter Success! Response: {response.direct_message_content}")
            if response.usage:
                print(f"   Usage: {response.usage.total_tokens} tokens")
        else:
            print(f"OpenRouter Failed: {response.error_message}")
    except Exception as e:
        print(f"Error during OpenRouter fallback test: {e}")
        logger.exception("OpenRouter fallback error")

    # 6. Test OpenRouter Streaming
    print("\n" + "-"*60)
    print("TEST 5: Streaming via OpenRouter")
    print("-"*60)
    print(f"Using model_id: {openrouter_model_id}")
    try:
        stream_iter = await invoke_openrouter_chat_completions(
            task_id="test_deepseek_v3_2_openrouter_stream",
            model_id=openrouter_model_id,
            messages=[{"role": "user", "content": "Count from 1 to 3."}],
            secrets_manager=secrets_manager,
            temperature=0.7,
            max_tokens=50,
            stream=True
        )
        
        print("   Stream output: ", end="", flush=True)
        full_text = ""
        async for chunk in stream_iter:
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
                full_text += chunk
        print("\nOpenRouter streaming completed.")
    except Exception as e:
        print(f"\nError during OpenRouter streaming: {e}")
        logger.exception("OpenRouter streaming error")

    print("\n" + "="*80)
    print("TESTS COMPLETED")
    print("="*80 + "\n")
    return 0

if __name__ == "__main__":
    # Ensure we can find the backend modules if running from script
    # The root of the project should be in the sys.path
    # In docker it's /app
    sys.path.append("/app")
    asyncio.run(test_deepseek_v3_2())
