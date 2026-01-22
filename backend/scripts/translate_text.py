#!/usr/bin/env python3
# backend/scripts/translate_text.py
#
# Standalone translation script for translating text to multiple languages.
# Useful for testing translation quality and ad-hoc translation needs.
#
# Usage:
#   docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py "Hello, world!"
#
#   # Translate to specific languages
#   docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py "Hello, world!" --languages de es fr
#
#   # Translate Tiptap JSON
#   docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Hello"}]}]}' --json
#
#   # Output as JSON
#   docker compose --env-file .env -f backend/core/docker-compose.yml exec api python /app/backend/scripts/translate_text.py "Hello" --json-output

import asyncio
import sys
import logging
import json
import argparse
from typing import Optional, Dict, List

# Set up logging
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings/errors
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("google").setLevel(logging.ERROR)


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


async def translate_text_batch(secrets_manager, text: str, target_languages: List[str]) -> Dict[str, str]:
    """
    Translate a single string to multiple languages in one API call using function calling.
    Returns a dictionary mapping language codes to translations.
    """
    if not text:
        return {lang: "" for lang in target_languages}
    
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    # Build function schema with output fields for each target language
    properties = {}
    for lang in target_languages:
        properties[lang] = {
            "type": "string",
            "description": f"Translation to {lang} language"
        }
    
    translation_tool = {
        "type": "function",
        "function": {
            "name": "return_translations",
            "description": "Return translations of the provided text to all target languages. Translate the text naturally and accurately to each language.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": target_languages
            }
        }
    }
    
    messages = [
        {"role": "system", "content": "You are a professional translator. Translate the provided text to all requested languages accurately and naturally."},
        {"role": "user", "content": f"Translate the following text to all target languages: {text}"}
    ]
    
    try:
        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"translate_batch_{hash(text) % 10000}",
            model_id="gemini-3-flash-preview",
            messages=messages,
            secrets_manager=secrets_manager,
            tools=[translation_tool],
            tool_choice="required",
            temperature=0.3,
            max_tokens=4000,
            stream=False
        )
        
        if response.success and response.tool_calls_made:
            # Extract translations from function call
            for tool_call in response.tool_calls_made:
                if tool_call.function_name == "return_translations":
                    translations = tool_call.function_arguments_parsed
                    # Ensure all languages are present, use original text as fallback
                    result = {}
                    for lang in target_languages:
                        result[lang] = translations.get(lang, text)
                    return result
        
        # Fallback: if function calling failed, return original text for all languages
        logger.error(f"Batch translation failed: {response.error_message if hasattr(response, 'error_message') else 'No function call returned'}")
        return {lang: text for lang in target_languages}
    except Exception as e:
        logger.error(f"Error calling Gemini for batch translation: {e}")
        return {lang: text for lang in target_languages}


async def translate_tiptap_json_batch(secrets_manager, tiptap_json: str, target_languages: List[str]) -> Dict[str, str]:
    """
    Translate Tiptap JSON content to multiple languages in one API call using function calling.
    Returns a dictionary mapping language codes to translated JSON strings.
    """
    if not tiptap_json:
        return {lang: "" for lang in target_languages}
    
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    # Simple check if it's actually JSON
    try:
        json.loads(tiptap_json)
    except Exception:
        # If not JSON, treat as plain text
        return await translate_text_batch(secrets_manager, tiptap_json, target_languages)
    
    # Build function schema with output fields for each target language
    properties = {}
    for lang in target_languages:
        properties[lang] = {
            "type": "string",
            "description": f"Translated Tiptap JSON for {lang} language. Must be valid JSON with the same structure as the input, only 'text' values translated."
        }
    
    translation_tool = {
        "type": "function",
        "function": {
            "name": "return_translated_json",
            "description": "Return translated Tiptap JSON for all target languages. Translate only the 'text' values in the JSON structure. Keep all other JSON structure, keys, and non-text values exactly as they are. Each output must be valid JSON.",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": target_languages
            }
        }
    }
    
    messages = [
        {"role": "system", "content": "You are a professional translator. Translate the 'text' values in the provided Tiptap JSON to all requested languages. Keep all JSON structure, keys, and non-text values exactly as they are. Return valid JSON for each language."},
        {"role": "user", "content": f"Translate the following Tiptap JSON to all target languages: {tiptap_json}"}
    ]
    
    try:
        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"translate_json_batch_{hash(tiptap_json) % 10000}",
            model_id="gemini-3-flash-preview",
            messages=messages,
            secrets_manager=secrets_manager,
            tools=[translation_tool],
            tool_choice="required",
            temperature=0.1, # Lower temperature for structural integrity
            max_tokens=8000, # Increased for multiple JSON outputs
            stream=False
        )
        
        if response.success and response.tool_calls_made:
            # Extract translations from function call
            for tool_call in response.tool_calls_made:
                if tool_call.function_name == "return_translated_json":
                    translations = tool_call.function_arguments_parsed
                    # Validate each translation is valid JSON
                    result = {}
                    for lang in target_languages:
                        translated_json = translations.get(lang, tiptap_json)
                        # Try to clean up markdown code blocks if AI included them
                        if isinstance(translated_json, str):
                            if translated_json.startswith("```json"):
                                translated_json = translated_json.split("```json")[1].split("```")[0].strip()
                            elif translated_json.startswith("```"):
                                translated_json = translated_json.split("```")[1].split("```")[0].strip()
                        
                        # Validate JSON
                        try:
                            json.loads(translated_json)
                            result[lang] = translated_json
                        except Exception:
                            logger.error(f"AI returned invalid JSON for translation to {lang}")
                            result[lang] = tiptap_json
                    return result
        
        # Fallback: if function calling failed, return original JSON for all languages
        logger.error(f"Batch JSON translation failed: {response.error_message if hasattr(response, 'error_message') else 'No function call returned'}")
        return {lang: tiptap_json for lang in target_languages}
    except Exception as e:
        logger.error(f"Error calling Gemini for batch JSON translation: {e}")
        return {lang: tiptap_json for lang in target_languages}


async def main():
    """
    Main function for the translation script.
    """
    parser = argparse.ArgumentParser(
        description="Translate text to multiple languages using Gemini 3 Flash",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Translate simple text
  python translate_text.py "Hello, world!"
  
  # Translate to specific languages
  python translate_text.py "Hello" --languages de es fr
  
  # Translate Tiptap JSON
  python translate_text.py '{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"Hello"}]}]}' --json
  
  # Output as JSON
  python translate_text.py "Hello" --json-output
        """
    )
    parser.add_argument(
        "text",
        help="Text to translate (or Tiptap JSON if --json is used)"
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"],
        help="Target languages (default: all 20 supported languages)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Treat input as Tiptap JSON instead of plain text"
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON instead of human-readable format"
    )
    
    args = parser.parse_args()
    
    # Initialize SecretsManager
    print("Initializing translation service...", file=sys.stderr)
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    
    secrets_manager = SecretsManager()
    try:
        await secrets_manager.initialize()
    except Exception as e:
        print(f"Error: Failed to initialize SecretsManager: {e}", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Translate
        if args.json:
            translations = await translate_tiptap_json_batch(secrets_manager, args.text, args.languages)
        else:
            translations = await translate_text_batch(secrets_manager, args.text, args.languages)
        
        # Output results
        if args.json_output:
            # JSON output
            print(json.dumps(translations, ensure_ascii=False, indent=2))
        else:
            # Human-readable output
            print(f"\nOriginal text: {args.text[:100]}{'...' if len(args.text) > 100 else ''}")
            print("=" * 80)
            for lang in args.languages:
                translation = translations.get(lang, "")
                if args.json:
                    # For JSON, show a preview
                    try:
                        parsed = json.loads(translation)
                        # Extract text content for preview
                        text_content = []
                        def extract_text(node):
                            if isinstance(node, dict):
                                if node.get("type") == "text" and "text" in node:
                                    text_content.append(node["text"])
                                if "content" in node:
                                    for child in node["content"]:
                                        extract_text(child)
                        extract_text(parsed)
                        preview = " ".join(text_content)[:60]
                        print(f"{lang:3}: {preview}{'...' if len(' '.join(text_content)) > 60 else ''}")
                    except:
                        print(f"{lang:3}: {translation[:60]}{'...' if len(translation) > 60 else ''}")
                else:
                    print(f"{lang:3}: {translation}")
            print("=" * 80)
    
    finally:
        # Cleanup
        try:
            await secrets_manager.aclose()
        except Exception as e:
            logger.warning(f"Error closing SecretsManager: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTranslation interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.error(f"Translation failed: {e}", exc_info=True)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
