import asyncio
import logging
import json

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions

logger = logging.getLogger(__name__)

TARGET_LANGUAGES = ["en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"]

@app.task(name="demo.translate_chat", bind=True, base=BaseServiceTask)
def translate_demo_chat_task(self, demo_chat_id: str, admin_user_id: str = None):
    """
    Celery task to translate a demo chat into all target languages.
    
    Args:
        demo_chat_id: UUID of the demo_chats entry
        admin_user_id: ID of the admin who approved it (for WebSocket notification)
    """
    task_id = self.request.id
    logger.info(f"Starting translation task for demo_chat_id: {demo_chat_id}, admin: {admin_user_id}, task_id: {task_id}")
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_translate_demo_chat(self, demo_chat_id, task_id, admin_user_id))
    except Exception as e:
        logger.error(f"Error in translate_demo_chat_task: {e}", exc_info=True)
        if loop:
            loop.run_until_complete(_update_demo_status(self, demo_chat_id, "translation_failed", admin_user_id))
        raise
    finally:
        if loop:
            loop.close()

async def _update_demo_status(task: BaseServiceTask, demo_chat_id: str, status: str, admin_user_id: str = None):
    """Update demo chat status by UUID."""
    try:
        await task.initialize_services()
        # demo_chat_id is already the UUID, can update directly
        await task.directus_service.update_item("demo_chats", demo_chat_id, {"status": status}, admin_required=True)
        
        # Notify admin via WebSocket if provided
        if admin_user_id:
            await task.publish_websocket_event(
                admin_user_id,
                "demo_chat_updated",
                {"user_id": admin_user_id, "demo_chat_id": demo_chat_id, "status": status}
            )
    except Exception as e:
        logger.error(f"Failed to update demo status to {status}: {e}")

async def _async_translate_demo_chat(task: BaseServiceTask, demo_chat_id: str, task_id: str, admin_user_id: str = None):
    """
    Translate a demo chat to all target languages.
    
    The demo chat was created by the client sending decrypted messages/embeds.
    We load the messages/embeds from demo_messages and demo_embeds tables (already encrypted with Vault).
    Decrypt them, translate to all languages, then store the translations.
    """
    await task.initialize_services()
    
    try:
        # 1. Fetch demo chat metadata by UUID
        demo_chats = await task.directus_service.get_items("demo_chats", {
            "filter": {"id": {"_eq": demo_chat_id}},
            "limit": 1
        }, admin_required=True)
        demo_chat = demo_chats[0] if demo_chats else None
        if not demo_chat:
            logger.error(f"Demo chat {demo_chat_id} not found")
            return

        # 2. Fetch original messages from demo_messages table (language='original')
        messages_params = {
            "filter": {
                "demo_chat_id": {"_eq": demo_chat_id},
                "language": {"_eq": "original"}
            },
            "sort": ["original_created_at"]  # Sort by original timestamp
        }
        demo_messages = await task.directus_service.get_items("demo_messages", messages_params)
        
        if not demo_messages:
            logger.error(f"No original messages found for demo chat {demo_chat_id}")
            demo_chat_item = await task.directus_service.demo_chat.get_demo_chat_by_id(demo_chat_id)
            if demo_chat_item and demo_chat_item.get("id"):
                await task.directus_service.update_item("demo_chats", demo_chat_item["id"], {
                    "status": "translation_failed"
                }, admin_required=True)
            return
        
        # 3. Get original messages (stored as cleartext)
        decrypted_messages = []
        for msg in demo_messages:
            content = msg.get("content", "")
            category = msg.get("category")
            model_name = msg.get("model_name")

            if content:
                decrypted_messages.append({
                    "role": msg["role"],
                    "content": content,
                    "category": category,
                    "model_name": model_name,
                    "original_created_at": msg["original_created_at"]
                })
        
        logger.info(f"Loaded and decrypted {len(decrypted_messages)} messages for demo chat {demo_chat_id}")
        
        # 4. Fetch original embeds from demo_embeds table
        embeds_params = {
            "filter": {
                "demo_chat_id": {"_eq": demo_chat_id},
                "language": {"_eq": "original"}
            },
            "sort": ["original_created_at"]
        }
        demo_embeds = await task.directus_service.get_items("demo_embeds", embeds_params)
        
        # 5. Get embeds (stored as cleartext)
        decrypted_embeds = []
        for emb in demo_embeds or []:
            content = emb.get("content", "")
            if content:
                decrypted_embeds.append({
                    "original_embed_id": emb["original_embed_id"],
                    "type": emb["type"],
                    "content": content,
                    "original_created_at": emb["original_created_at"]
                })
        
        logger.info(f"Loaded and decrypted {len(decrypted_embeds)} embeds for demo chat {demo_chat_id}")
        
        # 6. Get demo metadata (stored as cleartext)
        title = demo_chat.get("title")
        summary = demo_chat.get("summary")
        follow_up_suggestions = []

        if demo_chat.get("follow_up_suggestions"):
            try:
                follow_up_suggestions = json.loads(demo_chat["follow_up_suggestions"])
            except Exception:
                pass
        
        # 7. Translate and store per-language (translate + store immediately, resumable on restart)
        #
        # Architecture: We loop over each target language. For each language we:
        #   a) Check if translations already exist (resume support)
        #   b) Translate metadata (title, summary, follow-ups) to that language
        #   c) Translate all messages to that language
        #   d) Store everything for that language immediately
        # This means a crash/restart only loses work for the current language.
        logger.info(f"Translating demo {demo_chat_id} to {len(TARGET_LANGUAGES)} languages (per-language pipeline)...")

        total_languages = len(TARGET_LANGUAGES)

        # Pre-process system messages once: strip user_message_id for privacy
        # PRIVACY: The user_message_id references the original chat's message ID which:
        # 1. Leaks metadata from the original conversation
        # 2. Doesn't match any message ID in the demo chat (IDs are regenerated)
        # 3. The frontend uses position-based fallback for demo/shared chats
        sanitized_system_contents = {}  # index -> sanitized content
        for i, msg in enumerate(decrypted_messages):
            if msg.get("role") == "system":
                system_content = msg["content"]
                try:
                    parsed_system = json.loads(system_content)
                    if isinstance(parsed_system, dict) and "user_message_id" in parsed_system:
                        del parsed_system["user_message_id"]
                        system_content = json.dumps(parsed_system)
                        logger.info(f"Stripped user_message_id from system message {i+1} for privacy")
                except (json.JSONDecodeError, TypeError):
                    pass
                sanitized_system_contents[i] = system_content

        async def send_progress(current_language: str, message: str, progress_percentage: int):
            """Send a progress event with overall percentage."""
            # Clamp to 0-99 (100% is reserved for the final 'published' status update)
            progress_percentage = min(progress_percentage, 99)

            await task.publish_websocket_event(
                admin_user_id,
                "demo_chat_progress",
                {
                    "user_id": admin_user_id,
                    "demo_chat_id": demo_chat_id,
                    "stage": "translating",
                    "progress_percentage": progress_percentage,
                    "current_language": current_language,
                    "message": message
                }
            )

        # Check which languages already have translations (resume support)
        existing_translations = await task.directus_service.get_items("demo_chat_translations", {
            "filter": {"demo_chat_id": {"_eq": demo_chat_id}},
            "fields": ["language"]
        })
        already_translated = {t["language"] for t in (existing_translations or [])}
        if already_translated:
            logger.info(f"Resuming translation: {len(already_translated)} languages already done: {already_translated}")

        # Send initial progress (account for already-completed languages)
        completed_languages = len(already_translated)
        await send_progress(
            "",
            f"Starting translation ({completed_languages}/{total_languages} languages done)",
            int((completed_languages / total_languages) * 100) if total_languages > 0 else 0
        )

        for lang_idx, lang in enumerate(TARGET_LANGUAGES):
            # Skip languages that already have translations stored (resume support)
            if lang in already_translated:
                logger.info(f"Skipping {lang} ({lang_idx + 1}/{total_languages}) - already translated")
                completed_languages = lang_idx + 1
                continue

            logger.info(f"Translating to {lang} ({lang_idx + 1}/{total_languages})...")
            await send_progress(
                lang,
                f"Translating to {lang} ({lang_idx + 1}/{total_languages})",
                int((lang_idx / total_languages) * 100)
            )

            # a) Translate metadata for this language
            title_translation = await _translate_text_batch(task, title or "Demo Chat", [lang])
            summary_translation = await _translate_text_batch(task, summary or "", [lang])

            follow_up_translated = []
            if follow_up_suggestions:
                for suggestion in follow_up_suggestions:
                    suggestion_translation = await _translate_text_batch(task, suggestion, [lang])
                    follow_up_translated.append(suggestion_translation[lang])

            # b) Translate messages for this language
            translated_messages = []
            for i, msg in enumerate(decrypted_messages):
                if msg.get("role") == "system":
                    # Use pre-sanitized system content (not translated)
                    translated_messages.append(sanitized_system_contents[i])
                else:
                    msg_translation = await _translate_tiptap_json_batch(task, msg["content"], [lang])
                    translated_messages.append(msg_translation[lang])

            # c) Store translations immediately for this language
            translation_data = {
                "demo_chat_id": demo_chat_id,
                "language": lang,
                "title": title_translation[lang],
                "summary": summary_translation[lang],
                "follow_up_suggestions": json.dumps(follow_up_translated)
            }
            await task.directus_service.create_item("demo_chat_translations", translation_data)

            for i, translated_content in enumerate(translated_messages):
                message_data = {
                    "demo_chat_id": demo_chat_id,
                    "language": lang,
                    "role": decrypted_messages[i]["role"],
                    "content": translated_content,
                    "category": decrypted_messages[i].get("category"),
                    "model_name": decrypted_messages[i].get("model_name"),
                    "original_created_at": decrypted_messages[i]["original_created_at"]
                }
                await task.directus_service.create_item("demo_messages", message_data)

            # NOTE: Embeds are NOT duplicated per language - they remain stored once with
            # language="original" since embed content is not translated.

            completed_languages = lang_idx + 1
            logger.info(f"Completed and stored translations for {lang} ({completed_languages}/{total_languages})")
            await send_progress(
                lang,
                f"Completed {lang} ({completed_languages}/{total_languages})",
                int((completed_languages / total_languages) * 100)
            )

        # 8. Generate content hash for change detection
        import hashlib
        hash_content = ""
        for msg in decrypted_messages:
            hash_content += f"{msg['role']}:{msg['content']}\n"
        for emb in decrypted_embeds:
            hash_content += f"embed:{emb['original_embed_id']}:{emb['content']}\n"
        content_hash = hashlib.sha256(hash_content.encode('utf-8')).hexdigest()
        logger.info(f"Generated content hash for demo chat {demo_chat_id}: {content_hash[:16]}...")
        
        # 9. Update status to published
        if demo_chat and demo_chat.get("id"):
            from datetime import datetime, timezone
            await task.directus_service.update_item("demo_chats", demo_chat["id"], {
                "status": "published",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "content_hash": content_hash
            }, admin_required=True)
            
            # Notify admin via WebSocket if provided
            if admin_user_id:
                await task.publish_websocket_event(
                    admin_user_id,
                    "demo_chat_updated",
                    {"user_id": admin_user_id, "demo_chat_id": demo_chat_id, "status": "published"}
                )
        else:
            logger.warning(f"Could not find demo chat {demo_chat_id} to update status to published")
        
        # 10. Clear demo cache after publishing
        # IMPORTANT: This must happen AFTER all database updates are complete to ensure
        # the next cache population (on-demand or at API startup) fetches the complete data.
        # The cache will be re-populated on the next request with fresh data from the database.
        # NOTE: API startup also clears the cache before warming to prevent stale data issues.
        await task.directus_service.cache.clear_demo_chats_cache()
        logger.info(f"Cleared demo chats cache after publishing demo {demo_chat_id}")

        logger.info(f"Successfully published demo chat {demo_chat_id} in {total_languages} languages")

    finally:
        await task.cleanup_services()

async def _translate_text_batch(task: BaseServiceTask, text: str, target_languages: list, progress_callback=None) -> dict:
    """
    Translate a single string to multiple languages using intelligent batching.
    
    For short text (titles, summaries, follow-ups), translates to all languages at once.
    For longer text, automatically batches to stay within token limits.
    
    IMPORTANT: For markdown text with code blocks (like assistant messages with embeds),
    this function extracts code blocks, translates only the text portions, then reassembles.
    
    Uses 20k output token limit for reliability.
    
    Returns a dictionary mapping language codes to translations.
    """
    if not text:
        return {lang: "" for lang in target_languages}
    
    # Check if text contains markdown code blocks that should be preserved
    # Common pattern: ```json ... ``` or ``` ... ```
    import re
    code_block_pattern = r'(```(?:json|javascript|python|bash|sh|html|css|xml|yaml|yml|text|plain)?\n[\s\S]*?```)'
    code_blocks = re.findall(code_block_pattern, text)
    
    if code_blocks:
        # Text contains code blocks - use block-by-block translation
        logger.info(f"[Translation] Detected {len(code_blocks)} code blocks in markdown, using block extraction")
        return await _translate_markdown_with_code_blocks(task, text, target_languages, code_block_pattern)
    
    # No code blocks - proceed with normal batch translation
    content_length = len(text)
    
    # For plain text, estimate output tokens per language
    # Estimate: 1 char ≈ 0.6 tokens output per language (accounts for translation expansion)
    estimated_tokens_per_language = int(content_length * 0.6)
    
    # Calculate batch size to stay under 18k tokens (20k with safety buffer)
    # CRITICAL: Always respect the calculated max_batch_size
    if estimated_tokens_per_language > 0:
        max_batch_size = max(1, min(20, int(18000 / estimated_tokens_per_language)))
    else:
        max_batch_size = 20
    
    # Apply batch size limits based on content length, but ALWAYS respect max_batch_size
    if content_length < 500:
        batch_size = min(20, max_batch_size)  # Very short text
    elif content_length < 1500:
        batch_size = min(10, max_batch_size)  # Short text
    elif content_length < 4000:
        batch_size = min(5, max_batch_size)   # Medium text
    else:
        batch_size = min(3, max_batch_size)   # Long text
    
    logger.info(f"[Translation] Plain text length: {content_length} chars, estimated {estimated_tokens_per_language} tokens/lang, max_batch: {max_batch_size}, batch_size: {batch_size}")
    
    # Split target languages into batches
    all_translations = {}
    for batch_start in range(0, len(target_languages), batch_size):
        batch_langs = target_languages[batch_start:batch_start + batch_size]
        logger.info(f"[Translation] Translating plain text to batch: {batch_langs}")
        
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
                secrets_manager=task.secrets_manager,
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
                                logger.info(f"[Translation] Successfully translated plain text to {lang}")

                # Call progress callback after successful batch completion
                if progress_callback:
                    await progress_callback(batch_langs)

            else:
                # Fallback: if function calling failed for this batch, use original text
                error_msg = response.error_message if hasattr(response, 'error_message') else 'No function call returned'
                logger.error(f"[Translation] Batch plain text translation failed for {batch_langs}: {error_msg}")
                for lang in batch_langs:
                    all_translations[lang] = text

                # Still call progress callback even for failed batches
                if progress_callback:
                    await progress_callback(batch_langs)

        except Exception as e:
            logger.error(f"[Translation] Error calling Gemini for batch {batch_langs}: {e}")
            for lang in batch_langs:
                all_translations[lang] = text

            # Still call progress callback even for failed batches
            if progress_callback:
                await progress_callback(batch_langs)
    
    return all_translations


async def _translate_markdown_with_code_blocks(
    task: BaseServiceTask, 
    text: str, 
    target_languages: list,
    code_block_pattern: str
) -> dict:
    """
    Translate markdown text that contains code blocks.
    
    Strategy:
    1. Extract all code blocks and replace with placeholders
    2. Split remaining text into segments
    3. Extract leading/trailing whitespace from each segment (preserve formatting)
    4. Translate only the stripped text content
    5. Restore whitespace and reassemble with original code blocks
    
    This ensures:
    - Code blocks (especially JSON embed references) are never modified
    - Whitespace around code blocks is preserved (critical for proper rendering)
    """
    import re
    
    # Find all code blocks and their positions
    code_blocks = []
    placeholder_prefix = "<<<CODE_BLOCK_"
    placeholder_suffix = ">>>"
    
    def replace_code_block(match):
        idx = len(code_blocks)
        code_blocks.append(match.group(0))
        return f"{placeholder_prefix}{idx}{placeholder_suffix}"
    
    # Replace code blocks with placeholders
    text_with_placeholders = re.sub(code_block_pattern, replace_code_block, text)
    
    logger.info(f"[Translation] Extracted {len(code_blocks)} code blocks, translating remaining text")
    
    # Split text by placeholders to get translatable segments
    placeholder_pattern = r'(<<<CODE_BLOCK_\d+>>>)'
    segments = re.split(placeholder_pattern, text_with_placeholders)
    
    # Identify which segments are placeholders vs translatable text
    # IMPORTANT: Preserve leading/trailing whitespace for proper formatting around code blocks
    translatable_segments = []
    segment_indices = []
    segment_whitespace = []  # Store (leading_ws, trailing_ws) for each segment
    
    for i, segment in enumerate(segments):
        if not segment.startswith(placeholder_prefix):
            stripped = segment.strip()
            if stripped:  # Only translate non-empty segments
                # Extract leading and trailing whitespace
                # Use regex to capture leading whitespace
                leading_match = re.match(r'^(\s*)', segment)
                leading_ws = leading_match.group(1) if leading_match else ""
                # Extract trailing whitespace
                trailing_match = re.search(r'(\s*)$', segment)
                trailing_ws = trailing_match.group(1) if trailing_match else ""
                
                translatable_segments.append(stripped)  # Send only stripped text to LLM
                segment_indices.append(i)
                segment_whitespace.append((leading_ws, trailing_ws))
    
    logger.info(f"[Translation] Found {len(translatable_segments)} translatable segments (whitespace preserved)")
    
    if not translatable_segments:
        # No translatable text, just return original for all languages
        return {lang: text for lang in target_languages}
    
    # Translate all segments using the block translation function
    # Create text blocks with segment info (using stripped text)
    text_blocks = [{"text": seg, "index": idx} for seg, idx in zip(translatable_segments, segment_indices)]
    
    # Translate all text blocks
    block_translations = await _translate_text_blocks_batch(task, text_blocks, target_languages)
    
    # Reassemble for each language
    all_translations = {}
    for lang in target_languages:
        lang_texts = block_translations.get(lang, translatable_segments)
        
        # Reconstruct segments with translations, restoring whitespace
        translated_segments = list(segments)  # Copy original segments
        for i, (orig_idx, translated_text) in enumerate(zip(segment_indices, lang_texts)):
            # Restore the original leading/trailing whitespace
            leading_ws, trailing_ws = segment_whitespace[i]
            translated_segments[orig_idx] = f"{leading_ws}{translated_text}{trailing_ws}"
        
        # Replace placeholders back with original code blocks
        result = "".join(translated_segments)
        for idx, code_block in enumerate(code_blocks):
            result = result.replace(f"{placeholder_prefix}{idx}{placeholder_suffix}", code_block)
        
        all_translations[lang] = result
        
    return all_translations


async def _translate_text(task: BaseServiceTask, text: str, target_lang: str) -> str:
    """
    Translate a single string to one language (legacy function, kept for backward compatibility).
    For new code, use _translate_text_batch for efficiency.
    """
    if not text:
        return ""
    
    result = await _translate_text_batch(task, text, [target_lang])
    return result.get(target_lang, text)

def _contains_code_blocks(node: dict) -> bool:
    """
    Check if a Tiptap JSON node contains any code blocks.
    
    Messages with code blocks (like embed references) should always use
    block-by-block translation to ensure code content is never modified.
    
    Returns True if any codeBlock or code node is found.
    """
    if not isinstance(node, dict):
        return False
    
    node_type = node.get("type", "")
    
    # Check if this node is a code block
    if node_type in ("codeBlock", "code"):
        return True
    
    # Recurse into content array
    if "content" in node and isinstance(node["content"], list):
        for child in node["content"]:
            if _contains_code_blocks(child):
                return True
    
    return False


def _extract_text_blocks_from_tiptap(node: dict, blocks: list, path: list = None) -> None:
    """
    Recursively extract translatable text blocks from Tiptap JSON.
    
    Each block contains:
    - path: JSON path to the text node (e.g., ['content', 0, 'content', 1, 'text'])
    - text: The actual text content to translate
    - is_code: Whether this text is inside a code block (should not be translated)
    
    This function modifies the 'blocks' list in place.
    """
    if path is None:
        path = []
    
    if not isinstance(node, dict):
        return
    
    node_type = node.get("type", "")
    
    # Skip code blocks - these should not be translated
    if node_type in ("codeBlock", "code"):
        return
    
    # Check for text content in this node
    if "text" in node and isinstance(node["text"], str):
        text = node["text"].strip()
        # Only include non-empty text that isn't just whitespace or punctuation
        if text and len(text) > 0:
            blocks.append({
                "path": path + ["text"],
                "text": node["text"],  # Keep original with whitespace for accurate replacement
                "is_code": False
            })
    
    # Recurse into content array
    if "content" in node and isinstance(node["content"], list):
        for i, child in enumerate(node["content"]):
            _extract_text_blocks_from_tiptap(child, blocks, path + ["content", i])


def _rebuild_tiptap_with_translations(original_json: dict, translations: list) -> dict:
    """
    Rebuild Tiptap JSON with translated text blocks.
    
    Args:
        original_json: The original parsed Tiptap JSON
        translations: List of dicts with 'path' and 'translated_text' keys
    
    Returns:
        New Tiptap JSON dict with translated text
    """
    import copy
    result = copy.deepcopy(original_json)
    
    for item in translations:
        path = item["path"]
        translated_text = item["translated_text"]
        
        # Navigate to the parent node and set the text
        current = result
        for i, key in enumerate(path[:-1]):
            if isinstance(key, int):
                current = current[key]
            else:
                current = current.get(key, {})
        
        # Set the translated text
        final_key = path[-1]
        if isinstance(current, dict) and final_key in current:
            current[final_key] = translated_text
    
    return result


async def _translate_text_blocks_batch(task: BaseServiceTask, text_blocks: list, target_languages: list, progress_callback=None) -> dict:
    """
    Translate a list of text blocks to all target languages.
    
    For reliability, this translates all text blocks at once for each language batch.
    The LLM receives a simple list of strings to translate, which is much more reliable
    than asking it to produce valid Tiptap JSON.
    
    Returns a dict mapping language code to list of translated texts (same order as input).
    """
    if not text_blocks:
        return {lang: [] for lang in target_languages}
    
    # Extract just the text content (not paths)
    texts = [block["text"] for block in text_blocks]
    
    # Calculate batch size based on total text length
    total_text_length = sum(len(t) for t in texts)
    
    # Conservative batching: estimate output tokens per language
    # Output includes all text blocks translated, so multiply by number of blocks
    # Estimate: 0.6 tokens per char * total_length * languages must stay under 18k
    estimated_output_per_lang = int(total_text_length * 0.6)
    
    # Calculate max batch size to stay under 18k tokens output
    if estimated_output_per_lang > 0:
        max_batch_size = max(1, min(20, int(18000 / estimated_output_per_lang)))
    else:
        max_batch_size = 20
    
    # Apply conservative limits based on content length
    if total_text_length < 500:
        batch_size = min(20, max_batch_size)  # Very short
    elif total_text_length < 1500:
        batch_size = min(10, max_batch_size)  # Short
    elif total_text_length < 4000:
        batch_size = min(5, max_batch_size)   # Medium
    else:
        batch_size = min(3, max_batch_size)   # Long
    
    logger.info(f"[Translation] Translating {len(texts)} text blocks ({total_text_length} chars total), max_batch: {max_batch_size}, batch_size: {batch_size}")
    
    all_translations = {}
    
    for batch_start in range(0, len(target_languages), batch_size):
        batch_langs = target_languages[batch_start:batch_start + batch_size]
        logger.info(f"[Translation] Translating text blocks to batch: {batch_langs}")
        
        # Build function schema - each language gets an array of translated strings
        properties = {}
        for lang in batch_langs:
            properties[lang] = {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Array of {len(texts)} translated strings for {lang}. Must have exactly {len(texts)} items in the same order as input."
            }
        
        translation_tool = {
            "type": "function",
            "function": {
                "name": "return_translations",
                "description": (
                    f"Return translations of the {len(texts)} text strings to all target languages. "
                    "Each language should have an array of exactly the same number of translated strings, in the same order. "
                    "Preserve meaning, tone, and any markdown formatting within strings."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": batch_langs
                }
            }
        }
        
        # Format text list for the prompt
        text_list_formatted = "\n".join([f"{i+1}. {text}" for i, text in enumerate(texts)])
        
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional translator for chat conversations between a human user and an AI assistant. "
                    "Translate each text string to all requested languages accurately and naturally. "
                    "Preserve meaning, tone, and any markdown formatting (like **bold**, *italic*, links, etc.). "
                    "Keep technical terms, code snippets, and proper nouns unchanged. "
                    "Return exactly the same number of translated strings in the same order as the input. "
                    "When translating into languages with formal and informal 'you' (such as German, French, or Spanish), "
                    "use the friendly, informal register (e.g., 'du' in German, 'tu' in French, 'tú' in Spanish)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Translate the following {len(texts)} text strings to all target languages. "
                    f"Return exactly {len(texts)} translated strings per language, in the same order:\n\n"
                    f"{text_list_formatted}"
                ),
            },
        ]
        
        try:
            response = await invoke_google_ai_studio_chat_completions(
                task_id=f"translate_blocks_{hash(text_list_formatted) % 10000}_{batch_start}",
                model_id="gemini-3-flash-preview",
                messages=messages,
                secrets_manager=task.secrets_manager,
                tools=[translation_tool],
                tool_choice="required",
                temperature=0.3,
                max_tokens=20000,
                stream=False
            )
            
            if response.success and response.tool_calls_made:
                for tool_call in response.tool_calls_made:
                    if tool_call.function_name == "return_translations":
                        translations = tool_call.function_arguments_parsed
                        for lang in batch_langs:
                            lang_translations = translations.get(lang, [])
                            # Validate we got the right number of translations
                            if isinstance(lang_translations, list) and len(lang_translations) == len(texts):
                                all_translations[lang] = lang_translations
                                logger.info(f"[Translation] Successfully translated {len(texts)} blocks to {lang}")
                            else:
                                # Wrong number of translations - use originals
                                logger.warning(f"[Translation] Got {len(lang_translations) if isinstance(lang_translations, list) else 0} translations for {lang}, expected {len(texts)}. Using originals.")
                                all_translations[lang] = texts

                # Call progress callback after successful batch completion
                if progress_callback:
                    await progress_callback(batch_langs)

            else:
                error_msg = response.error_message if hasattr(response, 'error_message') else 'No function call returned'
                logger.error(f"[Translation] Text block translation failed for {batch_langs}: {error_msg}")
                for lang in batch_langs:
                    all_translations[lang] = texts

                # Still call progress callback even for failed batches
                if progress_callback:
                    await progress_callback(batch_langs)

        except Exception as e:
            logger.error(f"[Translation] Error translating text blocks for {batch_langs}: {e}")
            for lang in batch_langs:
                all_translations[lang] = texts

            # Still call progress callback even for failed batches
            if progress_callback:
                await progress_callback(batch_langs)
    
    return all_translations


async def _translate_tiptap_json_batch(task: BaseServiceTask, tiptap_json: str, target_languages: list, progress_callback=None) -> dict:
    """
    Translate Tiptap JSON content to multiple languages using text block extraction.
    
    Strategy for LONG CONTENT (>3000 chars) OR CONTENT WITH CODE BLOCKS:
    1. Extract individual text blocks from the Tiptap JSON structure
    2. Translate each text block as a simple string (much more reliable)
    3. Rebuild the Tiptap JSON with translated text blocks
    
    Strategy for SHORT CONTENT (<3000 chars) WITHOUT CODE BLOCKS:
    - Translate the entire JSON at once (original approach, works well for short content)
    
    This hybrid approach ensures:
    - Short content uses the fast single-call method
    - Long content uses the reliable block-by-block method
    - Content with code blocks (embeds, etc.) never has code content corrupted
    - Translation failures don't silently store English under other languages
    
    Returns a dictionary mapping language codes to translated JSON strings.
    """
    if not tiptap_json:
        return {lang: "" for lang in target_languages}
    
    # Parse JSON
    try:
        parsed_json = json.loads(tiptap_json)
    except Exception:
        # If not JSON, treat as plain text (markdown)
        return await _translate_text_batch(task, tiptap_json, target_languages, progress_callback)
    
    content_length = len(tiptap_json)
    
    # Check if content contains code blocks (e.g., embed references)
    # CRITICAL: Messages with code blocks must ALWAYS use block-by-block translation
    # to ensure code content (like embed JSON) is never modified by the LLM
    has_code_blocks = _contains_code_blocks(parsed_json)
    
    # Use block-by-block for:
    # 1. Long content (>3000 chars) - whole-JSON translation becomes unreliable
    # 2. Content with code blocks - prevents LLM from corrupting embed references
    if content_length > 3000 or has_code_blocks:
        reason = "code blocks present" if has_code_blocks else f"long content ({content_length} chars)"
        logger.info(f"[Translation] Using block-by-block translation: {reason}")
        
        # Extract translatable text blocks
        text_blocks = []
        _extract_text_blocks_from_tiptap(parsed_json, text_blocks)
        
        if not text_blocks:
            logger.warning("[Translation] No translatable text blocks found in Tiptap JSON")
            return {lang: tiptap_json for lang in target_languages}
        
        logger.info(f"[Translation] Extracted {len(text_blocks)} text blocks from Tiptap JSON")
        
        # Translate all text blocks
        block_translations = await _translate_text_blocks_batch(task, text_blocks, target_languages, progress_callback)
        
        # Rebuild Tiptap JSON for each language
        all_translations = {}
        for lang in target_languages:
            lang_texts = block_translations.get(lang, [block["text"] for block in text_blocks])
            
            # Build translation items with paths and translated text
            translation_items = []
            for i, block in enumerate(text_blocks):
                translation_items.append({
                    "path": block["path"],
                    "translated_text": lang_texts[i] if i < len(lang_texts) else block["text"]
                })
            
            # Rebuild the JSON with translations
            translated_json = _rebuild_tiptap_with_translations(parsed_json, translation_items)
            all_translations[lang] = json.dumps(translated_json, ensure_ascii=False)
            
        return all_translations
    
    # For short content, use the original whole-JSON translation approach
    # This is faster and works reliably for short content
    logger.info(f"[Translation] Using whole-JSON translation for short content ({content_length} chars)")
    
    # Determine optimal batch size based on content length
    estimated_tokens_per_language = int(content_length * 0.75)
    
    if estimated_tokens_per_language > 0:
        max_batch_size = max(1, min(20, int(18000 / estimated_tokens_per_language)))
    else:
        max_batch_size = 20
    
    # More conservative batch sizes
    if content_length < 1500:
        batch_size = 20  # Small content: all languages at once
    elif content_length < 2500:
        batch_size = min(10, max_batch_size)  # Medium content: 10 languages max
    else:
        batch_size = min(5, max_batch_size)  # Approaching threshold: 5 languages max
    
    logger.info(f"[Translation] Content length: {content_length} chars, batch size: {batch_size}")
    
    # Split target languages into batches
    all_translations = {}
    failed_languages = []  # Track languages that failed for retry
    
    for batch_start in range(0, len(target_languages), batch_size):
        batch_langs = target_languages[batch_start:batch_start + batch_size]
        logger.info(f"[Translation] Translating to batch: {batch_langs}")
        
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
                    "Only translate natural-language 'text' values; do not modify structure or code:\n\n"
                    f"{tiptap_json}"
                ),
            },
        ]
        
        try:
            response = await invoke_google_ai_studio_chat_completions(
                task_id=f"translate_json_batch_{hash(tiptap_json) % 10000}_{batch_start}",
                model_id="gemini-3-flash-preview",
                messages=messages,
                secrets_manager=task.secrets_manager,
                tools=[translation_tool],
                tool_choice="required",
                temperature=0.1,
                max_tokens=20000,
                stream=False
            )
            
            if response.success and response.tool_calls_made:
                for tool_call in response.tool_calls_made:
                    if tool_call.function_name == "return_translated_json":
                        translations = tool_call.function_arguments_parsed
                        for lang in batch_langs:
                            translated_json = translations.get(lang, "")
                            # Try to clean up markdown code blocks if AI included them
                            if isinstance(translated_json, str):
                                if translated_json.startswith("```json"):
                                    translated_json = translated_json.split("```json")[1].split("```")[0].strip()
                                elif translated_json.startswith("```"):
                                    translated_json = translated_json.split("```")[1].split("```")[0].strip()
                            
                            # Validate JSON
                            if translated_json:
                                try:
                                    json.loads(translated_json)
                                    all_translations[lang] = translated_json
                                    logger.info(f"[Translation] Successfully translated to {lang}")
                                except Exception as e:
                                    logger.warning(f"[Translation] Invalid JSON for {lang}, will retry with block method: {e}")
                                    failed_languages.append(lang)
                            else:
                                logger.warning(f"[Translation] Empty translation for {lang}, will retry with block method")
                                failed_languages.append(lang)
            else:
                error_msg = response.error_message if hasattr(response, 'error_message') else 'No function call returned'
                logger.warning(f"[Translation] Batch JSON translation failed for {batch_langs}, will retry: {error_msg}")
                failed_languages.extend(batch_langs)
                    
        except Exception as e:
            logger.warning(f"[Translation] Error translating batch {batch_langs}, will retry: {e}")
            failed_languages.extend(batch_langs)
    
    # Retry failed languages using the block-by-block approach
    if failed_languages:
        logger.info(f"[Translation] Retrying {len(failed_languages)} failed languages with block-by-block approach")
        
        # Extract text blocks
        text_blocks = []
        _extract_text_blocks_from_tiptap(parsed_json, text_blocks)
        
        if text_blocks:
            # Translate blocks for failed languages
            block_translations = await _translate_text_blocks_batch(task, text_blocks, failed_languages)
            
            # Rebuild JSON for each failed language
            for lang in failed_languages:
                lang_texts = block_translations.get(lang, [block["text"] for block in text_blocks])
                
                translation_items = []
                for i, block in enumerate(text_blocks):
                    translation_items.append({
                        "path": block["path"],
                        "translated_text": lang_texts[i] if i < len(lang_texts) else block["text"]
                    })
                
                translated_json = _rebuild_tiptap_with_translations(parsed_json, translation_items)
                all_translations[lang] = json.dumps(translated_json, ensure_ascii=False)
                logger.info(f"[Translation] Successfully translated to {lang} using block method")
        else:
            # No blocks to translate, use original
            for lang in failed_languages:
                all_translations[lang] = tiptap_json
    
    return all_translations


async def _translate_tiptap_json(task: BaseServiceTask, tiptap_json: str, target_lang: str) -> str:
    """
    Translate Tiptap JSON content to one language (legacy function, kept for backward compatibility).
    For new code, use _translate_tiptap_json_batch for efficiency.
    """
    if not tiptap_json:
        return ""
    
    result = await _translate_tiptap_json_batch(task, tiptap_json, [target_lang])
    return result.get(target_lang, tiptap_json)
