#!/usr/bin/env python3
# backend/scripts/test_gemini_3_1_pro.py
#
# Integration test script for Gemini 3.1 Pro via Google AI Studio (primary) and
# OpenRouter (fallback). Tests streaming, function calling, and multi-turn
# conversations to confirm the model works end-to-end through both providers.
#
# Run via docker exec:
#   docker exec api python /app/backend/scripts/test_gemini_3_1_pro.py
#
# Or limit to a single provider:
#   docker exec api python /app/backend/scripts/test_gemini_3_1_pro.py --google-only
#   docker exec api python /app/backend/scripts/test_gemini_3_1_pro.py --openrouter-only

import asyncio
import sys
import logging
import argparse
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy SDK logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("google").setLevel(logging.WARNING)

# ─── Model IDs ──────────────────────────────────────────────────────────────

# The model_id as declared in backend/providers/google.yml (used for our
# internal config lookups) and as required by the Google AI Studio API.
GOOGLE_MODEL_ID = "gemini-3.1-pro-preview"

# The fully-qualified model ID expected by OpenRouter.
OPENROUTER_MODEL_ID = "google/gemini-3.1-pro-preview"

# ─── Shared test fixtures ────────────────────────────────────────────────────

BASE_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant. Keep all responses concise."},
    {"role": "user", "content": "Hello! Please respond with exactly: 'Gemini 3.1 Pro is online.'"},
]

MULTITURN_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
    {"role": "assistant", "content": "The capital of France is Paris."},
    {"role": "user", "content": "What river runs through it?"},
]

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city. Call this when the user asks about weather.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Berlin'"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Perform arithmetic. Call this for any calculation request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide"]
                    },
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                },
                "required": ["operation", "a", "b"]
            }
        }
    }
]


# ─── Google AI Studio tests ──────────────────────────────────────────────────

async def test_google_ai_studio(secrets_manager) -> Dict[str, List]:
    """
    Run tests against Google AI Studio using the native google-genai SDK.
    Covers: non-streaming response, streaming response, multi-turn, function calling.
    """
    from backend.apps.ai.llm_providers.google_client import (
        invoke_google_ai_studio_chat_completions,
        _get_google_ai_studio_api_key,
        ParsedGoogleToolCall,
        GoogleUsageMetadata,
    )

    print("\n" + "=" * 80)
    print("GOOGLE AI STUDIO TESTS — gemini-3.1-pro-preview")
    print("=" * 80)

    results: Dict[str, List] = {"passed": [], "failed": [], "errors": []}

    # ── API key check ────────────────────────────────────────────────────────
    api_key = await _get_google_ai_studio_api_key(secrets_manager)
    if not api_key:
        print("❌ Google AI Studio API key not found — skipping all Google tests.")
        results["errors"].append(("API key check", "Key not found in Vault"))
        return results
    print(f"✅ API key found (length: {len(api_key)})\n")

    # ── Helper: run a single Google call ────────────────────────────────────
    async def call_google(label: str, messages, stream: bool,
                          tools=None, tool_choice=None, max_tokens=200):
        print(f"{'─'*60}")
        print(f"TEST: {label}")
        print(f"{'─'*60}")
        try:
            resp = await invoke_google_ai_studio_chat_completions(
                task_id=f"test_gemini31pro_{label.lower().replace(' ', '_')}",
                model_id=GOOGLE_MODEL_ID,
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                stream=stream,
            )
            return resp
        except Exception as e:
            print(f"❌ ERROR — {type(e).__name__}: {e}")
            results["errors"].append((label, str(e)))
            logger.exception(f"Exception in '{label}'")
            return None

    # ── 1. Non-streaming basic response ─────────────────────────────────────
    label = "Non-streaming basic response"
    resp = await call_google(label, BASE_MESSAGES, stream=False)
    if resp is not None:
        if resp.success and resp.direct_message_content:
            print(f"✅ PASS — Response: {resp.direct_message_content[:120]}")
            if resp.usage:
                print(f"   Tokens: {resp.usage.prompt_token_count} in / {resp.usage.candidates_token_count} out")
            results["passed"].append(label)
        else:
            reason = resp.error_message or "Empty response"
            print(f"❌ FAIL — {reason}")
            results["failed"].append((label, reason))

    # ── 2. Streaming basic response ──────────────────────────────────────────
    label = "Streaming basic response"
    resp = await call_google(label, BASE_MESSAGES, stream=True)
    if resp is not None:
        text = ""
        chunk_count = 0
        try:
            async for chunk in resp:
                if isinstance(chunk, str):
                    text += chunk
                    chunk_count += 1
                elif isinstance(chunk, GoogleUsageMetadata):
                    print(f"   Tokens: {chunk.prompt_token_count} in / {chunk.candidates_token_count} out")
        except Exception as e:
            print(f"❌ ERROR reading stream — {e}")
            results["errors"].append((label, str(e)))
            text = None

        if text:
            print(f"✅ PASS — {chunk_count} chunks, {len(text)} chars: {text[:100]}")
            results["passed"].append(label)
        elif text is not None:
            print("❌ FAIL — Stream returned no text")
            results["failed"].append((label, "Empty stream"))

    # ── 3. Multi-turn streaming ──────────────────────────────────────────────
    label = "Multi-turn streaming"
    resp = await call_google(label, MULTITURN_MESSAGES, stream=True)
    if resp is not None:
        text = ""
        try:
            async for chunk in resp:
                if isinstance(chunk, str):
                    text += chunk
        except Exception as e:
            print(f"❌ ERROR reading stream — {e}")
            results["errors"].append((label, str(e)))
            text = None

        if text:
            print(f"✅ PASS — {len(text)} chars: {text[:100]}")
            results["passed"].append(label)
        elif text is not None:
            print("❌ FAIL — No text received")
            results["failed"].append((label, "Empty stream"))

    # ── 4. Function calling (non-streaming) ──────────────────────────────────
    label = "Function calling (non-streaming)"
    tool_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the weather in Berlin?"},
    ]
    resp = await call_google(label, tool_messages, stream=False,
                             tools=TOOL_DEFS, tool_choice="auto")
    if resp is not None:
        if resp.success and resp.tool_calls_made:
            tool_call = resp.tool_calls_made[0]
            print(f"✅ PASS — Called: {tool_call.function_name}({tool_call.function_arguments_parsed})")
            results["passed"].append(label)
        elif resp.success:
            # Model gave a direct answer instead of calling the tool — warn but don't fail.
            print(f"⚠️  PASS (no tool) — Direct response: {resp.direct_message_content[:100]}")
            results["passed"].append(label + " (direct)")
        else:
            print(f"❌ FAIL — {resp.error_message}")
            results["failed"].append((label, resp.error_message or "Unknown error"))

    # ── 5. Function calling (streaming) ──────────────────────────────────────
    label = "Function calling (streaming)"
    calc_messages = [
        {"role": "system", "content": "You are a calculator assistant. Always use the calculate tool."},
        {"role": "user", "content": "What is 13 multiplied by 7?"},
    ]
    resp = await call_google(label, calc_messages, stream=True,
                             tools=TOOL_DEFS, tool_choice="required")
    if resp is not None:
        tool_calls = []
        text = ""
        try:
            async for chunk in resp:
                if isinstance(chunk, str):
                    text += chunk
                elif isinstance(chunk, ParsedGoogleToolCall):
                    tool_calls.append(chunk)
                    print(f"   Tool call: {chunk.function_name}({chunk.function_arguments_parsed})")
        except Exception as e:
            print(f"❌ ERROR reading stream — {e}")
            results["errors"].append((label, str(e)))
            tool_calls = None

        if tool_calls is not None:
            if tool_calls:
                print(f"✅ PASS — Got {len(tool_calls)} tool call(s) via stream")
                results["passed"].append(label)
            else:
                msg = f"No tool calls received; text: {text[:100]}"
                print(f"❌ FAIL — {msg}")
                results["failed"].append((label, msg))

    return results


# ─── OpenRouter tests ────────────────────────────────────────────────────────

async def test_openrouter(secrets_manager) -> Dict[str, List]:
    """
    Run tests against OpenRouter using the OpenAI-compatible client.
    Covers: non-streaming response, streaming response, function calling.
    """
    from backend.apps.ai.llm_providers.openai_openrouter import (
        invoke_openrouter_chat_completions,
        _get_openrouter_api_key,
    )
    from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall

    print("\n" + "=" * 80)
    print("OPENROUTER TESTS — google/gemini-3.1-pro-preview")
    print("=" * 80)

    results: Dict[str, List] = {"passed": [], "failed": [], "errors": []}

    # ── API key check ────────────────────────────────────────────────────────
    api_key = await _get_openrouter_api_key(secrets_manager)
    if not api_key:
        print("❌ OpenRouter API key not found — skipping all OpenRouter tests.")
        results["errors"].append(("API key check", "Key not found in Vault"))
        return results
    print(f"✅ OpenRouter API key found (length: {len(api_key)})\n")

    # ── Helper: run a single OpenRouter call ────────────────────────────────
    async def call_openrouter(label: str, messages, stream: bool,
                              tools=None, tool_choice=None, max_tokens=200):
        print(f"{'─'*60}")
        print(f"TEST: {label}")
        print(f"{'─'*60}")
        try:
            resp = await invoke_openrouter_chat_completions(
                task_id=f"test_gemini31pro_or_{label.lower().replace(' ', '_')}",
                model_id=OPENROUTER_MODEL_ID,
                messages=messages,
                secrets_manager=secrets_manager,
                temperature=0,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice=tool_choice,
                stream=stream,
            )
            return resp
        except Exception as e:
            print(f"❌ ERROR — {type(e).__name__}: {e}")
            results["errors"].append((label, str(e)))
            logger.exception(f"Exception in '{label}'")
            return None

    # ── 1. Non-streaming basic response ─────────────────────────────────────
    label = "OR: Non-streaming basic response"
    resp = await call_openrouter(label, BASE_MESSAGES, stream=False)
    if resp is not None:
        if resp.success and resp.direct_message_content:
            print(f"✅ PASS — Response: {resp.direct_message_content[:120]}")
            if resp.usage:
                print(f"   Tokens: {resp.usage.total_tokens} total")
            results["passed"].append(label)
        else:
            reason = resp.error_message or "Empty response"
            print(f"❌ FAIL — {reason}")
            results["failed"].append((label, reason))

    # ── 2. Streaming basic response ──────────────────────────────────────────
    label = "OR: Streaming basic response"
    resp = await call_openrouter(label, BASE_MESSAGES, stream=True)
    if resp is not None:
        text = ""
        chunk_count = 0
        try:
            async for chunk in resp:
                if isinstance(chunk, str):
                    text += chunk
                    chunk_count += 1
        except Exception as e:
            print(f"❌ ERROR reading stream — {e}")
            results["errors"].append((label, str(e)))
            text = None

        if text:
            print(f"✅ PASS — {chunk_count} chunks, {len(text)} chars: {text[:100]}")
            results["passed"].append(label)
        elif text is not None:
            print("❌ FAIL — Stream returned no text")
            results["failed"].append((label, "Empty stream"))

    # ── 3. Function calling (non-streaming) ──────────────────────────────────
    label = "OR: Function calling (non-streaming)"
    tool_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the weather in Tokyo?"},
    ]
    resp = await call_openrouter(label, tool_messages, stream=False,
                                 tools=TOOL_DEFS, tool_choice="auto")
    if resp is not None:
        if resp.success and resp.tool_calls_made:
            tool_call = resp.tool_calls_made[0]
            print(f"✅ PASS — Called: {tool_call.function_name}({tool_call.function_arguments_parsed})")
            results["passed"].append(label)
        elif resp.success:
            print(f"⚠️  PASS (no tool) — Direct: {resp.direct_message_content[:100]}")
            results["passed"].append(label + " (direct)")
        else:
            print(f"❌ FAIL — {resp.error_message}")
            results["failed"].append((label, resp.error_message or "Unknown error"))

    # ── 4. Streaming function calling ────────────────────────────────────────
    label = "OR: Function calling (streaming)"
    calc_messages = [
        {"role": "system", "content": "You are a calculator assistant. Always use the calculate tool."},
        {"role": "user", "content": "What is 99 divided by 3?"},
    ]
    resp = await call_openrouter(label, calc_messages, stream=True,
                                 tools=TOOL_DEFS, tool_choice="required")
    if resp is not None:
        tool_calls = []
        text = ""
        try:
            async for chunk in resp:
                if isinstance(chunk, str):
                    text += chunk
                elif isinstance(chunk, ParsedOpenAIToolCall):
                    tool_calls.append(chunk)
                    print(f"   Tool call: {chunk.function_name}({chunk.function_arguments_parsed})")
        except Exception as e:
            print(f"❌ ERROR reading stream — {e}")
            results["errors"].append((label, str(e)))
            tool_calls = None

        if tool_calls is not None:
            if tool_calls:
                print(f"✅ PASS — Got {len(tool_calls)} tool call(s) via stream")
                results["passed"].append(label)
            else:
                msg = f"No tool calls received; text: {text[:100]}"
                print(f"❌ FAIL — {msg}")
                results["failed"].append((label, msg))

    return results


# ─── Entry point ─────────────────────────────────────────────────────────────

async def run_all_tests(run_google: bool = True, run_openrouter: bool = True) -> int:
    """
    Main test runner. Initialises shared infrastructure, then runs the
    requested provider test suites and prints a unified summary.
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.core.api.app.utils.config_manager import config_manager

    print("\n" + "=" * 80)
    print("GEMINI 3.1 PRO INTEGRATION TESTS")
    print("=" * 80 + "\n")

    # ── Config presence check ────────────────────────────────────────────────
    print(f"Checking provider config for '{GOOGLE_MODEL_ID}'...")
    model_cfg = config_manager.get_model_pricing("google", GOOGLE_MODEL_ID)
    if model_cfg:
        print(f"✅ Config found: {model_cfg.get('name')} — {model_cfg.get('description', '')[:80]}")
        print(f"   Servers: {[s.get('id') for s in model_cfg.get('servers', [])]}")
    else:
        print(f"❌ Config NOT found for '{GOOGLE_MODEL_ID}' in google.yml — aborting.")
        return 1

    # ── SecretsManager ───────────────────────────────────────────────────────
    print("\nInitialising SecretsManager...")
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✅ SecretsManager initialised (connected to Vault)")
    except Exception as e:
        print(f"❌ SecretsManager init failed: {e}")
        print("HINT: Run inside Docker with: docker exec api python /app/backend/scripts/test_gemini_3_1_pro.py")
        return 1

    all_results: Dict[str, List] = {"passed": [], "failed": [], "errors": []}

    # ── Provider test suites ─────────────────────────────────────────────────
    if run_google:
        r = await test_google_ai_studio(secrets_manager)
        all_results["passed"].extend(r["passed"])
        all_results["failed"].extend(r["failed"])
        all_results["errors"].extend(r["errors"])

    if run_openrouter:
        r = await test_openrouter(secrets_manager)
        all_results["passed"].extend(r["passed"])
        all_results["failed"].extend(r["failed"])
        all_results["errors"].extend(r["errors"])

    # ── Summary ──────────────────────────────────────────────────────────────
    total = len(all_results["passed"]) + len(all_results["failed"]) + len(all_results["errors"])
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total:   {total}")
    print(f"✅ Passed:  {len(all_results['passed'])}")
    print(f"❌ Failed:  {len(all_results['failed'])}")
    print(f"💥 Errors:  {len(all_results['errors'])}")

    if all_results["passed"]:
        print("\nPassed:")
        for name in all_results["passed"]:
            print(f"  ✅ {name}")

    if all_results["failed"]:
        print("\nFailed:")
        for name, reason in all_results["failed"]:
            print(f"  ❌ {name}: {reason}")

    if all_results["errors"]:
        print("\nErrors:")
        for name, err in all_results["errors"]:
            print(f"  💥 {name}: {err}")

    print("=" * 80)

    if all_results["failed"] or all_results["errors"]:
        print("❌ SOME TESTS FAILED")
        return 1
    print("✅ ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.path.append("/app")

    parser = argparse.ArgumentParser(description="Integration tests for Gemini 3.1 Pro")
    parser.add_argument("--google-only", action="store_true",
                        help="Only test Google AI Studio")
    parser.add_argument("--openrouter-only", action="store_true",
                        help="Only test OpenRouter")
    args = parser.parse_args()

    run_google = not args.openrouter_only
    run_openrouter = not args.google_only

    exit_code = asyncio.run(run_all_tests(run_google=run_google, run_openrouter=run_openrouter))
    sys.exit(exit_code)
