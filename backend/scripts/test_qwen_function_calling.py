#!/usr/bin/env python3
# backend/scripts/test_qwen_function_calling.py
#
# Integration test script for Qwen3 function calling across Cerebras and OpenRouter.
# This script tests function calling in both streaming and non-streaming modes
# to validate the fix for the OpenRouter streaming tool call bug.
#
# Run via docker exec:
#   docker exec api python /app/backend/scripts/test_qwen_function_calling.py
#
# Or to test only OpenRouter (simulating Cerebras unhealthy):
#   docker exec api python /app/backend/scripts/test_qwen_function_calling.py --openrouter-only

import asyncio
import sys
import logging
import argparse
from typing import List, Dict, Any

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# Test tools for function calling
TEST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web-search",
            "description": "Search the web for current information",
            "parameters": {
                "type": "object",
                "properties": {
                    "requests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query"
                                }
                            },
                            "required": ["query"]
                        },
                        "description": "List of search requests"
                    }
                },
                "required": ["requests"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Perform arithmetic calculations",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide"],
                        "description": "The arithmetic operation"
                    },
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["operation", "a", "b"]
            }
        }
    }
]


async def test_cerebras_non_streaming(secrets_manager, model_id: str) -> bool:
    """Test Cerebras non-streaming function calling."""
    from backend.apps.ai.llm_providers.cerebras_wrapper import invoke_cerebras_chat_completions
    
    print("\n" + "─"*60)
    print("TEST: Cerebras Non-Streaming Function Calling")
    print("─"*60)
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools provided when needed."},
        {"role": "user", "content": "What is 42 multiplied by 7?"}
    ]
    
    try:
        response = await invoke_cerebras_chat_completions(
            task_id="test_cerebras_non_stream",
            model_id=model_id,
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0.3,
            max_tokens=500,
            tools=[TEST_TOOLS[1]],  # calculate tool
            tool_choice="auto",
            stream=False
        )
        
        if not response.success:
            print(f"❌ FAIL - API call failed: {response.error_message}")
            return False
        
        if not response.tool_calls_made:
            print(f"❌ FAIL - No tool calls made. Content: {response.direct_message_content}")
            return False
        
        tc = response.tool_calls_made[0]
        print(f"✅ Tool called: {tc.function_name}")
        print(f"   Arguments: {tc.function_arguments_parsed}")
        print(f"   Tool call ID: {tc.tool_call_id}")
        
        if tc.function_name != "calculate":
            print(f"❌ FAIL - Wrong function called")
            return False
        
        print("✅ PASS - Cerebras non-streaming function calling works")
        return True
        
    except Exception as e:
        print(f"❌ ERROR - {type(e).__name__}: {e}")
        logger.exception("Error in Cerebras non-streaming test")
        return False


async def test_cerebras_streaming(secrets_manager, model_id: str) -> bool:
    """Test Cerebras streaming function calling."""
    from backend.apps.ai.llm_providers.cerebras_wrapper import invoke_cerebras_chat_completions
    from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
    
    print("\n" + "─"*60)
    print("TEST: Cerebras Streaming Function Calling")
    print("─"*60)
    
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools provided when needed."},
        {"role": "user", "content": "Search the web for the latest news about AI"}
    ]
    
    try:
        stream = await invoke_cerebras_chat_completions(
            task_id="test_cerebras_stream",
            model_id=model_id,
            messages=messages,
            secrets_manager=secrets_manager,
            temperature=0.3,
            max_tokens=500,
            tools=[TEST_TOOLS[0]],  # web-search tool
            tool_choice="auto",
            stream=True
        )
        
        tool_calls = []
        text_content = ""
        usage = None
        
        async for chunk in stream:
            if isinstance(chunk, str):
                text_content += chunk
                print(f"   Text chunk: {chunk[:50]}..." if len(chunk) > 50 else f"   Text chunk: {chunk}")
            elif isinstance(chunk, ParsedOpenAIToolCall):
                tool_calls.append(chunk)
                print(f"   Tool call received: {chunk.function_name}")
            elif isinstance(chunk, OpenAIUsageMetadata):
                usage = chunk
        
        if not tool_calls:
            print(f"❌ FAIL - No tool calls received in stream. Text content: {text_content}")
            return False
        
        tc = tool_calls[0]
        print(f"✅ Tool called: {tc.function_name}")
        print(f"   Arguments: {tc.function_arguments_parsed}")
        print(f"   Tool call ID: {tc.tool_call_id}")
        
        if tc.function_name != "web-search":
            print(f"❌ FAIL - Wrong function called")
            return False
        
        print("✅ PASS - Cerebras streaming function calling works")
        return True
        
    except Exception as e:
        print(f"❌ ERROR - {type(e).__name__}: {e}")
        logger.exception("Error in Cerebras streaming test")
        return False


async def test_openrouter_non_streaming(secrets_manager) -> bool:
    """Test OpenRouter non-streaming function calling with Qwen."""
    from backend.apps.ai.llm_providers.openrouter_client import invoke_openrouter_api
    
    print("\n" + "─"*60)
    print("TEST: OpenRouter Non-Streaming Function Calling (Qwen)")
    print("─"*60)
    
    # Get API key from Vault
    api_key = await secrets_manager.get_secret("kv/data/providers/openrouter", "api_key")
    if not api_key:
        print("❌ FAIL - Could not retrieve OpenRouter API key from Vault")
        return False
    
    model_id = "qwen/qwen3-235b-a22b-2507"
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools provided when needed."},
        {"role": "user", "content": "Calculate 99 divided by 11"}
    ]
    
    try:
        response = await invoke_openrouter_api(
            task_id="test_openrouter_non_stream",
            model_id=model_id,
            messages=messages,
            api_key=api_key,
            temperature=0.3,
            max_tokens=500,
            tools=[TEST_TOOLS[1]],  # calculate tool
            tool_choice="auto",
            stream=False
        )
        
        if not response.success:
            print(f"❌ FAIL - API call failed: {response.error_message}")
            return False
        
        if not response.tool_calls_made:
            print(f"❌ FAIL - No tool calls made. Content: {response.direct_message_content}")
            return False
        
        tc = response.tool_calls_made[0]
        print(f"✅ Tool called: {tc.function_name}")
        print(f"   Arguments: {tc.function_arguments_parsed}")
        print(f"   Tool call ID: {tc.tool_call_id}")
        
        if tc.function_name != "calculate":
            print(f"❌ FAIL - Wrong function called")
            return False
        
        print("✅ PASS - OpenRouter non-streaming function calling works")
        return True
        
    except Exception as e:
        print(f"❌ ERROR - {type(e).__name__}: {e}")
        logger.exception("Error in OpenRouter non-streaming test")
        return False


async def test_openrouter_streaming(secrets_manager) -> bool:
    """Test OpenRouter streaming function calling with Qwen.
    
    THIS IS THE CRITICAL TEST - validates the fix for the streaming tool call bug.
    """
    from backend.apps.ai.llm_providers.openrouter_client import invoke_openrouter_api
    from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
    
    print("\n" + "─"*60)
    print("TEST: OpenRouter Streaming Function Calling (Qwen)")
    print("      ⚠️  THIS IS THE CRITICAL TEST FOR THE BUG FIX")
    print("─"*60)
    
    # Get API key from Vault
    api_key = await secrets_manager.get_secret("kv/data/providers/openrouter", "api_key")
    if not api_key:
        print("❌ FAIL - Could not retrieve OpenRouter API key from Vault")
        return False
    
    model_id = "qwen/qwen3-235b-a22b-2507"
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools provided when needed."},
        {"role": "user", "content": "Search the web for information about password managers"}
    ]
    
    try:
        stream = await invoke_openrouter_api(
            task_id="test_openrouter_stream",
            model_id=model_id,
            messages=messages,
            api_key=api_key,
            temperature=0.3,
            max_tokens=500,
            tools=[TEST_TOOLS[0]],  # web-search tool
            tool_choice="auto",
            stream=True
        )
        
        tool_calls = []
        text_content = ""
        usage = None
        chunk_count = 0
        
        async for chunk in stream:
            chunk_count += 1
            if isinstance(chunk, str):
                text_content += chunk
                if chunk.strip():  # Only log non-empty chunks
                    print(f"   Text chunk: {chunk[:80]}..." if len(chunk) > 80 else f"   Text chunk: {chunk}")
            elif isinstance(chunk, ParsedOpenAIToolCall):
                tool_calls.append(chunk)
                print(f"   ✅ Tool call received: {chunk.function_name}")
                print(f"      Arguments: {chunk.function_arguments_raw[:100]}...")
            elif isinstance(chunk, OpenAIUsageMetadata):
                usage = chunk
                print(f"   Usage: {usage.input_tokens} in, {usage.output_tokens} out")
        
        print(f"\n   Total chunks processed: {chunk_count}")
        
        if not tool_calls:
            print(f"❌ FAIL - No tool calls received in stream!")
            print(f"   Text content received: {text_content[:200] if text_content else '(none)'}")
            print("   This indicates the streaming tool call bug is NOT fixed!")
            return False
        
        tc = tool_calls[0]
        print(f"\n✅ Tool called: {tc.function_name}")
        print(f"   Arguments: {tc.function_arguments_parsed}")
        print(f"   Tool call ID: {tc.tool_call_id}")
        
        if tc.function_name != "web-search":
            print(f"❌ FAIL - Wrong function called (expected web-search)")
            return False
        
        # Validate the arguments structure
        args = tc.function_arguments_parsed
        if not args or "requests" not in args:
            print(f"❌ FAIL - Invalid arguments structure: {args}")
            return False
        
        print("✅ PASS - OpenRouter streaming function calling works!")
        print("   The bug fix is validated - tool calls are now properly yielded.")
        return True
        
    except Exception as e:
        print(f"❌ ERROR - {type(e).__name__}: {e}")
        logger.exception("Error in OpenRouter streaming test")
        return False


async def test_fallback_mechanism(secrets_manager, model_id: str) -> bool:
    """Test the automatic fallback from Cerebras to OpenRouter.
    
    This test simulates Cerebras being unavailable by calling OpenRouter directly
    with the Qwen model, which is the fallback behavior.
    """
    from backend.apps.ai.llm_providers.openrouter_client import invoke_openrouter_api
    from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
    
    print("\n" + "─"*60)
    print("TEST: Fallback Simulation (Direct OpenRouter Call)")
    print("      (Simulates Cerebras being unavailable)")
    print("─"*60)
    
    # Get API key from Vault
    api_key = await secrets_manager.get_secret("kv/data/providers/openrouter", "api_key")
    if not api_key:
        print("❌ FAIL - Could not retrieve OpenRouter API key from Vault")
        return False
    
    model_id = "qwen/qwen3-235b-a22b-2507"
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use the tools provided when needed."},
        {"role": "user", "content": "What is 25 plus 75?"}
    ]
    
    try:
        # Test streaming with the calculate tool (same as production fallback)
        stream = await invoke_openrouter_api(
            task_id="test_fallback_sim",
            model_id=model_id,
            messages=messages,
            api_key=api_key,
            temperature=0.3,
            max_tokens=500,
            tools=[TEST_TOOLS[1]],  # calculate tool
            tool_choice="auto",
            stream=True
        )
        
        tool_calls = []
        text_content = ""
        
        async for chunk in stream:
            if isinstance(chunk, str):
                text_content += chunk
            elif isinstance(chunk, ParsedOpenAIToolCall):
                tool_calls.append(chunk)
                print(f"   Tool call received: {chunk.function_name}")
            elif isinstance(chunk, OpenAIUsageMetadata):
                print(f"   Usage: {chunk.input_tokens} in, {chunk.output_tokens} out")
        
        if not tool_calls:
            print(f"❌ FAIL - No tool calls received. Text: {text_content}")
            return False
        
        tc = tool_calls[0]
        print(f"✅ Tool called: {tc.function_name}")
        print(f"   Arguments: {tc.function_arguments_parsed}")
        
        # Validate the function call
        if tc.function_name != "calculate":
            print(f"❌ FAIL - Wrong function called (expected calculate)")
            return False
        
        args = tc.function_arguments_parsed
        if args.get("operation") != "add" or args.get("a") != 25 or args.get("b") != 75:
            print(f"⚠️  Arguments not exactly as expected but function was called correctly")
        
        print("✅ PASS - Fallback simulation works correctly")
        return True
        
    except Exception as e:
        print(f"❌ ERROR - {type(e).__name__}: {e}")
        logger.exception("Error in fallback test")
        return False


async def run_tests(openrouter_only: bool = False):
    """Run all function calling tests."""
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    print("\n" + "="*80)
    print("QWEN3 FUNCTION CALLING TESTS")
    print("Testing Cerebras (primary) and OpenRouter (fallback)")
    print("="*80)
    
    # Initialize SecretsManager
    print("\nInitializing SecretsManager...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized (connected to Vault)")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        return 1
    
    # Cerebras model ID (without provider prefix for direct calls)
    cerebras_model_id = "qwen-3-235b-a22b-instruct-2507"
    
    results = {
        "passed": [],
        "failed": [],
        "skipped": []
    }
    
    # Test Cerebras (unless openrouter_only)
    if not openrouter_only:
        # Test 1: Cerebras non-streaming
        if await test_cerebras_non_streaming(secrets_manager, cerebras_model_id):
            results["passed"].append("Cerebras Non-Streaming")
        else:
            results["failed"].append("Cerebras Non-Streaming")
        
        # Test 2: Cerebras streaming
        if await test_cerebras_streaming(secrets_manager, cerebras_model_id):
            results["passed"].append("Cerebras Streaming")
        else:
            results["failed"].append("Cerebras Streaming")
    else:
        results["skipped"].append("Cerebras Non-Streaming")
        results["skipped"].append("Cerebras Streaming")
        print("\n⚠️  Skipping Cerebras tests (--openrouter-only flag)")
    
    # Test 3: OpenRouter non-streaming
    if await test_openrouter_non_streaming(secrets_manager):
        results["passed"].append("OpenRouter Non-Streaming")
    else:
        results["failed"].append("OpenRouter Non-Streaming")
    
    # Test 4: OpenRouter streaming (CRITICAL - validates the bug fix)
    if await test_openrouter_streaming(secrets_manager):
        results["passed"].append("OpenRouter Streaming (BUG FIX)")
    else:
        results["failed"].append("OpenRouter Streaming (BUG FIX)")
    
    # Test 5: Fallback mechanism (unless openrouter_only)
    if not openrouter_only:
        if await test_fallback_mechanism(secrets_manager, cerebras_model_id):
            results["passed"].append("Fallback Mechanism")
        else:
            results["failed"].append("Fallback Mechanism")
    else:
        results["skipped"].append("Fallback Mechanism")
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    total = len(results["passed"]) + len(results["failed"])
    print(f"\nTotal tests run: {total}")
    print(f"✅ Passed: {len(results['passed'])}")
    print(f"❌ Failed: {len(results['failed'])}")
    if results["skipped"]:
        print(f"⏭️  Skipped: {len(results['skipped'])}")
    
    if results["passed"]:
        print("\n✅ Passed tests:")
        for name in results["passed"]:
            print(f"   - {name}")
    
    if results["failed"]:
        print("\n❌ Failed tests:")
        for name in results["failed"]:
            print(f"   - {name}")
    
    if results["skipped"]:
        print("\n⏭️  Skipped tests:")
        for name in results["skipped"]:
            print(f"   - {name}")
    
    print("\n" + "="*80)
    
    if results["failed"]:
        print("❌ SOME TESTS FAILED")
        return 1
    else:
        print("✅ ALL TESTS PASSED")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Test Qwen3 function calling across Cerebras and OpenRouter"
    )
    parser.add_argument(
        "--openrouter-only",
        action="store_true",
        help="Only test OpenRouter (skip Cerebras tests)"
    )
    args = parser.parse_args()
    
    # Add app path for imports
    sys.path.insert(0, "/app")
    
    exit_code = asyncio.run(run_tests(openrouter_only=args.openrouter_only))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
