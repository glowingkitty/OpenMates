#!/usr/bin/env python3
# backend/scripts/test_demo_chat_translation.py
#
# Test script for demo chat translation functionality.
# Tests both simple text and Tiptap JSON translation using Gemini 3 Flash.
#
# Run via docker exec:
#   docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/test_demo_chat_translation.py
#
# Or test specific languages:
#   docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/test_demo_chat_translation.py --languages de es fr

import asyncio
import sys
import logging
import json
import argparse
from typing import Optional

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


class MockTask:
    """
    Mock task object that provides the secrets_manager property
    needed by the translation functions.
    """
    def __init__(self, secrets_manager):
        self._secrets_manager = secrets_manager
    
    @property
    def secrets_manager(self):
        return self._secrets_manager


async def translate_text(task, text: str, target_lang: str) -> str:
    """
    Translate a single string using Gemini 3 Flash.
    This is a copy of _translate_text from demo_tasks.py for testing.
    """
    if not text:
        return ""
    
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    messages = [
        {"role": "system", "content": f"You are a professional translator. Translate the following text to the language with code '{target_lang}'. Return only the translated text, no explanation or formatting."},
        {"role": "user", "content": text}
    ]
    
    try:
        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"translate_{target_lang}",
            model_id="gemini-3-flash-preview",
            messages=messages,
            secrets_manager=task.secrets_manager,
            temperature=0.3,
            max_tokens=2000,
            stream=False
        )
        
        if response.success and response.direct_message_content:
            return response.direct_message_content.strip()
        else:
            logger.error(f"Translation failed for {target_lang}: {response.error_message}")
            return text
    except Exception as e:
        logger.error(f"Error calling Gemini for translation: {e}")
        return text


async def translate_tiptap_json(task, tiptap_json: str, target_lang: str) -> str:
    """
    Translate Tiptap JSON content using Gemini 3 Flash.
    This is a copy of _translate_tiptap_json from demo_tasks.py for testing.
    """
    if not tiptap_json:
        return ""
    
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    # Simple check if it's actually JSON
    try:
        json.loads(tiptap_json)
    except Exception:
        return await translate_text(task, tiptap_json, target_lang)

    messages = [
        {"role": "system", "content": f"""You are a professional translator. 
Translate the 'text' values in the following Tiptap JSON to the language with code '{target_lang}'. 
Keep all other JSON structure, keys, and non-text values exactly as they are. 
Return only the valid JSON result."""},
        {"role": "user", "content": tiptap_json}
    ]
    
    try:
        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"translate_json_{target_lang}",
            model_id="gemini-3-flash-preview",
            messages=messages,
            secrets_manager=task.secrets_manager,
            temperature=0.1, # Lower temperature for structural integrity
            max_tokens=4000,
            stream=False
        )
        
        if response.success and response.direct_message_content:
            result = response.direct_message_content.strip()
            # Try to clean up markdown code blocks if AI included them
            if result.startswith("```json"):
                result = result.split("```json")[1].split("```")[0].strip()
            elif result.startswith("```"):
                result = result.split("```")[1].split("```")[0].strip()
            
            # Validate JSON
            try:
                json.loads(result)
                return result
            except Exception:
                logger.error(f"AI returned invalid JSON for translation to {target_lang}")
                return tiptap_json
        else:
            logger.error(f"JSON translation failed for {target_lang}: {response.error_message}")
            return tiptap_json
    except Exception as e:
        logger.error(f"Error calling Gemini for JSON translation: {e}")
        return tiptap_json


async def test_simple_text_translation(task, languages: list):
    """
    Test simple text translation (for titles, summaries, follow-up suggestions).
    """
    print("\n" + "="*80)
    print("SIMPLE TEXT TRANSLATION TESTS")
    print("="*80 + "\n")
    
    test_cases = [
        "How to build a REST API with Python",
        "This chat demonstrates advanced AI capabilities including code generation and analysis.",
        "Tell me more about this topic",
        "Can you explain this in simpler terms?",
        "What are the best practices for this?"
    ]
    
    results = {"passed": [], "failed": []}
    
    for test_text in test_cases:
        print(f"\n{'─'*60}")
        print(f"Original text: {test_text}")
        print(f"{'─'*60}")
        
        for lang in languages:
            try:
                translated = await translate_text(task, test_text, lang)
                
                if translated and translated != test_text:
                    print(f"  [{lang:3}] ✓ {translated[:80]}{'...' if len(translated) > 80 else ''}")
                    results["passed"].append((test_text, lang, translated))
                else:
                    print(f"  [{lang:3}] ✗ Translation failed or returned original text")
                    results["failed"].append((test_text, lang, translated))
            except Exception as e:
                print(f"  [{lang:3}] ✗ Error: {e}")
                results["failed"].append((test_text, lang, str(e)))
    
    return results


async def test_tiptap_json_translation(task, languages: list):
    """
    Test Tiptap JSON translation (for message content).
    """
    print("\n" + "="*80)
    print("TIPTAP JSON TRANSLATION TESTS")
    print("="*80 + "\n")
    
    # Sample Tiptap JSON structure (typical message format)
    test_cases = [
        {
            "name": "Simple paragraph",
            "json": json.dumps({
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Hello! How can I help you today?"
                            }
                        ]
                    }
                ]
            })
        },
        {
            "name": "Paragraph with formatting",
            "json": json.dumps({
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "This is a ",
                                "marks": []
                            },
                            {
                                "type": "text",
                                "text": "bold",
                                "marks": [{"type": "bold"}]
                            },
                            {
                                "type": "text",
                                "text": " statement."
                            }
                        ]
                    }
                ]
            })
        },
        {
            "name": "Multiple paragraphs",
            "json": json.dumps({
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "First paragraph with some content."
                            }
                        ]
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Second paragraph with more detailed information about the topic."
                            }
                        ]
                    }
                ]
            })
        },
        {
            "name": "Code block",
            "json": json.dumps({
                "type": "doc",
                "content": [
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "python"},
                        "content": [
                            {
                                "type": "text",
                                "text": "def hello():\n    print('Hello, World!')"
                            }
                        ]
                    }
                ]
            })
        }
    ]
    
    results = {"passed": [], "failed": []}
    
    for test_case in test_cases:
        print(f"\n{'─'*60}")
        print(f"Test: {test_case['name']}")
        print(f"Original JSON: {test_case['json'][:100]}...")
        print(f"{'─'*60}")
        
        for lang in languages:
            try:
                translated = await translate_tiptap_json(task, test_case['json'], lang)
                
                # Validate the result
                try:
                    parsed = json.loads(translated)
                    # Check if structure is preserved
                    if parsed.get("type") == "doc" and "content" in parsed:
                        # Extract text content for display
                        text_content = []
                        def extract_text(node):
                            if isinstance(node, dict):
                                if node.get("type") == "text" and "text" in node:
                                    text_content.append(node["text"])
                                if "content" in node:
                                    for child in node["content"]:
                                        extract_text(child)
                        
                        extract_text(parsed)
                        text_preview = " ".join(text_content)[:80]
                        
                        print(f"  [{lang:3}] ✓ Valid JSON - Text: {text_preview}{'...' if len(' '.join(text_content)) > 80 else ''}")
                        results["passed"].append((test_case['name'], lang, translated))
                    else:
                        print(f"  [{lang:3}] ✗ Invalid structure - missing 'doc' type or 'content'")
                        results["failed"].append((test_case['name'], lang, "Invalid structure"))
                except json.JSONDecodeError as e:
                    print(f"  [{lang:3}] ✗ Invalid JSON: {e}")
                    results["failed"].append((test_case['name'], lang, f"Invalid JSON: {e}"))
            except Exception as e:
                print(f"  [{lang:3}] ✗ Error: {e}")
                results["failed"].append((test_case['name'], lang, str(e)))
    
    return results


async def main():
    """
    Main test function that initializes services and runs translation tests.
    """
    parser = argparse.ArgumentParser(description="Test demo chat translation functionality")
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["de", "es", "fr", "zh", "ja"],
        help="Languages to test (default: de es fr zh ja)"
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Only test simple text translation"
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Only test Tiptap JSON translation"
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("DEMO CHAT TRANSLATION TEST")
    print("="*80)
    print(f"Testing languages: {', '.join(args.languages)}")
    print(f"Model: gemini-3-flash-preview")
    print("="*80)
    
    # Initialize SecretsManager
    print("\nInitializing SecretsManager...")
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
        print("✓ SecretsManager initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize SecretsManager: {e}")
        sys.exit(1)
    
    # Create mock task
    task = MockTask(secrets_manager)
    
    try:
        all_results = {}
        
        # Test simple text translation
        if not args.json_only:
            text_results = await test_simple_text_translation(task, args.languages)
            all_results["text"] = text_results
        
        # Test Tiptap JSON translation
        if not args.text_only:
            json_results = await test_tiptap_json_translation(task, args.languages)
            all_results["json"] = json_results
        
        # Print summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        if "text" in all_results:
            text_results = all_results["text"]
            print(f"\nSimple Text Translation:")
            print(f"  Passed: {len(text_results['passed'])}")
            print(f"  Failed: {len(text_results['failed'])}")
        
        if "json" in all_results:
            json_results = all_results["json"]
            print(f"\nTiptap JSON Translation:")
            print(f"  Passed: {len(json_results['passed'])}")
            print(f"  Failed: {len(json_results['failed'])}")
        
        # Overall status
        total_passed = sum(len(r["passed"]) for r in all_results.values())
        total_failed = sum(len(r["failed"]) for r in all_results.values())
        
        print(f"\nOverall:")
        print(f"  Total Passed: {total_passed}")
        print(f"  Total Failed: {total_failed}")
        
        if total_failed == 0:
            print("\n✓ All tests passed!")
            return 0
        else:
            print(f"\n✗ {total_failed} test(s) failed")
            return 1
    
    finally:
        # Cleanup
        try:
            await secrets_manager.aclose()
            print("\n✓ SecretsManager closed successfully")
        except Exception as e:
            print(f"\n⚠ Warning: Error closing SecretsManager: {e}")


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        sys.exit(1)
