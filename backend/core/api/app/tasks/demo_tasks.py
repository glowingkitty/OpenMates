import asyncio
import logging
import json

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY

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
                {"demo_chat_id": demo_chat_id, "status": status}
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
        
        # 3. Decrypt original messages
        decrypted_messages = []
        for msg in demo_messages:
            decrypted_content = await task.encryption_service.decrypt(
                msg["encrypted_content"],
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            
            decrypted_category = None
            if msg.get("encrypted_category"):
                decrypted_category = await task.encryption_service.decrypt(
                    msg["encrypted_category"],
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
            if decrypted_content:
                decrypted_messages.append({
                    "role": msg["role"],
                    "content": decrypted_content,
                    "category": decrypted_category,
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
        
        # 5. Decrypt embeds
        decrypted_embeds = []
        for emb in demo_embeds or []:
            decrypted_content = await task.encryption_service.decrypt(
                emb["encrypted_content"],
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            if decrypted_content:
                decrypted_embeds.append({
                    "original_embed_id": emb["original_embed_id"],
                    "type": emb["type"],
                    "content": decrypted_content,
                    "original_created_at": emb["original_created_at"]
                })
        
        logger.info(f"Loaded and decrypted {len(decrypted_embeds)} embeds for demo chat {demo_chat_id}")
        
        # 6. Decrypt demo metadata
        title = None
        summary = None
        follow_up_suggestions = []
        
        if demo_chat.get("encrypted_title"):
            title = await task.encryption_service.decrypt(demo_chat["encrypted_title"], key_name=DEMO_CHATS_ENCRYPTION_KEY)
        if demo_chat.get("encrypted_summary"):
            summary = await task.encryption_service.decrypt(demo_chat["encrypted_summary"], key_name=DEMO_CHATS_ENCRYPTION_KEY)
        if demo_chat.get("encrypted_follow_up_suggestions"):
            import json
            follow_up_json = await task.encryption_service.decrypt(demo_chat["encrypted_follow_up_suggestions"], key_name=DEMO_CHATS_ENCRYPTION_KEY)
            if follow_up_json:
                try:
                    follow_up_suggestions = json.loads(follow_up_json)
                except Exception:
                    pass
        
        # 7. Translate metadata and messages using batch translation
        logger.info(f"Translating demo {demo_chat_id} to {len(TARGET_LANGUAGES)} languages using batch translation...")
        
        # Translate metadata in batches
        title_translations = await _translate_text_batch(task, title or "Demo Chat", TARGET_LANGUAGES)
        summary_translations = await _translate_text_batch(task, summary or "", TARGET_LANGUAGES)
        
        # Translate follow-up suggestions in batches
        follow_up_translations_by_lang = {lang: [] for lang in TARGET_LANGUAGES}
        if follow_up_suggestions:
            for suggestion in follow_up_suggestions:
                suggestion_translations = await _translate_text_batch(task, suggestion, TARGET_LANGUAGES)
                for lang in TARGET_LANGUAGES:
                    follow_up_translations_by_lang[lang].append(suggestion_translations[lang])
        
        # Translate messages in batches
        message_translations_by_lang = {lang: [] for lang in TARGET_LANGUAGES}
        for i, msg in enumerate(decrypted_messages):
            logger.info(f"Translating message {i+1}/{len(decrypted_messages)} to all languages...")
            msg_translations = await _translate_tiptap_json_batch(task, msg["content"], TARGET_LANGUAGES)
            for lang in TARGET_LANGUAGES:
                message_translations_by_lang[lang].append(msg_translations[lang])
        
        # 8. Store translations for each language
        for lang in TARGET_LANGUAGES:
            logger.info(f"Storing translations for {lang}...")
            
            # Store metadata translation (Vault-encrypted)
            encrypted_title, _ = await task.encryption_service.encrypt(
                title_translations[lang], 
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            encrypted_summary, _ = await task.encryption_service.encrypt(
                summary_translations[lang], 
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            
            import json
            encrypted_follow_up, _ = await task.encryption_service.encrypt(
                json.dumps(follow_up_translations_by_lang[lang]), 
                key_name=DEMO_CHATS_ENCRYPTION_KEY
            )
            
            translation_data = {
                "demo_chat_id": demo_chat_id,
                "language": lang,
                "encrypted_title": encrypted_title,
                "encrypted_summary": encrypted_summary,
                "encrypted_follow_up_suggestions": encrypted_follow_up
            }
            await task.directus_service.create_item("demo_chat_translations", translation_data)

            # Store translated messages
            for i, translated_content in enumerate(message_translations_by_lang[lang]):
                # Encrypt translated content and category
                encrypted_content, _ = await task.encryption_service.encrypt(
                    translated_content, 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                encrypted_category = None
                category = decrypted_messages[i].get("category")
                if category:
                    encrypted_category, _ = await task.encryption_service.encrypt(
                        category,
                        key_name=DEMO_CHATS_ENCRYPTION_KEY
                    )
                
                message_data = {
                    "demo_chat_id": demo_chat_id,
                    "language": lang,
                    "role": decrypted_messages[i]["role"],
                    "encrypted_content": encrypted_content,
                    "encrypted_category": encrypted_category,
                    "original_created_at": decrypted_messages[i]["original_created_at"]
                }
                await task.directus_service.create_item("demo_messages", message_data)

            # Store embeds (no translation for now, just copy with language marker)
            for emb in decrypted_embeds:
                # Encrypt embed content with Vault
                encrypted_content, _ = await task.encryption_service.encrypt(
                    emb["content"], 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                embed_data = {
                    "demo_chat_id": demo_chat_id,
                    "language": lang,
                    "original_embed_id": emb["original_embed_id"],
                    "encrypted_content": encrypted_content,
                    "type": emb["type"],
                    "original_created_at": emb["original_created_at"]
                }
                await task.directus_service.create_item("demo_embeds", embed_data)

        # 9. Generate content hash for change detection
        hash_content = ""
        for msg in decrypted_messages:
            hash_content += f"{msg['role']}:{msg['content']}\n"
        for emb in decrypted_embeds:
            hash_content += f"embed:{emb['original_embed_id']}:{emb['content']}\n"
        import hashlib
        content_hash = hashlib.sha256(hash_content.encode('utf-8')).hexdigest()
        logger.info(f"Generated content hash for demo chat {demo_chat_id}: {content_hash[:16]}...")
        
        # 10. Update status to published
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
                    {"demo_chat_id": demo_chat_id, "status": "published"}
                )
        else:
            logger.warning(f"Could not find demo chat {demo_chat_id} to update status to published")
        
        # 11. Clear and reload cache
        await task.directus_service.cache.clear_demo_chats_cache()

        logger.info(f"Successfully published demo chat {demo_chat_id} in {len(TARGET_LANGUAGES)} languages")

    finally:
        await task.cleanup_services()

async def _translate_text_batch(task: BaseServiceTask, text: str, target_languages: list) -> dict:
    """
    Translate a single string to multiple languages in one API call using function calling.
    Returns a dictionary mapping language codes to translations.
    """
    if not text:
        return {lang: "" for lang in target_languages}
    
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
            secrets_manager=task.secrets_manager,
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


async def _translate_text(task: BaseServiceTask, text: str, target_lang: str) -> str:
    """
    Translate a single string to one language (legacy function, kept for backward compatibility).
    For new code, use _translate_text_batch for efficiency.
    """
    if not text:
        return ""
    
    result = await _translate_text_batch(task, text, [target_lang])
    return result.get(target_lang, text)

async def _translate_tiptap_json_batch(task: BaseServiceTask, tiptap_json: str, target_languages: list) -> dict:
    """
    Translate Tiptap JSON content to multiple languages in one API call using function calling.
    Returns a dictionary mapping language codes to translated JSON strings.
    """
    if not tiptap_json:
        return {lang: "" for lang in target_languages}
    
    # Simple check if it's actually JSON
    try:
        json.loads(tiptap_json)
    except Exception:
        # If not JSON, treat as plain text
        return await _translate_text_batch(task, tiptap_json, target_languages)
    
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
            secrets_manager=task.secrets_manager,
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


async def _translate_tiptap_json(task: BaseServiceTask, tiptap_json: str, target_lang: str) -> str:
    """
    Translate Tiptap JSON content to one language (legacy function, kept for backward compatibility).
    For new code, use _translate_tiptap_json_batch for efficiency.
    """
    if not tiptap_json:
        return ""
    
    result = await _translate_tiptap_json_batch(task, tiptap_json, [target_lang])
    return result.get(target_lang, tiptap_json)
