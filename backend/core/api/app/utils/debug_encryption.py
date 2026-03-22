"""
DEBUG MODULE FOR ENCRYPTION ISSUES
Purpose: Targeted logging and diagnostics for the dual-cache encryption bug

USAGE:
  1. Import: from backend.core.api.app.utils.debug_encryption import EncryptionDebugger
  2. Enable in handlers: debugger = EncryptionDebugger(user_id, chat_id)
  3. Log operations: debugger.log_message_encryption(...)
  4. Later disable by removing the import

NOTE: This is FOR DEBUGGING ONLY and should be removed once the bug is fixed.
It adds performance overhead and logs sensitive data.
"""

import logging
import json
import base64
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

class EncryptionStage(Enum):
    """Stages of message processing for encryption"""
    CLIENT_RECEIVED = "client_received"
    CONTENT_PREPARED = "content_prepared"
    VAULT_ENCRYPTION = "vault_encryption"
    CACHE_STORAGE = "cache_storage"
    CACHE_RETRIEVAL = "cache_retrieval"
    DIRECTUS_FETCH = "directus_fetch"
    SYNC_CACHE_STORAGE = "sync_cache_storage"
    SYNC_CACHE_RETRIEVAL = "sync_cache_retrieval"
    DECRYPTION_ATTEMPT = "decryption_attempt"
    CLIENT_SEND = "client_send"

class EncryptionDebugger:
    """
    Comprehensive encryption debugging utility

    Tracks the journey of a message through:
    - Client submission
    - Encryption (vault key)
    - AI cache storage
    - Sync cache storage
    - Decryption attempts (for diagnostics)
    """

    def __init__(self, user_id: str, chat_id: str, enabled: bool = True):
        self.user_id = user_id
        self.chat_id = chat_id
        self.enabled = enabled
        self.events = []
        self.debug_log_prefix = f"🔐_ENCRYPTION_DEBUG [{user_id[:8]}...][{chat_id[:8]}...]"

    def _log(self, stage: EncryptionStage, message: str, data: Optional[Dict[str, Any]] = None):
        """Internal logging method"""
        if not self.enabled:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        event = {
            "timestamp": timestamp,
            "stage": stage.value,
            "message": message,
            "data": data or {}
        }
        self.events.append(event)

        log_message = f"{self.debug_log_prefix} [{stage.value}] {message}"
        if data:
            log_message += f" | {json.dumps(data, default=str)}"

        logger.info(log_message)

    def log_client_message_received(self, message_id: str, role: str, content_length: int):
        """Log when a message arrives from the client"""
        self._log(
            EncryptionStage.CLIENT_RECEIVED,
            f"Message received from client: {message_id}",
            {
                "message_id": message_id,
                "role": role,
                "content_length": content_length,
                "content_type": "plaintext"
            }
        )

    def log_content_preparation(self, message_id: str, content_preview: str, is_dict: bool = False):
        """Log content preparation before encryption"""
        self._log(
            EncryptionStage.CONTENT_PREPARED,
            f"Content prepared for encryption: {message_id}",
            {
                "message_id": message_id,
                "is_dict": is_dict,
                "content_preview": content_preview[:100] if isinstance(content_preview, str) else "dict",
                "will_be_encrypted": True
            }
        )

    def log_vault_encryption(
        self,
        message_id: str,
        vault_key_id: str,
        original_length: int,
        encrypted_content: str,
        encryption_method: str = "encrypt_with_user_key"
    ):
        """Log vault encryption of message content"""
        # Extract the vault cipher format to verify it's actually vault-encrypted
        is_vault_format = encrypted_content.startswith("vault:v")
        encryption_key_type = "vault_key" if is_vault_format else "❌_INVALID_FORMAT"

        self._log(
            EncryptionStage.VAULT_ENCRYPTION,
            f"Message encrypted with vault key: {message_id}",
            {
                "message_id": message_id,
                "vault_key_id": vault_key_id[:20] + "...",
                "encryption_method": encryption_method,
                "original_content_length": original_length,
                "encrypted_content_length": len(encrypted_content),
                "encrypted_format": encrypted_content[:30] + "...",
                "is_vault_format": is_vault_format,
                "encryption_key_type": encryption_key_type,
                "⚠️_WARNING": "❌ NOT vault format!" if not is_vault_format else None
            }
        )

    def log_cache_storage(
        self,
        message_id: str,
        cache_type: str,  # "ai" or "sync"
        encrypted_content: str,
        cache_key: str
    ):
        """Log message storage to cache"""
        # Verify encryption type matches cache type
        is_vault_encrypted = encrypted_content.startswith("vault:v")
        expected_vault = cache_type == "ai"
        encryption_match = is_vault_encrypted == expected_vault

        self._log(
            EncryptionStage.CACHE_STORAGE,
            f"Message stored to {cache_type.upper()} cache: {message_id}",
            {
                "message_id": message_id,
                "cache_type": cache_type,
                "cache_key": cache_key,
                "encrypted_content_length": len(encrypted_content),
                "encrypted_format": encrypted_content[:30] + "...",
                "is_vault_encrypted": is_vault_encrypted,
                "expected_encryption": "vault" if expected_vault else "client",
                "✅_ENCRYPTION_MATCH": encryption_match,
                "❌_ENCRYPTION_MISMATCH": not encryption_match,
                "⚠️_WARNING": f"Encryption type mismatch! {cache_type} cache should use {'vault' if expected_vault else 'client'} encryption" if not encryption_match else None
            }
        )

    def log_cache_retrieval(
        self,
        chat_id: str,
        cache_type: str,
        message_count: int,
        first_message_sample: Optional[str] = None
    ):
        """Log message retrieval from cache"""
        sample_encrypted = ""
        sample_format = "unknown"

        if first_message_sample:
            try:
                parsed = json.loads(first_message_sample)
                encrypted_content = parsed.get("encrypted_content", "")
                sample_encrypted = encrypted_content[:30] + "..." if encrypted_content else "NONE"
                sample_format = "vault" if encrypted_content and encrypted_content.startswith("vault:v") else "other"
            except:
                sample_format = "invalid_json"

        self._log(
            EncryptionStage.CACHE_RETRIEVAL,
            f"Retrieved {message_count} messages from {cache_type.upper()} cache: {chat_id}",
            {
                "chat_id": chat_id,
                "cache_type": cache_type,
                "message_count": message_count,
                "first_message_sample": sample_encrypted,
                "sample_encryption_format": sample_format
            }
        )

    def log_directus_fetch(
        self,
        chat_id: str,
        message_count: int,
        first_message_sample: Optional[Dict[str, Any]] = None
    ):
        """Log messages fetched from Directus"""
        sample_encrypted = ""
        sample_format = "unknown"

        if first_message_sample and isinstance(first_message_sample, dict):
            encrypted_content = first_message_sample.get("encrypted_content", "")
            sample_encrypted = encrypted_content[:30] + "..." if encrypted_content else "NONE"
            sample_format = "vault" if encrypted_content and encrypted_content.startswith("vault:v") else "client_encrypted"

        self._log(
            EncryptionStage.DIRECTUS_FETCH,
            f"Fetched {message_count} messages from Directus for chat: {chat_id}",
            {
                "chat_id": chat_id,
                "message_count": message_count,
                "first_message_sample": sample_encrypted,
                "sample_encryption_format": sample_format,
                "expected_format": "client_encrypted (not vault)",
                "✅_FORMAT_CORRECT": sample_format == "client_encrypted"
            }
        )

    def log_sync_cache_storage(
        self,
        chat_id: str,
        message_count: int,
        messages_sample: Optional[list] = None
    ):
        """Log messages stored to sync cache"""
        sample_encrypted = ""
        sample_format = "unknown"

        if messages_sample and len(messages_sample) > 0:
            try:
                parsed = json.loads(messages_sample[0])
                encrypted_content = parsed.get("encrypted_content", "")
                sample_encrypted = encrypted_content[:30] + "..." if encrypted_content else "NONE"
                sample_format = "vault" if encrypted_content and encrypted_content.startswith("vault:v") else "client_encrypted"
            except:
                sample_format = "invalid_json"

        self._log(
            EncryptionStage.SYNC_CACHE_STORAGE,
            f"Stored {message_count} messages to SYNC cache for chat: {chat_id}",
            {
                "chat_id": chat_id,
                "message_count": message_count,
                "first_message_sample": sample_encrypted,
                "sample_encryption_format": sample_format,
                "expected_format": "client_encrypted",
                "✅_FORMAT_CORRECT": sample_format == "client_encrypted" or sample_format == "unknown"
            }
        )

    def log_sync_cache_retrieval(
        self,
        chat_id: str,
        message_count: int,
        messages_sample: Optional[list] = None
    ):
        """Log messages retrieved from sync cache during client sync"""
        sample_encrypted = ""
        sample_format = "unknown"

        if messages_sample and len(messages_sample) > 0:
            try:
                parsed = json.loads(messages_sample[0])
                encrypted_content = parsed.get("encrypted_content", "")
                sample_encrypted = encrypted_content[:30] + "..." if encrypted_content else "NONE"
                sample_format = "vault" if encrypted_content and encrypted_content.startswith("vault:v") else "client_encrypted"
            except:
                sample_format = "invalid_json"

        self._log(
            EncryptionStage.SYNC_CACHE_RETRIEVAL,
            f"Retrieved {message_count} messages from SYNC cache for client: {chat_id}",
            {
                "chat_id": chat_id,
                "message_count": message_count,
                "first_message_sample": sample_encrypted,
                "sample_encryption_format": sample_format,
                "expected_format": "client_encrypted",
                "⚠️_CRITICAL": "Vault-encrypted messages in sync cache! Client cannot decrypt!" if sample_format == "vault" else None
            }
        )

    def log_client_send(self, message_id: str, encrypted_content: str):
        """Log when message is sent to client"""
        is_vault = encrypted_content.startswith("vault:v") if encrypted_content else False

        self._log(
            EncryptionStage.CLIENT_SEND,
            f"Message sent to client: {message_id}",
            {
                "message_id": message_id,
                "encrypted_content_length": len(encrypted_content),
                "encrypted_format": encrypted_content[:30] + "...",
                "is_vault_encrypted": is_vault,
                "⚠️_WARNING": "Vault-encrypted message sent to client! Client cannot decrypt!" if is_vault else "✅ Client-encrypted"
            }
        )

    def get_report(self) -> Dict[str, Any]:
        """Generate debug report"""
        return {
            "user_id": self.user_id[:8] + "...",
            "chat_id": self.chat_id[:8] + "...",
            "event_count": len(self.events),
            "events": self.events,
            "potential_issues": self._detect_issues()
        }

    def _detect_issues(self) -> list:
        """Analyze events for potential issues"""
        issues = []

        # Check for vault-encrypted messages in sync cache
        sync_cache_events = [e for e in self.events if "sync_cache" in e["stage"]]
        for event in sync_cache_events:
            if event["data"].get("sample_encryption_format") == "vault":
                issues.append({
                    "severity": "CRITICAL",
                    "issue": "Vault-encrypted messages in sync cache",
                    "event": event,
                    "solution": "Messages in sync cache must be client-encrypted, not vault-encrypted"
                })

        # Check for client-encrypted messages in AI cache
        ai_cache_events = [e for e in self.events if "cache" in e["stage"] and "ai" in str(e.get("data", {}))]
        for event in ai_cache_events:
            if event["data"].get("sample_encryption_format") == "client_encrypted":
                issues.append({
                    "severity": "HIGH",
                    "issue": "Client-encrypted messages in AI cache",
                    "event": event,
                    "solution": "Messages in AI cache must be vault-encrypted for server processing"
                })

        # Check for directus fetch with wrong encryption
        directus_events = [e for e in self.events if "directus_fetch" in e["stage"]]
        for event in directus_events:
            if event["data"].get("sample_encryption_format") == "vault":
                issues.append({
                    "severity": "CRITICAL",
                    "issue": "Directus contains vault-encrypted messages",
                    "event": event,
                    "solution": "Directus must ONLY contain client-encrypted messages"
                })

        return issues

    def print_summary(self):
        """Print a human-readable summary"""
        report = self.get_report()
        print(f"\n{'='*80}")
        print(f"ENCRYPTION DEBUG SUMMARY")
        print(f"{'='*80}")
        print(f"User: {report['user_id']}")
        print(f"Chat: {report['chat_id']}")
        print(f"Total Events: {report['event_count']}")

        if report["potential_issues"]:
            print(f"\n⚠️  POTENTIAL ISSUES DETECTED: {len(report['potential_issues'])}")
            for idx, issue in enumerate(report["potential_issues"], 1):
                print(f"\n{idx}. [{issue['severity']}] {issue['issue']}")
                print(f"   Solution: {issue['solution']}")
        else:
            print(f"\n✅ No obvious issues detected")

        print(f"\n{'='*80}\n")

        return report
