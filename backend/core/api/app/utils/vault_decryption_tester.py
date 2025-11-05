"""
VAULT DECRYPTION TESTER FOR DEBUG PURPOSES ONLY

This utility attempts to decrypt cached messages using the Vault encryption key.
This is useful for diagnosing whether:
1. Messages in sync cache are accidentally vault-encrypted (they shouldn't be)
2. Messages in AI cache are properly vault-encrypted (they should be)
3. Messages in Directus are accidentally vault-encrypted (they shouldn't be)

USAGE:
  from backend.core.api.app.utils.vault_decryption_tester import VaultDecryptionTester

  tester = VaultDecryptionTester(encryption_service, cache_service)
  result = await tester.test_message_decryption(
      user_id="user_id",
      chat_id="chat_id",
      cache_type="sync",  # or "ai"
      message_index=0
  )

NOTE: THIS IS FOR DEBUGGING ONLY
- Remove this file and all references once the bug is fixed
- This adds performance overhead
- This exposes encryption key details in logs
- This violates the intent of the encryption scheme (testing if wrong keys were used)

It's acceptable to keep this for now because:
✅ It's in a dev-only utility
✅ It only attempts to decrypt (read-only)
✅ It helps understand the encryption violation
✅ It will be removed once bug is fixed
"""

import logging
import json
import base64
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class VaultDecryptionTester:
    """
    Tests whether cached messages can be decrypted with Vault keys.

    This is a diagnostic tool to identify encryption violations.
    """

    def __init__(self, encryption_service, cache_service):
        self.encryption_service = encryption_service
        self.cache_service = cache_service

    async def test_message_decryption(
        self,
        user_id: str,
        chat_id: str,
        cache_type: str,  # "sync" or "ai"
        message_index: int = 0,
        vault_key_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Test whether a specific cached message can be decrypted with Vault key.

        Args:
            user_id: User ID
            chat_id: Chat ID
            cache_type: "sync" or "ai"
            message_index: Which message to test (0 = first/newest)
            vault_key_id: Optional vault key ID. If not provided, fetches from cache.

        Returns:
            {
                "cache_type": str,
                "message_index": int,
                "encrypted_format": str,  # "vault", "client", or "unknown"
                "vault_decryption_possible": bool,
                "vault_decryption_result": str or None,
                "⚠️_interpretation": str,
                "recommendation": str
            }
        """
        result = {
            "cache_type": cache_type,
            "message_index": message_index,
            "test_timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id[:8] + "...",
            "chat_id": chat_id[:8] + "...",
            "vault_decryption_possible": False,
            "vault_decryption_result": None,
            "encrypted_format": "unknown",
            "⚠️_interpretation": None,
            "recommendation": None,
            "detailed_analysis": {}
        }

        try:
            # Step 1: Get vault key ID if not provided
            if not vault_key_id:
                vault_key_id = await self.cache_service.get_user_vault_key_id(user_id)
                if not vault_key_id:
                    result["⚠️_interpretation"] = "Could not retrieve vault_key_id for user"
                    return result

            result["vault_key_id_length"] = len(vault_key_id)

            # Step 2: Retrieve message from cache
            if cache_type == "sync":
                messages = await self.cache_service.get_sync_messages_history(user_id, chat_id)
            elif cache_type == "ai":
                messages = await self.cache_service.get_ai_messages_history(user_id, chat_id)
            else:
                result["⚠️_interpretation"] = f"Unknown cache_type: {cache_type}"
                return result

            if not messages or len(messages) <= message_index:
                result["⚠️_interpretation"] = f"Message not found in {cache_type} cache at index {message_index}"
                return result

            # Step 3: Parse message JSON
            message_str = messages[message_index]
            try:
                message_obj = json.loads(message_str)
            except json.JSONDecodeError:
                result["⚠️_interpretation"] = "Message is not valid JSON"
                return result

            encrypted_content = message_obj.get("encrypted_content", "")

            # Step 4: Detect encryption format
            if encrypted_content.startswith("vault:v"):
                result["encrypted_format"] = "vault"
            elif encrypted_content.startswith("base64:") or all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in encrypted_content if c not in ['\n', '\r']):
                result["encrypted_format"] = "client"
            else:
                result["encrypted_format"] = "unknown"

            result["encrypted_content_length"] = len(encrypted_content)
            result["encrypted_content_preview"] = encrypted_content[:50] + "..."

            # Step 5: Attempt Vault decryption
            logger.info(f"🧪 VAULT DECRYPTION TEST: Attempting to decrypt {cache_type} cache message for user {user_id[:8]}... with vault key")

            try:
                decrypted = await self.encryption_service.decrypt_with_user_key(
                    encrypted_content,
                    vault_key_id
                )

                if decrypted:
                    result["vault_decryption_possible"] = True
                    result["vault_decryption_result"] = decrypted[:100] + "..." if len(decrypted) > 100 else decrypted
                    result["decryption_success"] = True

                    # Interpretation
                    if cache_type == "sync":
                        result["⚠️_interpretation"] = "❌ CRITICAL: Sync cache message is vault-encrypted! This is WRONG."
                        result["⚠️_issue"] = "Messages in sync cache should be client-encrypted (encryption_key_chat), not server-encrypted (vault key)"
                        result["recommendation"] = (
                            "1. Check cache warming code (user_cache_tasks.py)\n"
                            "2. Verify messages from Directus are not being re-encrypted\n"
                            "3. Check if wrong encryption key is being used somewhere"
                        )
                    elif cache_type == "ai":
                        result["✅_interpretation"] = "✅ OK: AI cache message is vault-encrypted. This is CORRECT."
                        result["recommendation"] = "No action needed for AI cache"

                else:
                    result["vault_decryption_possible"] = False
                    result["decryption_success"] = False
                    result["⚠️_interpretation"] = (
                        f"Vault decryption returned None. "
                        f"This means the message is likely NOT vault-encrypted (probably client-encrypted, which is expected for sync cache)"
                    )

            except Exception as e:
                result["vault_decryption_possible"] = False
                result["vault_decryption_error"] = str(e)
                result["⚠️_interpretation"] = (
                    f"Vault decryption failed with error: {e}. "
                    f"This likely means the message is client-encrypted (expected for sync cache)"
                )

            # Step 6: Interpretation logic
            if result["encrypted_format"] == "vault" and result["vault_decryption_possible"]:
                if cache_type == "sync":
                    result["severity"] = "CRITICAL"
                    result["issue_category"] = "encryption_violation"
                elif cache_type == "ai":
                    result["severity"] = "OK"
                    result["issue_category"] = "no_issue"
            elif result["encrypted_format"] == "client":
                if cache_type == "sync":
                    result["severity"] = "OK"
                    result["issue_category"] = "no_issue"
                elif cache_type == "ai":
                    result["severity"] = "HIGH"
                    result["issue_category"] = "wrong_encryption"

            result["detailed_analysis"] = {
                "cache_type_expected_encryption": "client" if cache_type == "sync" else "vault",
                "detected_encryption": result["encrypted_format"],
                "vault_decryption_succeeded": result["vault_decryption_possible"],
                "summary": (
                    f"{cache_type.upper()} cache with {result['encrypted_format']} encryption - "
                    f"vault decryption: {result['vault_decryption_possible']}"
                )
            }

            logger.info(f"🧪 VAULT DECRYPTION TEST RESULT: {result['detailed_analysis']['summary']}")

        except Exception as e:
            logger.error(f"Error in vault decryption test: {e}", exc_info=True)
            result["test_error"] = str(e)
            result["⚠️_interpretation"] = f"Test failed with error: {e}"

        return result

    async def test_all_caches_for_chat(
        self,
        user_id: str,
        chat_id: str
    ) -> Dict[str, Any]:
        """
        Comprehensive test of both sync and AI caches for a chat.

        Returns dict with results for both cache types.
        """
        results = {
            "test_timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id[:8] + "...",
            "chat_id": chat_id[:8] + "...",
            "sync_cache": None,
            "ai_cache": None,
            "summary": None
        }

        # Test sync cache
        sync_result = await self.test_message_decryption(user_id, chat_id, "sync", 0)
        results["sync_cache"] = sync_result

        # Test AI cache
        ai_result = await self.test_message_decryption(user_id, chat_id, "ai", 0)
        results["ai_cache"] = ai_result

        # Generate summary
        issues = []
        if sync_result.get("vault_decryption_possible") and sync_result.get("cache_type") == "sync":
            issues.append("❌ CRITICAL: Sync cache has vault-encrypted messages (should be client-encrypted)")

        if ai_result.get("encrypted_format") == "client" and ai_result.get("cache_type") == "ai":
            issues.append("⚠️ HIGH: AI cache has client-encrypted messages (should be vault-encrypted)")

        if not issues:
            results["summary"] = "✅ Both caches appear to have correct encryption types"
        else:
            results["summary"] = "❌ ISSUES DETECTED:\n" + "\n".join(issues)

        return results

    async def test_directus_messages(
        self,
        directus_service,
        user_id: str,
        chat_id: str
    ) -> Dict[str, Any]:
        """
        Test messages from Directus to verify they are client-encrypted, not vault-encrypted.

        This is important because Directus is the source of truth.
        """
        result = {
            "test_timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id[:8] + "...",
            "messages_tested": 0,
            "vault_encrypted_count": 0,
            "client_encrypted_count": 0,
            "unknown_format_count": 0,
            "issues_detected": []
        }

        try:
            # Get messages from Directus
            messages_map = await directus_service.chat.get_messages_for_chats([chat_id])
            messages_str_list = messages_map.get(chat_id, [])

            if not messages_str_list:
                result["⚠️_note"] = "No messages found in Directus for this chat"
                return result

            # Analyze each message
            for idx, msg_str in enumerate(messages_str_list[:10]):  # Test first 10
                try:
                    msg_obj = json.loads(msg_str)
                    encrypted_content = msg_obj.get("encrypted_content", "")

                    if encrypted_content.startswith("vault:v"):
                        result["vault_encrypted_count"] += 1
                        result["issues_detected"].append({
                            "message_index": idx,
                            "issue": "Vault-encrypted message in Directus",
                            "severity": "CRITICAL"
                        })
                    elif encrypted_content:
                        result["client_encrypted_count"] += 1
                    else:
                        result["unknown_format_count"] += 1

                    result["messages_tested"] += 1

                except Exception as e:
                    logger.warning(f"Could not parse message {idx} from Directus: {e}")

            # Determine if Directus is corrupted
            if result["vault_encrypted_count"] > 0:
                result["⚠️_critical_issue"] = (
                    f"Directus contains {result['vault_encrypted_count']} vault-encrypted messages! "
                    f"This is a critical violation - Directus should ONLY have client-encrypted messages."
                )

        except Exception as e:
            logger.error(f"Error testing Directus messages: {e}", exc_info=True)
            result["test_error"] = str(e)

        return result

    def print_results(self, result: Dict[str, Any]):
        """Pretty-print test results"""
        print(f"\n{'='*80}")
        print(f"VAULT DECRYPTION TEST RESULTS")
        print(f"{'='*80}\n")

        if "test_error" in result:
            print(f"❌ TEST ERROR: {result['test_error']}\n")
            return

        print(f"Cache Type: {result.get('cache_type')}")
        print(f"Encrypted Format Detected: {result.get('encrypted_format')}")
        print(f"Content Length: {result.get('encrypted_content_length')} bytes")
        print(f"Vault Decryption Possible: {result.get('vault_decryption_possible')}")

        if result.get("⚠️_interpretation"):
            print(f"\n⚠️  INTERPRETATION: {result.get('⚠️_interpretation')}")

        if result.get("✅_interpretation"):
            print(f"\n✅ INTERPRETATION: {result.get('✅_interpretation')}")

        if result.get("recommendation"):
            print(f"\n📋 RECOMMENDATION:\n{result.get('recommendation')}")

        print(f"\n{'='*80}\n")
