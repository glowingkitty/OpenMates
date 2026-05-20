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
from typing import Dict, List

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
    Translate a single string to multiple languages using intelligent batching.
    
    Strategy:
    - Short text (<3000 chars): translate to all 20 languages at once
    - Medium text (3000-8000 chars): translate in batches of 10 languages
    - Long text (>8000 chars): translate in batches of 5 languages
    
    Uses 20k output token limit for reliability with long translations.
    
    Returns a dictionary mapping language codes to translations.
    """
    if not text:
        return {lang: "" for lang in target_languages}
    
    from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
    
    # Determine optimal batch size based on content length
    content_length = len(text)
    
    # Calculate estimated output tokens per language (conservative estimate)
    # Plain text: 1 char ≈ 0.6 tokens on average (accounts for non-English languages)
    estimated_tokens_per_language = int(content_length * 0.6)
    
    # Determine batch size to stay under 18k tokens (20k with safety buffer)
    if estimated_tokens_per_language > 0:
        max_batch_size = max(1, min(20, int(18000 / estimated_tokens_per_language)))
    else:
        max_batch_size = 20
    
    # Apply content-length based limits for additional safety
    if content_length < 3000:
        batch_size = 20  # Short text: all languages at once
    elif content_length < 8000:
        batch_size = min(10, max_batch_size)  # Medium text: 10 languages max
    else:
        batch_size = min(5, max_batch_size)  # Long text: 5 languages max
    
    print(f"[Translation] Plain text length: {content_length} chars, estimated {estimated_tokens_per_language} tokens/lang, batch size: {batch_size}", file=sys.stderr)
    
    # Split target languages into batches
    all_translations = {}
    for batch_start in range(0, len(target_languages), batch_size):
        batch_langs = target_languages[batch_start:batch_start + batch_size]
        print(f"[Translation] Translating plain text to batch: {batch_langs}", file=sys.stderr)
        
        # Build function schema with output fields for this batch of languages
        properties = {}
        for lang in batch_langs:
            properties[lang] = {
                "type": "string",
                "description": f"Translation to {lang} language"
            }
        
        translation_tool = {
            "type": "function",
            "function": {
                "name": "return_translations",
                "description": (
                    "Return translations of the provided chat text to all target languages. "
                    "The text comes from a conversation between a human user and an AI assistant. "
                    "Preserve the original meaning, intent, and conversational style in each language. "
                    "Do not add explanations or commentary."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": batch_langs
                }
            }
        }
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional translator for chat conversations between a human user and an AI assistant. "
                    "The input may be either a user request or an assistant reply. "
                    "Translate the text to each requested language accurately and naturally, "
                    "preserving tone (requests should still sound like requests, answers like answers), "
                    "and keep all formatting, markdown and code snippets unchanged. "
                    "When translating into languages with formal and informal 'you' (such as German, French, or Spanish), "
                    "use the friendly, informal register that a person would naturally use when talking to a helpful chatbot "
                    "(for example, use 'du' instead of 'Sie' in German, 'tu' instead of 'vous' in French, "
                    "and 'tú' instead of 'usted' in Spanish), unless the source text is explicitly formal."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Translate the following chat message or passage to all target languages. "
                    "Only translate natural language text; keep markdown syntax and code blocks as they are:\n\n"
                    f"{text}"
                ),
            },
        ]
        
        try:
            response = await invoke_google_ai_studio_chat_completions(
                task_id=f"translate_batch_{hash(text) % 10000}_{batch_start}",
                model_id="gemini-3-flash-preview",
                messages=messages,
                secrets_manager=secrets_manager,
                tools=[translation_tool],
                tool_choice="required",
                temperature=0.3,
                max_tokens=20000,  # Increased to 20k for reliability
                stream=False
            )
            
            if response.success and response.tool_calls_made:
                # Extract translations from function call
                for tool_call in response.tool_calls_made:
                    if tool_call.function_name == "return_translations":
                        translations = tool_call.function_arguments_parsed
                        # Ensure all languages are present, use original text as fallback
                        for lang in batch_langs:
                            all_translations[lang] = translations.get(lang, text)
                            if all_translations[lang] != text:
                                print(f"[Translation] Successfully translated plain text to {lang}", file=sys.stderr)
            else:
                # Fallback: if function calling failed for this batch, use original text
                error_msg = response.error_message if hasattr(response, 'error_message') else 'No function call returned'
                logger.error(f"[Translation] Batch plain text translation failed for {batch_langs}: {error_msg}")
                for lang in batch_langs:
                    all_translations[lang] = text
                    
        except Exception as e:
            logger.error(f"[Translation] Error calling Gemini for batch {batch_langs}: {e}")
            for lang in batch_langs:
                all_translations[lang] = text
    
    return all_translations


async def translate_tiptap_json_batch(secrets_manager, tiptap_json: str, target_languages: List[str]) -> Dict[str, str]:
    """
    Translate Tiptap JSON content to multiple languages using intelligent batching.
    
    Strategy:
    - Short content (<2000 chars): translate to all 20 languages at once
    - Medium content (2000-6000 chars): translate in batches of 10 languages
    - Long content (6000-12000 chars): translate in batches of 5 languages
    - Very long content (>12000 chars): translate one language at a time
    
    Uses 20k output token limit for reliability with long translations.
    
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
    
    # Determine optimal batch size based on content length
    content_length = len(tiptap_json)
    
    # Calculate estimated output tokens per language (conservative estimate)
    # Tiptap JSON: 1 char ≈ 0.75 tokens on average (accounts for JSON overhead + non-English)
    estimated_tokens_per_language = int(content_length * 0.75)
    
    # Determine batch size to stay under 18k tokens (20k with safety buffer)
    if estimated_tokens_per_language > 0:
        max_batch_size = max(1, min(20, int(18000 / estimated_tokens_per_language)))
    else:
        max_batch_size = 20
    
    # Apply content-length based limits for additional safety
    if content_length < 2000:
        batch_size = 20  # Small content: all languages at once
    elif content_length < 6000:
        batch_size = min(10, max_batch_size)  # Medium content: 10 languages max
    elif content_length < 12000:
        batch_size = min(5, max_batch_size)  # Long content: 5 languages max
    else:
        batch_size = 1  # Very long content: one at a time
    
    print(f"[Translation] Tiptap JSON length: {content_length} chars, estimated {estimated_tokens_per_language} tokens/lang, batch size: {batch_size}", file=sys.stderr)
    
    # Split target languages into batches
    all_translations = {}
    for batch_start in range(0, len(target_languages), batch_size):
        batch_langs = target_languages[batch_start:batch_start + batch_size]
        print(f"[Translation] Translating Tiptap JSON to batch: {batch_langs}", file=sys.stderr)
        
        # Build function schema with output fields for this batch of languages
        properties = {}
        for lang in batch_langs:
            properties[lang] = {
                "type": "string",
                "description": f"Translated Tiptap JSON for {lang} language. Must be valid JSON with the same structure as the input, only 'text' values translated."
            }
        
        translation_tool = {
            "type": "function",
            "function": {
                "name": "return_translated_json",
                "description": (
                    "Return translated Tiptap JSON for all target languages. "
                    "The JSON represents content from a conversation between a human user and an AI assistant. "
                    "Translate only the 'text' values in the JSON structure. Keep all JSON structure, keys, "
                    "and non-text values (such as node types, attributes, and code blocks) exactly as they are. "
                    "Each output must be valid JSON."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": batch_langs
                }
            }
        }
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional translator for chat conversations between a human user and an AI assistant. "
                    "You are given Tiptap JSON that encodes rich-text chat content. "
                    "Translate only the 'text' fields to the requested languages, preserving meaning, intent, and tone. "
                    "Do NOT change the JSON structure, keys, node types, attributes, or code/markdown formatting. "
                    "Each translated value must be valid JSON when inserted back into the same structure. "
                    "When translating into languages with formal and informal 'you' (such as German, French, or Spanish), "
                    "use the friendly, informal register that a person would naturally use when talking to a helpful chatbot "
                    "(for example, use 'du' instead of 'Sie' in German, 'tu' instead of 'vous' in French, "
                    "and 'tú' instead of 'usted' in Spanish), unless the source text is explicitly formal."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Translate the following Tiptap JSON chat content to all target languages. "
                    "Only translate natural-language 'text' values; do not modify structure or code:\\n\\n"
                    f"{tiptap_json}"
                ),
            },
        ]
        
        try:
            response = await invoke_google_ai_studio_chat_completions(
                task_id=f"translate_json_batch_{hash(tiptap_json) % 10000}_{batch_start}",
                model_id="gemini-3-flash-preview",
                messages=messages,
                secrets_manager=secrets_manager,
                tools=[translation_tool],
                tool_choice="required",
                temperature=0.1, # Lower temperature for structural integrity
                max_tokens=20000,  # Increased to 20k for reliability with long content
                stream=False
            )
            
            if response.success and response.tool_calls_made:
                # Extract translations from function call
                for tool_call in response.tool_calls_made:
                    if tool_call.function_name == "return_translated_json":
                        translations = tool_call.function_arguments_parsed
                        # Validate each translation is valid JSON
                        for lang in batch_langs:
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
                                all_translations[lang] = translated_json
                                print(f"[Translation] Successfully translated Tiptap JSON to {lang}", file=sys.stderr)
                            except Exception as e:
                                logger.error(f"AI returned invalid JSON for translation to {lang}: {e}")
                                all_translations[lang] = tiptap_json
            else:
                # Fallback: if function calling failed for this batch, use original JSON
                error_msg = response.error_message if hasattr(response, 'error_message') else 'No function call returned'
                logger.error(f"[Translation] Batch JSON translation failed for {batch_langs}: {error_msg}")
                for lang in batch_langs:
                    all_translations[lang] = tiptap_json
                    
        except Exception as e:
            logger.error(f"[Translation] Error calling Gemini for batch {batch_langs}: {e}")
            for lang in batch_langs:
                all_translations[lang] = tiptap_json
    
    return all_translations


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
                    except Exception:
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
