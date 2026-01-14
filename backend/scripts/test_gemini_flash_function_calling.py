#!/usr/bin/env python3
# backend/scripts/test_gemini_flash_function_calling.py
#
# Integration test script for Gemini 3 Flash via Google AI Studio.
# This script tests both streaming and function calling capabilities.
#
# Run via docker exec:
#   docker compose exec api python /app/backend/scripts/test_gemini_flash_function_calling.py
#
# Or with specific tests:
#   docker compose exec api python /app/backend/scripts/test_gemini_flash_function_calling.py --streaming-only
#   docker compose exec api python /app/backend/scripts/test_gemini_flash_function_calling.py --function-calling-only

import asyncio
import sys
import logging
import argparse
from typing import List, Dict, Any, Optional, Union, AsyncIterator

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy logs from other modules
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)


async def run_streaming_tests(secrets_manager) -> Dict[str, List]:
    """
    Test streaming functionality with Gemini 3 Flash.
    
    Streaming is critical for main processor usage - if streaming doesn't work,
    the model cannot be used for real-time responses.
    """
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    print("\n" + "="*80)
    print("GEMINI 3 FLASH STREAMING TESTS")
    print("="*80 + "\n")
    
    results = {"passed": [], "failed": [], "errors": []}
    
    # Model to test - using the model_id as it appears in google.yml server config
    model_id = "gemini-3-flash-preview"
    
    # Test cases for streaming
    streaming_test_cases = [
        (
            "Basic streaming response",
            [
                {"role": "system", "content": "You are a helpful assistant. Keep responses concise."},
                {"role": "user", "content": "What is 2+2? Answer in one sentence."}
            ],
            None  # No tools
        ),
        (
            "Longer streaming response",
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Explain what Python is in 2-3 sentences."}
            ],
            None
        ),
        (
            "Multi-turn conversation streaming",
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is the capital of France?"},
                {"role": "assistant", "content": "The capital of France is Paris."},
                {"role": "user", "content": "What is its population?"}
            ],
            None
        ),
    ]
    
    for test_name, messages, tools in streaming_test_cases:
        print(f"\n{'─'*60}")
        print(f"TEST: {test_name}")
        print(f"{'─'*60}")
        print(f"Last message: {messages[-1]['content'][:80]}...")
        
        try:
            task_id = f"test_streaming_{test_name.replace(' ', '_').lower()}"
            
            # Call with stream=True
            stream_response = await invoke_google_ai_studio_chat_completions(
                task_id=task_id,
                model_id=model_id,
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0.7,
                max_tokens=200,
                tools=tools,
                tool_choice=None,
                stream=True
            )
            
            # Collect streamed content
            collected_text = ""
            chunk_count = 0
            usage_metadata = None
            
            # Check if we got an async iterator
            if not hasattr(stream_response, '__aiter__'):
                print(f"❌ FAIL - Expected async iterator but got: {type(stream_response)}")
                results["failed"].append((test_name, f"Not an async iterator: {type(stream_response)}"))
                continue
            
            async for chunk in stream_response:
                # Check what type of chunk we received
                if isinstance(chunk, str):
                    collected_text += chunk
                    chunk_count += 1
                    # Print first few chunks to show streaming is working
                    if chunk_count <= 3:
                        print(f"  Chunk {chunk_count}: {repr(chunk[:50])}...")
                else:
                    # Could be usage metadata or tool call
                    from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata, ParsedGoogleToolCall
                    if hasattr(chunk, 'prompt_token_count'):
                        usage_metadata = chunk
                        print(f"  Usage: {chunk.prompt_token_count} input, {chunk.candidates_token_count} output tokens")
                    else:
                        print(f"  Non-string chunk: {type(chunk)}")
            
            # Validate results
            if not collected_text:
                print(f"❌ FAIL - No text content received from stream")
                results["failed"].append((test_name, "No text content"))
                continue
            
            print(f"✅ Received {chunk_count} chunks, total {len(collected_text)} chars")
            print(f"  Response preview: {collected_text[:100]}...")
            
            if usage_metadata:
                print(f"  Tokens: {usage_metadata.prompt_token_count} input, {usage_metadata.candidates_token_count} output")
            
            results["passed"].append(test_name)
            
        except Exception as e:
            print(f"❌ ERROR - {type(e).__name__}: {e}")
            results["errors"].append((test_name, str(e)))
            logger.exception(f"Error in streaming test '{test_name}'")
    
    return results


async def run_function_calling_tests(secrets_manager) -> Dict[str, List]:
    """
    Test function calling with Gemini 3 Flash.
    
    Function calling (tool use) is required for the main processor to execute
    skills like web search, news, etc.
    """
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    print("\n" + "="*80)
    print("GEMINI 3 FLASH FUNCTION CALLING TESTS")
    print("="*80 + "\n")
    
    results = {"passed": [], "failed": [], "errors": []}
    
    model_id = "gemini-3-flash-preview"
    
    # Define test tools
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
                "name": "web_search",
                "description": "Search the web for information. Use this when the user asks about current events, facts, or needs to find information online.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of results to return (default: 5)"
                        }
                    },
                    "required": ["query"]
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
    
    # Test cases: (name, messages, tools, tool_choice, expected_function_name, stream)
    function_calling_test_cases = [
        # Non-streaming function calling tests
        (
            "Non-stream: Required single tool (calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant that performs calculations."},
                {"role": "user", "content": "What is 15 plus 27?"}
            ],
            [test_tools[0]],  # Only calculate tool
            "required",
            "calculate",
            False
        ),
        (
            "Non-stream: Auto single tool (calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Can you multiply 8 by 9 for me?"}
            ],
            [test_tools[0]],
            "auto",
            "calculate",
            False
        ),
        (
            "Non-stream: Auto multiple tools (choose web_search)",
            [
                {"role": "system", "content": "You are a helpful assistant with access to calculators, weather APIs, and web search."},
                {"role": "user", "content": "Search the web for the latest news about AI."}
            ],
            test_tools,
            "auto",
            "web_search",
            False
        ),
        (
            "Non-stream: Auto multiple tools (choose get_weather)",
            [
                {"role": "system", "content": "You are a helpful assistant with access to calculators, weather APIs, and web search."},
                {"role": "user", "content": "What's the weather like in New York?"}
            ],
            test_tools,
            "auto",
            "get_weather",
            False
        ),
        # Streaming function calling tests
        (
            "Stream: Required single tool (calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant that performs calculations."},
                {"role": "user", "content": "Divide 100 by 4"}
            ],
            [test_tools[0]],
            "required",
            "calculate",
            True
        ),
        (
            "Stream: Auto multiple tools (choose calculate)",
            [
                {"role": "system", "content": "You are a helpful assistant with access to calculators, weather APIs, and web search."},
                {"role": "user", "content": "What's 42 divided by 7?"}
            ],
            test_tools,
            "auto",
            "calculate",
            True
        ),
    ]
    
    for test_name, messages, tools, tool_choice, expected_function_name, stream in function_calling_test_cases:
        print(f"\n{'─'*60}")
        print(f"TEST: {test_name}")
        print(f"{'─'*60}")
        print(f"Message: {messages[-1]['content'][:80]}...")
        print(f"Tools: {[tool['function']['name'] for tool in tools]}")
        print(f"Tool choice: {tool_choice}, Stream: {stream}")
        print(f"Expected function: {expected_function_name}")
        
        try:
            task_id = f"test_fc_{test_name.replace(' ', '_').replace(':', '').replace('(', '').replace(')', '').lower()}"
            
            response = await invoke_google_ai_studio_chat_completions(
                task_id=task_id,
                model_id=model_id,
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0.7,
                max_tokens=500,
                tools=tools,
                tool_choice=tool_choice,
                stream=stream
            )
            
            if stream:
                # Handle streaming response
                tool_calls_received = []
                text_content = ""
                
                if not hasattr(response, '__aiter__'):
                    print(f"❌ FAIL - Expected async iterator but got: {type(response)}")
                    results["failed"].append((test_name, f"Not an async iterator: {type(response)}"))
                    continue
                
                async for chunk in response:
                    if isinstance(chunk, str):
                        text_content += chunk
                    else:
                        # Check if it's a tool call
                        from backend.apps.ai.llm_providers.google_client import ParsedGoogleToolCall, GoogleUsageMetadata
                        if hasattr(chunk, 'function_name'):
                            tool_calls_received.append(chunk)
                            print(f"  Tool call received: {chunk.function_name}")
                            print(f"  Arguments: {chunk.function_arguments_parsed}")
                        elif hasattr(chunk, 'prompt_token_count'):
                            print(f"  Usage: {chunk.prompt_token_count} input, {chunk.candidates_token_count} output tokens")
                
                if not tool_calls_received:
                    print(f"❌ FAIL - No tool calls received in stream")
                    if text_content:
                        print(f"  Text content instead: {text_content[:200]}...")
                    results["failed"].append((test_name, "No tool calls in stream"))
                    continue
                
                # Validate tool call
                called_function_name = tool_calls_received[0].function_name
                args = tool_calls_received[0].function_arguments_parsed or {}
                
            else:
                # Handle non-streaming response
                if not response.success:
                    print(f"❌ FAIL - API call failed: {response.error_message}")
                    results["failed"].append((test_name, f"API call failed: {response.error_message}"))
                    continue
                
                if not response.tool_calls_made or len(response.tool_calls_made) == 0:
                    print(f"❌ FAIL - No tool calls were made")
                    if response.direct_message_content:
                        print(f"  Response content: {response.direct_message_content[:200]}...")
                    results["failed"].append((test_name, "No tool calls were made"))
                    continue
                
                called_function_name = response.tool_calls_made[0].function_name
                args = response.tool_calls_made[0].function_arguments_parsed or {}
                
                if response.tool_calls_made[0].parsing_error:
                    print(f"⚠️  WARNING - JSON parsing error: {response.tool_calls_made[0].parsing_error}")
            
            # Validate the correct function was called
            print(f"✅ Called function: {called_function_name}")
            print(f"  Arguments: {args}")
            
            # For tool_choice="required" with multiple tools, accept any valid tool
            available_functions = [tool["function"]["name"] for tool in tools]
            
            if tool_choice == "required" and len(tools) > 1:
                if called_function_name not in available_functions:
                    print(f"❌ FAIL - Called function '{called_function_name}' not in available tools: {available_functions}")
                    results["failed"].append((test_name, f"Called wrong function: {called_function_name}"))
                    continue
            elif called_function_name != expected_function_name:
                # For auto mode, check if at least a valid function was called
                if called_function_name in available_functions:
                    print(f"⚠️  WARNING - Expected '{expected_function_name}' but got '{called_function_name}' (still valid)")
                else:
                    print(f"❌ FAIL - Expected '{expected_function_name}' but got '{called_function_name}'")
                    results["failed"].append((test_name, f"Wrong function called: {called_function_name}"))
                    continue
            
            # Validate arguments based on function called
            validation_passed = True
            if called_function_name == "calculate":
                required_params = ["operation", "a", "b"]
                missing_params = [p for p in required_params if p not in args]
                if missing_params:
                    print(f"❌ FAIL - Missing required parameters: {missing_params}")
                    results["failed"].append((test_name, f"Missing parameters: {missing_params}"))
                    validation_passed = False
                elif args.get("operation") not in ["add", "subtract", "multiply", "divide"]:
                    print(f"❌ FAIL - Invalid operation: {args.get('operation')}")
                    results["failed"].append((test_name, f"Invalid operation: {args.get('operation')}"))
                    validation_passed = False
                elif not isinstance(args.get("a"), (int, float)) or not isinstance(args.get("b"), (int, float)):
                    print(f"❌ FAIL - Invalid number parameters: a={args.get('a')}, b={args.get('b')}")
                    results["failed"].append((test_name, "Invalid number parameters"))
                    validation_passed = False
                    
            elif called_function_name == "web_search":
                if "query" not in args:
                    print(f"❌ FAIL - Missing required parameter: query")
                    results["failed"].append((test_name, "Missing query parameter"))
                    validation_passed = False
                elif not isinstance(args.get("query"), str) or len(args.get("query", "").strip()) == 0:
                    print(f"❌ FAIL - Invalid query parameter: {args.get('query')}")
                    results["failed"].append((test_name, "Invalid query parameter"))
                    validation_passed = False
                    
            elif called_function_name == "get_weather":
                if "location" not in args:
                    print(f"❌ FAIL - Missing required parameter: location")
                    results["failed"].append((test_name, "Missing location parameter"))
                    validation_passed = False
                elif not isinstance(args.get("location"), str) or len(args.get("location", "").strip()) == 0:
                    print(f"❌ FAIL - Invalid location parameter: {args.get('location')}")
                    results["failed"].append((test_name, "Invalid location parameter"))
                    validation_passed = False
            
            if validation_passed:
                print("✅ PASS - Function calling worked correctly")
                results["passed"].append(test_name)
            
        except Exception as e:
            print(f"❌ ERROR - {type(e).__name__}: {e}")
            results["errors"].append((test_name, str(e)))
            logger.exception(f"Error in function calling test '{test_name}'")
    
    return results


async def run_main_processor_simulation(secrets_manager) -> Dict[str, List]:
    """
    Simulate a main processor call using Gemini 3 Flash.
    
    This tests the model in a more realistic scenario with:
    - System prompt similar to what main_processor uses
    - Multiple tools available
    - Streaming response
    """
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    print("\n" + "="*80)
    print("MAIN PROCESSOR SIMULATION TEST")
    print("="*80 + "\n")
    
    results = {"passed": [], "failed": [], "errors": []}
    
    model_id = "gemini-3-flash-preview"
    
    # Simulate main processor system prompt (simplified)
    system_prompt = """You are a helpful AI assistant named Mates. Current date and time: 2026-01-14 10:00:00 UTC.

You have access to the following tools to help answer user questions:
- web_search: Search the web for current information
- calculate: Perform mathematical calculations

When the user asks a question that requires current information, use the web_search tool.
When the user asks for calculations, use the calculate tool.
Otherwise, respond directly with your knowledge.

Be helpful, accurate, and concise."""
    
    # Tools similar to what main processor provides
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current information about any topic.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "Perform mathematical calculations.",
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
    
    # Test scenarios
    test_cases = [
        # Direct response (no tool needed)
        (
            "Direct response (no tool)",
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "What is the capital of Japan?"}
            ],
            tools,
            "auto",
            None,  # No tool expected
            True   # stream
        ),
        # Tool use (web search)
        (
            "Web search tool use",
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Search for the latest news about AI developments today."}
            ],
            tools,
            "auto",
            "web_search",
            True
        ),
        # Follow-up conversation
        (
            "Follow-up conversation",
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "What is Python?"},
                {"role": "assistant", "content": "Python is a high-level, general-purpose programming language known for its readability and versatility. It's widely used in web development, data science, AI/ML, automation, and many other fields."},
                {"role": "user", "content": "What are its main features?"}
            ],
            tools,
            "auto",
            None,  # Direct response expected
            True
        ),
    ]
    
    for test_name, messages, test_tools, tool_choice, expected_tool, stream in test_cases:
        print(f"\n{'─'*60}")
        print(f"TEST: {test_name}")
        print(f"{'─'*60}")
        print(f"Last message: {messages[-1]['content'][:80]}...")
        print(f"Expected: {'Tool call: ' + expected_tool if expected_tool else 'Direct response'}")
        
        try:
            task_id = f"test_main_sim_{test_name.replace(' ', '_').replace('(', '').replace(')', '').lower()}"
            
            response = await invoke_google_ai_studio_chat_completions(
                task_id=task_id,
                model_id=model_id,
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0.7,
                max_tokens=500,
                tools=test_tools,
                tool_choice=tool_choice,
                stream=stream
            )
            
            # Collect response
            tool_calls = []
            text_content = ""
            
            async for chunk in response:
                if isinstance(chunk, str):
                    text_content += chunk
                else:
                    from backend.apps.ai.llm_providers.google_client import ParsedGoogleToolCall
                    if hasattr(chunk, 'function_name'):
                        tool_calls.append(chunk)
            
            # Validate based on expectation
            if expected_tool:
                # We expected a tool call
                if not tool_calls:
                    print(f"❌ FAIL - Expected tool '{expected_tool}' but got direct response")
                    print(f"  Response: {text_content[:200]}...")
                    results["failed"].append((test_name, f"Expected tool {expected_tool}, got text"))
                elif tool_calls[0].function_name != expected_tool:
                    print(f"⚠️  Got different tool: {tool_calls[0].function_name} (expected {expected_tool})")
                    print(f"  Arguments: {tool_calls[0].function_arguments_parsed}")
                    # This might be acceptable depending on the model's interpretation
                    results["passed"].append(test_name + " (different tool)")
                else:
                    print(f"✅ PASS - Got expected tool call: {expected_tool}")
                    print(f"  Arguments: {tool_calls[0].function_arguments_parsed}")
                    results["passed"].append(test_name)
            else:
                # We expected a direct response
                if tool_calls:
                    print(f"⚠️  Got tool call when direct response expected: {tool_calls[0].function_name}")
                    # This might be acceptable - model decided to use tools
                    results["passed"].append(test_name + " (used tool)")
                elif text_content:
                    print(f"✅ PASS - Got direct response")
                    print(f"  Response: {text_content[:200]}...")
                    results["passed"].append(test_name)
                else:
                    print(f"❌ FAIL - No response received")
                    results["failed"].append((test_name, "No response"))
                    
        except Exception as e:
            print(f"❌ ERROR - {type(e).__name__}: {e}")
            results["errors"].append((test_name, str(e)))
            logger.exception(f"Error in main processor simulation '{test_name}'")
    
    return results


async def run_integration_tests(run_streaming=True, run_function_calling=True, run_main_sim=True):
    """
    Run integration tests for Gemini 3 Flash via Google AI Studio.
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    print("\n" + "="*80)
    print("GEMINI 3 FLASH INTEGRATION TESTS (Google AI Studio)")
    print("="*80 + "\n")
    
    # Initialize services
    print("Initializing SecretsManager...")
    secrets_manager = SecretsManager()
    
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialized successfully (connected to Vault)")
    except Exception as e:
        print(f"❌ Failed to initialize SecretsManager: {e}")
        print("\nHINT: Make sure you're running this inside the Docker container where Vault is accessible.")
        print("Run with: docker compose exec api python /app/backend/scripts/test_gemini_flash_function_calling.py")
        return 1
    
    # Check if API key is available
    from backend.apps.ai.llm_providers.google_client import _get_google_ai_studio_api_key
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        print("\n❌ Google AI Studio API key not found!")
        print("Make sure GEMINI_API_KEY or SECRET__GOOGLE_AI_STUDIO__API_KEY is set in your environment")
        print("or the key is stored in Vault at kv/data/providers/google_ai_studio")
        return 1
    print(f"✅ Google AI Studio API key found (length: {len(api_key)})")
    
    # Aggregate results
    all_results = {"passed": [], "failed": [], "errors": []}
    
    # Run test suites based on flags
    if run_streaming:
        streaming_results = await run_streaming_tests(secrets_manager)
        all_results["passed"].extend(streaming_results["passed"])
        all_results["failed"].extend(streaming_results["failed"])
        all_results["errors"].extend(streaming_results["errors"])
    
    if run_function_calling:
        fc_results = await run_function_calling_tests(secrets_manager)
        all_results["passed"].extend(fc_results["passed"])
        all_results["failed"].extend(fc_results["failed"])
        all_results["errors"].extend(fc_results["errors"])
    
    if run_main_sim:
        main_sim_results = await run_main_processor_simulation(secrets_manager)
        all_results["passed"].extend(main_sim_results["passed"])
        all_results["failed"].extend(main_sim_results["failed"])
        all_results["errors"].extend(main_sim_results["errors"])
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    total = len(all_results["passed"]) + len(all_results["failed"]) + len(all_results["errors"])
    passed = len(all_results["passed"])
    failed = len(all_results["failed"])
    errors = len(all_results["errors"])
    
    print(f"\nTotal: {total} tests")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"💥 Errors: {errors}")
    
    if all_results["passed"]:
        print("\nPassed tests:")
        for name in all_results["passed"]:
            print(f"  ✅ {name}")
    
    if all_results["failed"]:
        print("\nFailed tests:")
        for name, reason in all_results["failed"]:
            print(f"  ❌ {name}: {reason}")
    
    if all_results["errors"]:
        print("\nError tests:")
        for name, error in all_results["errors"]:
            print(f"  💥 {name}: {error}")
    
    print("\n" + "="*80)
    
    # Return exit code
    if failed > 0 or errors > 0:
        print("❌ SOME TESTS FAILED")
        return 1
    else:
        print("✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Gemini 3 Flash via Google AI Studio")
    parser.add_argument("--streaming-only", action="store_true", help="Run only streaming tests")
    parser.add_argument("--function-calling-only", action="store_true", help="Run only function calling tests")
    parser.add_argument("--main-sim-only", action="store_true", help="Run only main processor simulation tests")
    args = parser.parse_args()
    
    # Determine which tests to run
    run_streaming = True
    run_fc = True
    run_main = True
    
    if args.streaming_only:
        run_streaming = True
        run_fc = False
        run_main = False
    elif args.function_calling_only:
        run_streaming = False
        run_fc = True
        run_main = False
    elif args.main_sim_only:
        run_streaming = False
        run_fc = False
        run_main = True
    
    exit_code = asyncio.run(run_integration_tests(run_streaming, run_fc, run_main))
    sys.exit(exit_code)
