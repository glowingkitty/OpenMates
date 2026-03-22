#!/usr/bin/env python3
# backend/scripts/test_groq_function_calling.py
#
# Integration test script for function calling via Groq API.
# This script tests function calling with three models:
# 1. openai/gpt-oss-20b
# 2. openai/gpt-oss-120b
# 3. openai/gpt-oss-safeguard-20b
#
# Run via docker exec:
#   docker compose exec api python /app/backend/scripts/test_groq_function_calling.py
#
# Or from the project root:
#   cd backend/core && docker compose exec api python /app/backend/scripts/test_groq_function_calling.py

import asyncio
import sys
import logging
from typing import List, Dict, Any, Optional

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy logs from other modules
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def run_integration_tests():
    """
    Run integration tests for function calling via Groq API.
    
    Tests function calling with three models:
    1. openai/gpt-oss-20b
    2. openai/gpt-oss-120b
    3. openai/gpt-oss-safeguard-20b
    
    Test scenarios:
    1. Required function call (tool_choice="required")
    2. Auto function call (tool_choice="auto")
    3. Multiple tools (model chooses which one)
    """
    # Import after setting up path
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.apps.ai.llm_providers.groq_client import invoke_groq_chat_completions
    
    print("\n" + "="*80)
    print("GROQ FUNCTION CALLING INTEGRATION TESTS (Real API Calls)")
    print("="*80 + "\n")
    
    # Initialize services
    print("Initializing SecretsManager...")
    secrets_manager = SecretsManager()
    
    # Initialize SecretsManager (connects to Vault and loads token)
    print("Connecting to Vault...")
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized successfully (connected to Vault)")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        print("\nHINT: Make sure you're running this inside the Docker container where Vault is accessible.")
        print("Run with: cd backend/core && docker compose exec api python /app/backend/scripts/test_groq_function_calling.py")
        return 1
    
    # Define models to test
    models_to_test = [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-safeguard-20b",
    ]
    
    # Define test tools (simple functions for testing)
    test_tools = [
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "Performs basic arithmetic calculations. Use this when the user asks you to calculate something.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["add", "subtract", "multiply", "divide"],
                            "description": "The arithmetic operation to perform"
                        },
                        "a": {
                            "type": "number",
                            "description": "The first number"
                        },
                        "b": {
                            "type": "number",
                            "description": "The second number"
                        }
                    },
                    "required": ["operation", "a", "b"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Gets the current weather for a given location. Use this when the user asks about weather.",
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
    
    # Test cases: (name, messages, tools, tool_choice, expected_function_name)
    test_cases = [
        # Test 1: Required function call with single tool (should always call calculate)
        (
            "Required: Single tool (calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant that performs calculations."},
                {"role": "user", "content": "What is 15 plus 27?"}
            ],
            [test_tools[0]],  # Only calculate tool
            "required",
            "calculate"
        ),
        # Test 2: Auto function call with single tool (should call calculate)
        (
            "Auto: Single tool (calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant that performs calculations."},
                {"role": "user", "content": "Can you multiply 8 by 9 for me?"}
            ],
            [test_tools[0]],  # Only calculate tool
            "auto",
            "calculate"
        ),
        # Test 3: Auto function call with multiple tools (should choose calculate)
        (
            "Auto: Multiple tools (choose calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant with access to calculators and weather APIs."},
                {"role": "user", "content": "What's 42 divided by 7?"}
            ],
            test_tools,  # Both tools available
            "auto",
            "calculate"
        ),
        # Test 4: Auto function call with multiple tools (should choose get_weather)
        (
            "Auto: Multiple tools (choose get_weather)",
            [
                {"role": "system", "content": "You are a helpful assistant with access to calculators and weather APIs."},
                {"role": "user", "content": "What's the weather like in New York?"}
            ],
            test_tools,  # Both tools available
            "auto",
            "get_weather"
        ),
        # Test 5: Required function call with multiple tools (should call first tool)
        (
            "Required: Multiple tools (calculate should be called)",
            [
                {"role": "system", "content": "You are a helpful assistant with access to calculators and weather APIs."},
                {"role": "user", "content": "Subtract 100 from 250"}
            ],
            test_tools,  # Both tools available
            "required",
            "calculate"  # With "required", it should call the first tool when multiple are available
        ),
    ]
    
    # Track results
    results = {
        "passed": [],
        "failed": [],
        "errors": []
    }
    
    # Test each model
    for model_id in models_to_test:
        print("\n" + "="*80)
        print(f"TESTING MODEL: {model_id}")
        print("="*80)
        
        for test_name, messages, tools, tool_choice, expected_function_name in test_cases:
            full_test_name = f"{model_id} - {test_name}"
            print(f"\n{'─'*60}")
            print(f"TEST: {full_test_name}")
            print(f"{'─'*60}")
            print(f"Messages: {messages[-1]['content'][:80]}{'...' if len(messages[-1]['content']) > 80 else ''}")
            print(f"Tools: {[tool['function']['name'] for tool in tools]}")
            print(f"Tool choice: {tool_choice}")
            print(f"Expected function: {expected_function_name}")
            
            try:
                # Call the actual function calling API
                task_id = f"test_{model_id.replace('/', '_')}_{test_name.replace(' ', '_').replace(':', '').replace('(', '').replace(')', '')}"
                
                response = await invoke_groq_chat_completions(
                    task_id=task_id,
                    model_id=model_id,
                    messages=messages,
                    secrets_manager=secrets_manager,
                    temperature=0.7,
                    max_tokens=500,
                    tools=tools,
                    tool_choice=tool_choice,
                    stream=False
                )
                
                # Check if request was successful
                if not response.success:
                    print(f"❌ FAIL - API call failed: {response.error_message}")
                    results["failed"].append((full_test_name, f"API call failed: {response.error_message}"))
                    continue
                
                # Check if tool calls were made
                if not response.tool_calls_made or len(response.tool_calls_made) == 0:
                    print("❌ FAIL - No tool calls were made")
                    print(f"Response content: {response.direct_message_content}")
                    results["failed"].append((full_test_name, "No tool calls were made"))
                    continue
                
                # Check if the correct function was called
                called_function_name = response.tool_calls_made[0].function_name
                print(f"✅ Called function: {called_function_name}")
                print(f"Function arguments: {response.tool_calls_made[0].function_arguments_parsed}")
                
                # Validate function arguments were parsed correctly
                if response.tool_calls_made[0].parsing_error:
                    print(f"⚠️  WARNING - JSON parsing error: {response.tool_calls_made[0].parsing_error}")
                
                # Check if correct function was called (for required, it should match or be the first tool)
                if tool_choice == "required" and len(tools) > 1:
                    # With multiple tools and "required", it should call one of them
                    available_functions = [tool["function"]["name"] for tool in tools]
                    if called_function_name not in available_functions:
                        print(f"❌ FAIL - Called function '{called_function_name}' not in available tools: {available_functions}")
                        results["failed"].append((full_test_name, f"Called wrong function: {called_function_name}"))
                        continue
                elif called_function_name != expected_function_name:
                    print(f"❌ FAIL - Expected '{expected_function_name}' but got '{called_function_name}'")
                    results["failed"].append((full_test_name, f"Wrong function called: {called_function_name}"))
                    continue
                
                # Validate arguments based on function called
                args = response.tool_calls_made[0].function_arguments_parsed or {}
                
                if called_function_name == "calculate":
                    required_params = ["operation", "a", "b"]
                    missing_params = [p for p in required_params if p not in args]
                    if missing_params:
                        print(f"❌ FAIL - Missing required parameters: {missing_params}")
                        results["failed"].append((full_test_name, f"Missing parameters: {missing_params}"))
                        continue
                    
                    # Check operation is valid
                    if args.get("operation") not in ["add", "subtract", "multiply", "divide"]:
                        print(f"❌ FAIL - Invalid operation: {args.get('operation')}")
                        results["failed"].append((full_test_name, f"Invalid operation: {args.get('operation')}"))
                        continue
                    
                    # Check numbers are provided
                    if not isinstance(args.get("a"), (int, float)) or not isinstance(args.get("b"), (int, float)):
                        print(f"❌ FAIL - Invalid number parameters: a={args.get('a')}, b={args.get('b')}")
                        results["failed"].append((full_test_name, "Invalid number parameters"))
                        continue
                
                elif called_function_name == "get_weather":
                    if "location" not in args:
                        print(f"❌ FAIL - Missing required parameter: location")
                        results["failed"].append((full_test_name, "Missing location parameter"))
                        continue
                    
                    if not isinstance(args.get("location"), str) or len(args.get("location", "").strip()) == 0:
                        print(f"❌ FAIL - Invalid location parameter: {args.get('location')}")
                        results["failed"].append((full_test_name, "Invalid location parameter"))
                        continue
                
                # Print usage if available
                if response.usage:
                    print(f"Usage: {response.usage.input_tokens} input tokens, {response.usage.output_tokens} output tokens, {response.usage.total_tokens} total")
                
                print("✅ PASS - Function calling worked correctly")
                results["passed"].append(full_test_name)
                
            except Exception as e:
                print(f"❌ ERROR - {type(e).__name__}: {e}")
                results["errors"].append((full_test_name, str(e)))
                logger.exception(f"Error in test '{full_test_name}'")
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    total = len(models_to_test) * len(test_cases)
    passed = len(results["passed"])
    failed = len(results["failed"])
    errors = len(results["errors"])
    
    print(f"\nTotal: {total} tests")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"💥 Errors: {errors}")
    
    if results["failed"]:
        print("\nFailed tests:")
        for name, reason in results["failed"]:
            print(f"  - {name}: {reason}")
    
    if results["errors"]:
        print("\nError tests:")
        for name, error in results["errors"]:
            print(f"  - {name}: {error}")
    
    print("\n" + "="*80)
    
    # Return exit code
    if failed > 0 or errors > 0:
        print("❌ SOME TESTS FAILED")
        return 1
    else:
        print("✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_integration_tests())
    sys.exit(exit_code)
