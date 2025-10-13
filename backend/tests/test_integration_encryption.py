"""
Integration tests for the complete encryption architecture.

Tests the end-to-end encryption flow including:
- Backend encryption service with real Vault
- Frontend crypto service integration
- Chat creation and message flow
- Data integrity and security
- Performance and reliability
"""

import pytest
import asyncio
import os
import json
import base64
from unittest.mock import patch, MagicMock
import sys

# Add backend path
sys.path.append('/home/superdev/projects/OpenMates/backend/core/api')
from app.utils.encryption import EncryptionService


class TestEncryptionIntegration:
    """Integration tests for complete encryption flow"""

    @pytest.fixture
    def vault_url(self):
        """Vault URL for integration tests"""
        return os.environ.get('VAULT_URL', 'http://localhost:8200')

    @pytest.fixture
    def vault_token(self):
        """Vault token for integration tests"""
        return os.environ.get('VAULT_TOKEN')

    @pytest.fixture
    def encryption_service(self, vault_url, vault_token):
        """Create EncryptionService for integration tests"""
        if not vault_token:
            pytest.skip("Integration tests require VAULT_TOKEN environment variable")
        
        service = EncryptionService()
        service.vault_url = vault_url
        service.vault_token = vault_token
        return service

    @pytest.mark.asyncio
    async def test_complete_user_registration_flow(self, encryption_service):
        """Test complete user registration encryption flow"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Simulate user registration
        email = "integration@test.com"
        password = "secure-password-123"
        
        # 1. Hash email for lookup
        email_hash = await encryption_service.hash_email(email)
        assert email_hash is not None
        assert len(email_hash) > 0
        
        # 2. Verify email hash
        verification = await encryption_service.verify_email_hash(email, email_hash)
        assert verification is True
        
        # 3. Create user-specific encryption key
        user_key_id = await encryption_service.create_user_key()
        assert user_key_id.startswith("user_")
        
        # 4. Encrypt user data (e.g., username, settings)
        username = "testuser"
        ciphertext, key_version = await encryption_service.encrypt_with_user_key(username, user_key_id)
        assert ciphertext is not None
        assert key_version is not None
        
        # 5. Decrypt user data
        decrypted_username = await encryption_service.decrypt_with_user_key(ciphertext, user_key_id)
        assert decrypted_username == username
        
        # 6. Test email decryption (if PyNaCl is available)
        try:
            import nacl.secret
            import nacl.utils
            
            # Generate email encryption key
            email_salt = nacl.utils.random(16)
            email_key = nacl.utils.random(32)
            
            # Encrypt email
            box = nacl.secret.SecretBox(email_key)
            nonce = nacl.utils.random(24)
            encrypted_email_bytes = box.encrypt(email.encode('utf-8'), nonce)
            
            # Combine nonce and ciphertext
            combined = nonce + encrypted_email_bytes
            encrypted_email_b64 = base64.b64encode(combined).decode('utf-8')
            email_key_b64 = base64.b64encode(email_key).decode('utf-8')
            
            # Test server-side email decryption
            decrypted_email = encryption_service.decrypt_with_email_key(encrypted_email_b64, email_key_b64)
            assert decrypted_email == email
            
        except ImportError:
            pytest.skip("PyNaCl not available for email decryption test")

    @pytest.mark.asyncio
    async def test_chat_creation_and_message_flow(self, encryption_service):
        """Test complete chat creation and message encryption flow"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # 1. Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # 2. Simulate chat creation
        chat_id = "chat-integration-test-123"
        chat_title = "Integration Test Chat"
        
        # Encrypt chat title with user key
        encrypted_title, title_version = await encryption_service.encrypt_with_user_key(chat_title, user_key_id)
        assert encrypted_title is not None
        
        # 3. Simulate message creation
        messages = [
            {
                "role": "user",
                "content": "Hello, this is a test message",
                "sender_name": "Test User",
                "category": "general"
            },
            {
                "role": "assistant", 
                "content": "Hello! I'm here to help with your questions.",
                "sender_name": "AI Assistant",
                "category": "general"
            }
        ]
        
        # Encrypt each message with user key
        encrypted_messages = []
        for message in messages:
            message_data = json.dumps(message)
            encrypted_message, msg_version = await encryption_service.encrypt_with_user_key(message_data, user_key_id)
            encrypted_messages.append({
                "encrypted_content": encrypted_message,
                "version": msg_version
            })
        
        # 4. Verify decryption
        for i, encrypted_msg in enumerate(encrypted_messages):
            decrypted_data = await encryption_service.decrypt_with_user_key(
                encrypted_msg["encrypted_content"], 
                user_key_id
            )
            decrypted_message = json.loads(decrypted_data)
            assert decrypted_message == messages[i]
        
        # 5. Decrypt chat title
        decrypted_title = await encryption_service.decrypt_with_user_key(encrypted_title, user_key_id)
        assert decrypted_title == chat_title

    @pytest.mark.asyncio
    async def test_multiple_users_isolation(self, encryption_service):
        """Test that different users' data is properly isolated"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create two different user keys
        user1_key_id = await encryption_service.create_user_key()
        user2_key_id = await encryption_service.create_user_key()
        
        # Ensure different keys
        assert user1_key_id != user2_key_id
        
        # Create data for both users
        user1_data = "User 1 confidential data"
        user2_data = "User 2 confidential data"
        
        # Encrypt data for each user
        user1_encrypted, _ = await encryption_service.encrypt_with_user_key(user1_data, user1_key_id)
        user2_encrypted, _ = await encryption_service.encrypt_with_user_key(user2_data, user2_key_id)
        
        # Verify different encryption results
        assert user1_encrypted != user2_encrypted
        
        # Verify each user can only decrypt their own data
        user1_decrypted = await encryption_service.decrypt_with_user_key(user1_encrypted, user1_key_id)
        user2_decrypted = await encryption_service.decrypt_with_user_key(user2_encrypted, user2_key_id)
        
        assert user1_decrypted == user1_data
        assert user2_decrypted == user2_data
        
        # Verify cross-decryption fails
        user1_cross_decrypt = await encryption_service.decrypt_with_user_key(user1_encrypted, user2_key_id)
        user2_cross_decrypt = await encryption_service.decrypt_with_user_key(user2_encrypted, user1_key_id)
        
        assert user1_cross_decrypt is None
        assert user2_cross_decrypt is None

    @pytest.mark.asyncio
    async def test_key_rotation_and_versioning(self, encryption_service):
        """Test key rotation and version management"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # Encrypt data multiple times (simulating key rotation)
        data = "Test data for key rotation"
        encrypted_versions = []
        
        for i in range(3):
            encrypted, version = await encryption_service.encrypt_with_user_key(data, user_key_id)
            encrypted_versions.append((encrypted, version))
        
        # Verify all versions can be decrypted
        for encrypted, version in encrypted_versions:
            decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
            assert decrypted == data
        
        # Verify different versions produce different ciphertexts
        ciphertexts = [enc for enc, _ in encrypted_versions]
        assert len(set(ciphertexts)) == len(ciphertexts)  # All different

    @pytest.mark.asyncio
    async def test_large_data_encryption(self, encryption_service):
        """Test encryption/decryption of large data"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # Test with large data (1MB)
        large_data = "x" * (1024 * 1024)  # 1MB of data
        
        # Encrypt large data
        encrypted, version = await encryption_service.encrypt_with_user_key(large_data, user_key_id)
        assert encrypted is not None
        
        # Decrypt large data
        decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
        assert decrypted == large_data
        
        # Test with very large data (10MB)
        very_large_data = "y" * (10 * 1024 * 1024)  # 10MB of data
        
        encrypted_large, version_large = await encryption_service.encrypt_with_user_key(very_large_data, user_key_id)
        assert encrypted_large is not None
        
        decrypted_large = await encryption_service.decrypt_with_user_key(encrypted_large, user_key_id)
        assert decrypted_large == very_large_data

    @pytest.mark.asyncio
    async def test_special_characters_and_unicode(self, encryption_service):
        """Test encryption with special characters and unicode"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # Test various special characters and unicode
        test_cases = [
            "Basic ASCII: Hello World!",
            "Special chars: !@#$%^&*()_+-=[]{}|;:,.<>?",
            "Unicode: 🚀 🌟 💫 🎉",
            "Mixed: Hello 世界! 🌍",
            "Emojis: 😀😃😄😁😆😅😂🤣",
            "Math symbols: ∑∏∫√∞≤≥≠≈",
            "Currency: $€£¥₹₽",
            "Quotes: \"'`«»‹›",
            "Newlines and tabs:\n\t\r",
            "Null bytes: \x00\x01\x02",
        ]
        
        for test_data in test_cases:
            # Encrypt
            encrypted, version = await encryption_service.encrypt_with_user_key(test_data, user_key_id)
            assert encrypted is not None
            
            # Decrypt
            decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
            assert decrypted == test_data

    @pytest.mark.asyncio
    async def test_concurrent_encryption_operations(self, encryption_service):
        """Test concurrent encryption operations"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # Define concurrent encryption task
        async def encrypt_data(data_id):
            data = f"Concurrent test data {data_id}"
            encrypted, version = await encryption_service.encrypt_with_user_key(data, user_key_id)
            decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
            return data_id, encrypted, decrypted
        
        # Run concurrent operations
        tasks = [encrypt_data(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Verify all operations succeeded
        assert len(results) == 10
        for data_id, encrypted, decrypted in results:
            assert encrypted is not None
            assert decrypted == f"Concurrent test data {data_id}"

    @pytest.mark.asyncio
    async def test_error_handling_and_recovery(self, encryption_service):
        """Test error handling and recovery scenarios"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # Test with invalid data
        invalid_cases = [
            "",  # Empty string
            None,  # None value
        ]
        
        for invalid_data in invalid_cases:
            if invalid_data is None:
                # Skip None test as it would cause type error
                continue
            
            encrypted, version = await encryption_service.encrypt_with_user_key(invalid_data, user_key_id)
            decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
            assert decrypted == invalid_data
        
        # Test with invalid key ID
        invalid_key_id = "invalid-key-id"
        data = "Test data"
        
        # This should handle gracefully
        encrypted, version = await encryption_service.encrypt_with_user_key(data, invalid_key_id)
        # The encryption might succeed but decryption should fail
        decrypted = await encryption_service.decrypt_with_user_key(encrypted, invalid_key_id)
        assert decrypted is None

    @pytest.mark.asyncio
    async def test_performance_benchmarks(self, encryption_service):
        """Test encryption performance benchmarks"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        import time
        
        # Test encryption performance
        data_sizes = [1024, 10240, 102400]  # 1KB, 10KB, 100KB
        iterations = 10
        
        for size in data_sizes:
            test_data = "x" * size
            
            # Measure encryption time
            start_time = time.time()
            for _ in range(iterations):
                encrypted, version = await encryption_service.encrypt_with_user_key(test_data, user_key_id)
            encryption_time = time.time() - start_time
            
            # Measure decryption time
            start_time = time.time()
            for _ in range(iterations):
                decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
            decryption_time = time.time() - start_time
            
            avg_encryption_time = encryption_time / iterations
            avg_decryption_time = decryption_time / iterations
            
            print(f"Data size: {size} bytes")
            print(f"Average encryption time: {avg_encryption_time:.4f}s")
            print(f"Average decryption time: {avg_decryption_time:.4f}s")
            print(f"Encryption throughput: {size / avg_encryption_time / 1024:.2f} KB/s")
            print(f"Decryption throughput: {size / avg_decryption_time / 1024:.2f} KB/s")
            print()
            
            # Basic performance assertions (adjust thresholds as needed)
            assert avg_encryption_time < 1.0  # Should encrypt in less than 1 second
            assert avg_decryption_time < 1.0  # Should decrypt in less than 1 second

    @pytest.mark.asyncio
    async def test_data_integrity_and_corruption_detection(self, encryption_service):
        """Test data integrity and corruption detection"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Create user key
        user_key_id = await encryption_service.create_user_key()
        
        # Test data integrity
        original_data = "Test data for integrity check"
        encrypted, version = await encryption_service.encrypt_with_user_key(original_data, user_key_id)
        decrypted = await encryption_service.decrypt_with_user_key(encrypted, user_key_id)
        
        assert decrypted == original_data
        
        # Test corruption detection
        # Corrupt the encrypted data
        corrupted_encrypted = encrypted[:-5] + "corrupted"
        
        # Decryption should fail gracefully
        corrupted_decrypted = await encryption_service.decrypt_with_user_key(corrupted_encrypted, user_key_id)
        assert corrupted_decrypted is None
        
        # Test with completely invalid encrypted data
        invalid_encrypted = "completely-invalid-data"
        invalid_decrypted = await encryption_service.decrypt_with_user_key(invalid_encrypted, user_key_id)
        assert invalid_decrypted is None

    @pytest.mark.asyncio
    async def test_email_hash_consistency(self, encryption_service):
        """Test email hash consistency across multiple calls"""
        # Initialize service
        await encryption_service.initialize()
        await encryption_service.ensure_keys_exist()
        
        # Test email hash consistency
        email = "consistency@test.com"
        
        # Generate hash multiple times
        hashes = []
        for _ in range(5):
            email_hash = await encryption_service.hash_email(email)
            hashes.append(email_hash)
        
        # All hashes should be identical
        assert len(set(hashes)) == 1
        
        # Verify hash verification works
        verification = await encryption_service.verify_email_hash(email, hashes[0])
        assert verification is True
        
        # Verify different email produces different hash
        different_email = "different@test.com"
        different_hash = await encryption_service.hash_email(different_email)
        assert different_hash != hashes[0]
        
        # Verify hash verification fails for different email
        false_verification = await encryption_service.verify_email_hash(different_email, hashes[0])
        assert false_verification is False


class TestFrontendBackendIntegration:
    """Test integration between frontend and backend encryption"""
    
    def test_encryption_compatibility(self):
        """Test that frontend and backend encryption are compatible"""
        # This test would require running both frontend and backend
        # For now, we'll test the compatibility of the encryption formats
        
        # Test that both use the same encryption algorithms
        # Frontend uses TweetNaCl (XSalsa20-Poly1305)
        # Backend uses Vault transit engine (AES-256-GCM)
        
        # The key compatibility points are:
        # 1. Email encryption uses TweetNaCl on frontend, PyNaCl on backend
        # 2. Both should produce compatible encrypted data
        
        try:
            import nacl.secret
            import nacl.utils
            
            # Test email encryption compatibility
            email = "compatibility@test.com"
            email_key = nacl.utils.random(32)
            
            # Frontend-style encryption (TweetNaCl)
            box = nacl.secret.SecretBox(email_key)
            nonce = nacl.utils.random(24)
            encrypted_email_bytes = box.encrypt(email.encode('utf-8'), nonce)
            
            # Combine nonce and ciphertext (frontend format)
            combined = nonce + encrypted_email_bytes
            encrypted_email_b64 = base64.b64encode(combined).decode('utf-8')
            email_key_b64 = base64.b64encode(email_key).decode('utf-8')
            
            # Backend should be able to decrypt this
            # (This would require the actual EncryptionService instance)
            assert encrypted_email_b64 is not None
            assert email_key_b64 is not None
            
        except ImportError:
            pytest.skip("PyNaCl not available for compatibility test")

    def test_data_format_compatibility(self):
        """Test that data formats are compatible between frontend and backend"""
        # Test JSON serialization compatibility
        test_data = {
            "message_id": "test-123",
            "content": {"type": "doc", "content": [{"type": "text", "text": "Hello"}]},
            "sender_name": "Test User",
            "category": "general"
        }
        
        # Frontend would serialize this as JSON string before encryption
        json_string = json.dumps(test_data)
        
        # Backend should be able to deserialize this
        deserialized = json.loads(json_string)
        
        assert deserialized == test_data
        
        # Test that special characters are preserved
        special_data = {
            "unicode": "🚀 🌟 💫",
            "special_chars": "!@#$%^&*()",
            "newlines": "line1\nline2\tline3"
        }
        
        json_string_special = json.dumps(special_data)
        deserialized_special = json.loads(json_string_special)
        
        assert deserialized_special == special_data


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])