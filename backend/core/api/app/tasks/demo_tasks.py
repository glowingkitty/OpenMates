import asyncio
import hashlib
import logging
import json
import base64
from typing import Optional
from datetime import datetime, timezone

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions
from backend.core.api.app.utils.encryption import DEMO_CHATS_ENCRYPTION_KEY

logger = logging.getLogger(__name__)

TARGET_LANGUAGES = ["en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"]

@app.task(name="demo.translate_chat", bind=True, base=BaseServiceTask)
def translate_demo_chat_task(self, demo_id: str):
    """
    Celery task to translate a demo chat into all target languages.
    """
    task_id = self.request.id
    logger.info(f"Starting translation task for demo_id: {demo_id}, task_id: {task_id}")
    
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_translate_demo_chat(self, demo_id, task_id))
    except Exception as e:
        logger.error(f"Error in translate_demo_chat_task: {e}", exc_info=True)
        if loop:
            loop.run_until_complete(_update_demo_status(self, demo_id, "error"))
        raise
    finally:
        if loop:
            loop.close()

async def _update_demo_status(task: BaseServiceTask, demo_id: str, status: str):
    try:
        await task.initialize_services()
        await task.directus_service.update_item("demo_chats", demo_id, {"status": status})
    except Exception as e:
        logger.error(f"Failed to update demo status to {status}: {e}")

async def _async_translate_demo_chat(task: BaseServiceTask, demo_id: str, task_id: str):
    await task.initialize_services()
    
    try:
        # 1. Fetch demo chat metadata
        demo_chat = await task.directus_service.demo_chat.get_demo_chat_by_id(demo_id)
        if not demo_chat:
            logger.error(f"Demo chat {demo_id} not found")
            return

        original_chat_id = demo_chat["original_chat_id"]
        encrypted_key_blob = demo_chat["encrypted_key"]  # This is the encrypted share key blob
        
        if not encrypted_key_blob:
            logger.error(f"Demo chat {demo_id} has no encrypted_key - cannot decrypt messages")
            return
        
        # Decrypt the share key blob to get the actual chat encryption key
        # The blob is encrypted with AES-GCM using a key derived from the chat_id
        # When a user shares a chat with community, the frontend creates a share blob containing:
        # - chat_encryption_key: The raw 32-byte NaCl key (base64 encoded)
        # - generated_at: Unix timestamp
        # - duration_seconds: Expiration duration
        # - pwd: Password flag
        # This blob is encrypted with AES-GCM and stored in demo_chats.encrypted_key
        encryption_key_b64 = _decrypt_share_key_blob(encrypted_key_blob, original_chat_id)
        if not encryption_key_b64:
            logger.error(
                f"Failed to decrypt share key blob for demo chat {demo_id}. "
                f"This usually means the encrypted_key was corrupted or is not a valid share blob. "
                f"The user may need to re-share the chat with community. "
                f"encrypted_key length: {len(encrypted_key_blob) if encrypted_key_blob else 0}"
            )
            # Update status to indicate translation failed
            demo_chat_item = await task.directus_service.demo_chat.get_demo_chat_by_id(demo_id)
            if demo_chat_item and demo_chat_item.get("id"):
                item_id = demo_chat_item["id"]
                await task.directus_service.update_item("demo_chats", item_id, {
                    "status": "translation_failed"
                }, admin_required=True)
            return
        
        logger.info(f"Successfully extracted encryption key for demo chat {demo_id}")
        
        # 2. Fetch and decrypt original messages and embeds
        # We need ALL fields for messages to recreate them correctly
        messages = await task.directus_service.chat.get_all_messages_for_chat(original_chat_id, decrypt_content=False)
        # Fetch embeds for the chat
        hashed_chat_id = hashlib.sha256(original_chat_id.encode()).hexdigest()
        embeds = await task.directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)

        decrypted_messages = []
        for msg in messages:
            # Parse JSON string if needed
            if isinstance(msg, str):
                try:
                    msg = json.loads(msg)
                except Exception:
                    logger.error(f"Failed to parse message JSON: {msg}")
                    continue

            content = _decrypt_client_side(msg.get("encrypted_content", ""), encryption_key_b64)
            if content:
                decrypted_messages.append({
                    "role": msg["role"],
                    "content": content,
                    "order": msg.get("created_at", 0) # Use created_at for order if message_order is not available
                })
        
        # Sort messages by order
        decrypted_messages.sort(key=lambda x: x["order"])
        for i, msg in enumerate(decrypted_messages):
            msg["order"] = i

        decrypted_embeds = []
        for emb in embeds:
            # Parse JSON string if needed
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except Exception:
                    logger.error(f"Failed to parse embed JSON: {emb}")
                    continue

            content = _decrypt_client_side(emb.get("encrypted_content", ""), encryption_key_b64)
            if content:
                decrypted_embeds.append({
                    "embed_id": emb["embed_id"],
                    "content": content,
                    "type": _decrypt_client_side(emb.get("encrypted_type", ""), encryption_key_b64) or "unknown",
                    "order": emb.get("created_at", 0)
                })

        # 3. Translate using batch translation (one API call per text instead of per language)
        logger.info(f"Translating demo {demo_id} to {len(TARGET_LANGUAGES)} languages using batch translation...")
        
        # Translate metadata in batches
        title_translations = await _translate_text_batch(task, demo_chat.get("title", "Demo Chat"), TARGET_LANGUAGES)
        summary_translations = await _translate_text_batch(task, demo_chat.get("summary", ""), TARGET_LANGUAGES)
        
        # Translate follow-up suggestions in batches
        follow_up = demo_chat.get("follow_up_suggestions")
        follow_up_translations_by_lang = {lang: [] for lang in TARGET_LANGUAGES}
        if follow_up:
            if isinstance(follow_up, str):
                try:
                    follow_up = json.loads(follow_up)
                except Exception:
                    follow_up = []
            if isinstance(follow_up, list):
                for suggestion in follow_up:
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
        
        # 4. Store translations for each language
        for lang in TARGET_LANGUAGES:
            logger.info(f"Storing translations for {lang}...")
            
            # Store metadata translation
            translation_data = {
                "demo_id": demo_id,
                "language": lang,
                "title": title_translations[lang],
                "summary": summary_translations[lang],
                "follow_up_suggestions": follow_up_translations_by_lang[lang]
            }
            await task.directus_service.create_item("demo_chat_translations", translation_data)

            # Store translated messages
            for i, translated_content in enumerate(message_translations_by_lang[lang]):
                # Encrypt server-side
                encrypted_content, _ = await task.encryption_service.encrypt(
                    translated_content, 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                message_data = {
                    "demo_id": demo_id,
                    "language": lang,
                    "role": decrypted_messages[i]["role"],
                    "encrypted_content": encrypted_content,
                    "message_order": i
                }
                await task.directus_service.create_item("demo_messages", message_data)

            # Store embeds (no translation for now as per user request)
            for i, emb in enumerate(decrypted_embeds):
                # Encrypt server-side
                encrypted_content, _ = await task.encryption_service.encrypt(
                    emb["content"], 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                embed_data = {
                    "demo_id": demo_id,
                    "language": lang,
                    "embed_id": emb["embed_id"],
                    "encrypted_content": encrypted_content,
                    "type": emb["type"],
                    "embed_order": i
                }
                await task.directus_service.create_item("demo_embeds", embed_data)

        # 4. Generate content hash for change detection
        # The hash is computed from all message contents and embed contents
        # This allows clients to detect when demo content has changed
        hash_content = ""
        for msg in decrypted_messages:
            hash_content += f"{msg['role']}:{msg['content']}\n"
        for emb in decrypted_embeds:
            hash_content += f"embed:{emb['embed_id']}:{emb['content']}\n"
        content_hash = hashlib.sha256(hash_content.encode('utf-8')).hexdigest()
        logger.info(f"Generated content hash for demo chat {demo_id}: {content_hash[:16]}...")
        
        # 5. Update status to published (requires admin privileges)
        # First get the demo chat to find its actual Directus item ID
        demo_chat_item = await task.directus_service.demo_chat.get_demo_chat_by_id(demo_id)
        if demo_chat_item and demo_chat_item.get("id"):
            item_id = demo_chat_item["id"]  # This is the Directus item ID (UUID)
            await task.directus_service.update_item("demo_chats", item_id, {
                "status": "published",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "content_hash": content_hash
            }, admin_required=True)
        else:
            logger.warning(f"Could not find demo chat {demo_id} to update status to published")
        
        # 5. Clear and reload cache
        await task.directus_service.cache.clear_demo_chats_cache()
        # Trigger warming (optional, depends on if we have a warming task)
        # await task.directus_service.cache.warm_demo_chats_cache()

        logger.info(f"Successfully published demo chat {demo_id} in {len(TARGET_LANGUAGES)} languages")

    finally:
        await task.cleanup_services()

def _decrypt_share_key_blob(encrypted_blob: str, chat_id: str) -> Optional[str]:
    """
    Decrypt a share key blob to extract the raw chat encryption key.
    
    The share key blob is encrypted with AES-GCM using a key derived from the chat_id.
    This mirrors the frontend's decryptShareKeyBlob function.
    
    Structure:
    - Key derivation: PBKDF2 with chat_id, salt="openmates-share-v1", 100000 iterations, SHA-256
    - Encryption: AES-GCM with 12-byte IV prepended to ciphertext
    - Blob format: URL-encoded params (chat_encryption_key, generated_at, duration_seconds, pwd)
    
    Args:
        encrypted_blob: Base64 URL-safe encoded encrypted blob
        chat_id: The original chat ID used to derive the decryption key
        
    Returns:
        The raw chat encryption key (base64 encoded) or None if decryption fails
    """
    if not encrypted_blob or not chat_id:
        return None
    
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from urllib.parse import parse_qs
        
        # 1. Decode the base64 URL-safe blob
        # Convert URL-safe base64 to standard base64
        base64_standard = encrypted_blob.replace('-', '+').replace('_', '/')
        # Add padding if needed
        padding = 4 - (len(base64_standard) % 4)
        if padding != 4:
            base64_standard += '=' * padding
        
        combined = base64.b64decode(base64_standard)
        
        # 2. Extract IV (first 12 bytes) and ciphertext
        if len(combined) <= 12:
            logger.error(f"Share key blob too short: {len(combined)} bytes")
            return None
        
        iv = combined[:12]
        ciphertext = combined[12:]
        
        # 3. Derive the decryption key using PBKDF2
        salt = b"openmates-share-v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits for AES-GCM
            salt=salt,
            iterations=100000,
        )
        derived_key = kdf.derive(chat_id.encode('utf-8'))
        
        # 4. Decrypt with AES-GCM
        aesgcm = AESGCM(derived_key)
        decrypted_bytes = aesgcm.decrypt(iv, ciphertext, None)
        serialized = decrypted_bytes.decode('utf-8')
        
        # 5. Parse URL-encoded parameters to extract chat_encryption_key
        # Format: chat_encryption_key=...&generated_at=...&duration_seconds=...&pwd=0|1
        params = parse_qs(serialized)
        
        chat_encryption_key = params.get('chat_encryption_key', [None])[0]
        if not chat_encryption_key:
            logger.error("No chat_encryption_key found in decrypted share blob")
            return None
        
        logger.info(f"Successfully decrypted share key blob for chat {chat_id[:8]}...")
        return chat_encryption_key
        
    except Exception as e:
        logger.error(f"Failed to decrypt share key blob: {e}", exc_info=True)
        return None


def _decrypt_client_side(ciphertext_b64: str, key_b64: str) -> Optional[str]:
    """Decrypt content encrypted with TweetNaCl (XSalsa20-Poly1305) on the client side."""
    if not ciphertext_b64:
        return ""
    try:
        import nacl.secret
        import nacl.utils
        key = base64.b64decode(key_b64)
        combined = base64.b64decode(ciphertext_b64)
        if len(combined) <= 24:
            return None
        nonce = combined[:24]
        ciphertext = combined[24:]
        box = nacl.secret.SecretBox(key)
        return box.decrypt(ciphertext, nonce).decode('utf-8')
    except Exception as e:
        logger.error(f"Client-side decryption failed: {e}")
        return None

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
