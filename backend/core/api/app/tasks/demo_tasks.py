import asyncio
import logging
import json
import base64
from typing import List, Dict, Any, Optional
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
        encryption_key_b64 = demo_chat["encrypted_key"] # Original plaintext chat key (base64)
        
        # 2. Fetch and decrypt original messages and embeds
        # We need ALL fields for messages to recreate them correctly
        messages = await task.directus_service.chat.get_all_messages_for_chat(original_chat_id, decrypt_content=False)
        # Fetch embeds for the chat
        hashed_chat_id = task.directus_service.chat._hash_id(original_chat_id)
        embeds = await task.directus_service.embed.get_embeds_by_hashed_chat_id(hashed_chat_id)

        decrypted_messages = []
        for msg in messages:
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
            content = _decrypt_client_side(emb.get("encrypted_content", ""), encryption_key_b64)
            if content:
                decrypted_embeds.append({
                    "embed_id": emb["embed_id"],
                    "content": content,
                    "type": _decrypt_client_side(emb.get("encrypted_type", ""), encryption_key_b64) or "unknown",
                    "order": emb.get("created_at", 0)
                })

        # 3. Translate for each language
        for lang in TARGET_LANGUAGES:
            logger.info(f"Translating demo {demo_id} to {lang}...")
            
            # Translate metadata
            translated_title = await _translate_text(task, demo_chat.get("title", "Demo Chat"), lang)
            translated_summary = await _translate_text(task, demo_chat.get("summary", ""), lang)
            
            follow_up = demo_chat.get("follow_up_suggestions")
            translated_follow_up = []
            if follow_up:
                if isinstance(follow_up, str):
                    try:
                        follow_up = json.loads(follow_up)
                    except:
                        follow_up = []
                if isinstance(follow_up, list):
                    for suggestion in follow_up:
                        translated_follow_up.append(await _translate_text(task, suggestion, lang))

            # Store translation
            translation_data = {
                "demo_id": demo_id,
                "language": lang,
                "title": translated_title,
                "summary": translated_summary,
                "follow_up_suggestions": translated_follow_up
            }
            await task.directus_service.create_item("demo_chat_translations", translation_data)

            # Translate and store messages
            for i, msg in enumerate(decrypted_messages):
                translated_content = await _translate_tiptap_json(task, msg["content"], lang)
                
                # Encrypt server-side
                encrypted_content, _ = await task.encryption_service.encrypt(
                    translated_content, 
                    key_name=DEMO_CHATS_ENCRYPTION_KEY
                )
                
                message_data = {
                    "demo_id": demo_id,
                    "language": lang,
                    "role": msg["role"],
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

        # 4. Update status to published
        await task.directus_service.update_item("demo_chats", demo_id, {
            "status": "published",
            "approved_at": datetime.now(timezone.utc).isoformat()
        })
        
        # 5. Clear and reload cache
        await task.directus_service.cache.clear_demo_chats_cache()
        # Trigger warming (optional, depends on if we have a warming task)
        # await task.directus_service.cache.warm_demo_chats_cache()

        logger.info(f"Successfully published demo chat {demo_id} in {len(TARGET_LANGUAGES)} languages")

    finally:
        await task.cleanup_services()

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

async def _translate_text(task: BaseServiceTask, text: str, target_lang: str) -> str:
    """Translate a single string using Gemini 3 Flash."""
    if not text:
        return ""
    
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

async def _translate_tiptap_json(task: BaseServiceTask, tiptap_json: str, target_lang: str) -> str:
    """Translate Tiptap JSON content using Gemini 3 Flash."""
    if not tiptap_json:
        return ""
    
    # Simple check if it's actually JSON
    try:
        json.loads(tiptap_json)
    except:
        return await _translate_text(task, tiptap_json, target_lang)

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
            except:
                logger.error(f"AI returned invalid JSON for translation to {target_lang}")
                return tiptap_json
        else:
            logger.error(f"JSON translation failed for {target_lang}: {response.error_message}")
            return tiptap_json
    except Exception as e:
        logger.error(f"Error calling Gemini for JSON translation: {e}")
        return tiptap_json
