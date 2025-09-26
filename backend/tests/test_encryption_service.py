"""
Comprehensive unit tests for the EncryptionService class.

Tests the zero-knowledge encryption architecture including:
- User-specific encryption/decryption
- Email encryption/decryption
- Email hashing and verification
- Vault integration
- Error handling and edge cases
"""

import pytest
import asyncio
import base64
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from cryptography.exceptions import InvalidTag

# Import the encryption service
import sys
sys.path.append('/home/superdev/projects/OpenMates/backend/core/api')
from app.utils.encryption import EncryptionService


class TestEncryptionService:
    """Test suite for EncryptionService class"""

    @pytest.fixture
    def mock_vault_url(self):
        """Mock Vault URL for testing"""
        return "http://localhost:8200"

    @pytest.fixture
    def mock_vault_token(self):
        """Mock Vault token for testing"""
        return "test-token-12345"

    @pytest.fixture
    def encryption_service(self, mock_vault_url, mock_vault_token):
        """Create EncryptionService instance with mocked dependencies"""
        with patch.dict(os.environ, {'VAULT_URL': mock_vault_url, 'VAULT_TOKEN': mock_vault_token}):
            service = EncryptionService()
            service.vault_token = mock_vault_token
            return service

    @pytest.fixture
    def mock_vault_response(self):
        """Mock successful Vault response"""
        return {
            "data": {
                "ciphertext": "vault:v1:test-ciphertext",
                "plaintext": base64.b64encode(b"test data").decode('utf-8')
            }
        }

    @pytest.fixture
    def mock_hmac_response(self):
        """Mock HMAC response from Vault"""
        return {
            "data": {
                "hmac": "hmac:v1:test-hmac-digest"
            }
        }

    class TestInitialization:
        """Test service initialization and configuration"""

        def test_init_with_env_vars(self, mock_vault_url, mock_vault_token):
            """Test initialization with environment variables"""
            with patch.dict(os.environ, {'VAULT_URL': mock_vault_url, 'VAULT_TOKEN': mock_vault_token}):
                service = EncryptionService()
                assert service.vault_url == mock_vault_url
                assert service.vault_token == mock_vault_token
                assert service.transit_mount == "transit"

        def test_init_with_token_file(self, mock_vault_url):
            """Test initialization with token from file"""
            mock_token = "file-token-67890"
            with patch.dict(os.environ, {'VAULT_URL': mock_vault_url}):
                with patch('builtins.open', mock_open(read_data=mock_token)):
                    with patch('os.path.exists', return_value=True):
                        service = EncryptionService()
                        assert service.vault_token == mock_token

        def test_init_fallback_to_env_var(self, mock_vault_url, mock_vault_token):
            """Test fallback to environment variable when file doesn't exist"""
            with patch.dict(os.environ, {'VAULT_URL': mock_vault_url, 'VAULT_TOKEN': mock_vault_token}):
                with patch('os.path.exists', return_value=False):
                    service = EncryptionService()
                    assert service.vault_token == mock_vault_token

        def test_init_no_token_available(self, mock_vault_url):
            """Test initialization when no token is available"""
            with patch.dict(os.environ, {'VAULT_URL': mock_vault_url}):
                with patch('os.path.exists', return_value=False):
                    service = EncryptionService()
                    assert service.vault_token is None

    class TestTokenValidation:
        """Test Vault token validation"""

        @pytest.mark.asyncio
        async def test_validate_token_success(self, encryption_service):
            """Test successful token validation"""
            mock_response = {
                "data": {
                    "policies": ["default", "encryption-policy"]
                }
            }
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_response):
                result = await encryption_service._validate_token()
                assert result is True

        @pytest.mark.asyncio
        async def test_validate_token_failure(self, encryption_service):
            """Test token validation failure"""
            with patch.object(encryption_service, '_vault_request', side_effect=Exception("Unauthorized")):
                result = await encryption_service._validate_token()
                assert result is False

        @pytest.mark.asyncio
        async def test_validate_token_caching(self, encryption_service):
            """Test token validation caching"""
            mock_response = {"data": {"policies": ["default"]}}
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_response) as mock_request:
                # First call should validate
                result1 = await encryption_service._validate_token()
                assert result1 is True
                
                # Second call should use cache
                result2 = await encryption_service._validate_token()
                assert result2 is True
                
                # Should only call vault once due to caching
                assert mock_request.call_count == 1

    class TestVaultRequest:
        """Test Vault API request handling"""

        @pytest.mark.asyncio
        async def test_vault_request_success(self, encryption_service, mock_vault_response):
            """Test successful Vault request"""
            with patch('httpx.AsyncClient') as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 200
                mock_response_obj.json.return_value = mock_vault_response
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response_obj
                
                with patch.object(encryption_service, '_validate_token', return_value=True):
                    result = await encryption_service._vault_request("get", "test/path")
                    assert result == mock_vault_response

        @pytest.mark.asyncio
        async def test_vault_request_permission_denied(self, encryption_service):
            """Test Vault request with permission denied"""
            with patch('httpx.AsyncClient') as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 403
                mock_response_obj.text = "Permission denied"
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response_obj
                
                with patch.object(encryption_service, '_validate_token', return_value=True):
                    with pytest.raises(Exception, match="Permission denied"):
                        await encryption_service._vault_request("get", "test/path")

        @pytest.mark.asyncio
        async def test_vault_request_not_found(self, encryption_service):
            """Test Vault request with not found"""
            with patch('httpx.AsyncClient') as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 404
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response_obj
                
                with patch.object(encryption_service, '_validate_token', return_value=True):
                    result = await encryption_service._vault_request("get", "test/path")
                    assert result == {"data": {}}

        @pytest.mark.asyncio
        async def test_vault_request_unauthorized(self, encryption_service):
            """Test Vault request with unauthorized"""
            with patch('httpx.AsyncClient') as mock_client:
                mock_response_obj = MagicMock()
                mock_response_obj.status_code = 401
                
                mock_client.return_value.__aenter__.return_value.get.return_value = mock_response_obj
                
                with patch.object(encryption_service, '_validate_token', return_value=True):
                    with pytest.raises(Exception, match="Vault token is expired or invalid"):
                        await encryption_service._vault_request("get", "test/path")

    class TestUserKeyManagement:
        """Test user-specific key management"""

        @pytest.mark.asyncio
        async def test_create_user_key_success(self, encryption_service):
            """Test successful user key creation"""
            mock_response = {"data": {}}
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_response):
                key_id = await encryption_service.create_user_key()
                assert key_id.startswith("user_")
                assert len(key_id) == 37  # "user_" + 32 hex chars

        @pytest.mark.asyncio
        async def test_create_user_key_failure(self, encryption_service):
            """Test user key creation failure"""
            with patch.object(encryption_service, '_vault_request', side_effect=Exception("Vault error")):
                with pytest.raises(Exception):
                    await encryption_service.create_user_key()

    class TestEncryptionDecryption:
        """Test encryption and decryption operations"""

        @pytest.mark.asyncio
        async def test_encrypt_success(self, encryption_service, mock_vault_response):
            """Test successful encryption"""
            plaintext = "test data"
            key_name = "test-key"
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_vault_response):
                ciphertext, key_version = await encryption_service.encrypt(plaintext, key_name)
                assert ciphertext == "vault:v1:test-ciphertext"
                assert key_version == "v1"

        @pytest.mark.asyncio
        async def test_encrypt_with_context(self, encryption_service, mock_vault_response):
            """Test encryption with context for derived keys"""
            plaintext = "test data"
            key_name = "test-key"
            context = "test-context"
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_vault_response) as mock_request:
                ciphertext, key_version = await encryption_service.encrypt(plaintext, key_name, context)
                
                # Verify context was included in request
                call_args = mock_request.call_args
                assert call_args[1]['data']['context'] == context

        @pytest.mark.asyncio
        async def test_encrypt_empty_plaintext(self, encryption_service):
            """Test encryption with empty plaintext"""
            ciphertext, key_version = await encryption_service.encrypt("", "test-key")
            assert ciphertext == ""
            assert key_version == ""

        @pytest.mark.asyncio
        async def test_decrypt_success(self, encryption_service, mock_vault_response):
            """Test successful decryption"""
            ciphertext = "vault:v1:test-ciphertext"
            key_name = "test-key"
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_vault_response):
                result = await encryption_service.decrypt(ciphertext, key_name)
                assert result == "test data"

        @pytest.mark.asyncio
        async def test_decrypt_with_context(self, encryption_service, mock_vault_response):
            """Test decryption with context"""
            ciphertext = "vault:v1:test-ciphertext"
            key_name = "test-key"
            context = "test-context"
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_vault_response) as mock_request:
                result = await encryption_service.decrypt(ciphertext, key_name, context)
                
                # Verify context was included in request
                call_args = mock_request.call_args
                assert call_args[1]['data']['context'] == context

        @pytest.mark.asyncio
        async def test_decrypt_empty_ciphertext(self, encryption_service):
            """Test decryption with empty ciphertext"""
            result = await encryption_service.decrypt("", "test-key")
            assert result is None

        @pytest.mark.asyncio
        async def test_decrypt_failure(self, encryption_service):
            """Test decryption failure"""
            ciphertext = "vault:v1:invalid-ciphertext"
            key_name = "test-key"
            
            with patch.object(encryption_service, '_vault_request', side_effect=Exception("Decryption failed")):
                result = await encryption_service.decrypt(ciphertext, key_name)
                assert result is None

    class TestUserSpecificEncryption:
        """Test user-specific encryption methods"""

        @pytest.mark.asyncio
        async def test_encrypt_with_user_key_success(self, encryption_service):
            """Test successful user-specific encryption"""
            plaintext = "user data"
            key_id = "user_12345"
            
            with patch.object(encryption_service, 'encrypt', return_value=("ciphertext", "v1")) as mock_encrypt:
                ciphertext, key_version = await encryption_service.encrypt_with_user_key(plaintext, key_id)
                
                # Verify encrypt was called with correct parameters
                mock_encrypt.assert_called_once()
                call_args = mock_encrypt.call_args
                assert call_args[0][0] == plaintext
                assert call_args[0][1] == key_id
                assert 'context' in call_args[1]

        @pytest.mark.asyncio
        async def test_encrypt_with_user_key_empty_input(self, encryption_service):
            """Test user-specific encryption with empty input"""
            ciphertext, key_version = await encryption_service.encrypt_with_user_key("", "key_id")
            assert ciphertext == ""
            assert key_version == ""

        @pytest.mark.asyncio
        async def test_decrypt_with_user_key_success(self, encryption_service):
            """Test successful user-specific decryption"""
            ciphertext = "ciphertext"
            key_id = "user_12345"
            
            with patch.object(encryption_service, 'decrypt', return_value="decrypted data") as mock_decrypt:
                result = await encryption_service.decrypt_with_user_key(ciphertext, key_id)
                
                # Verify decrypt was called with correct parameters
                mock_decrypt.assert_called_once()
                call_args = mock_decrypt.call_args
                assert call_args[0][0] == ciphertext
                assert call_args[0][1] == key_id
                assert 'context' in call_args[1]

        @pytest.mark.asyncio
        async def test_decrypt_with_user_key_empty_input(self, encryption_service):
            """Test user-specific decryption with empty input"""
            result = await encryption_service.decrypt_with_user_key("", "key_id")
            assert result is None

    class TestEmailOperations:
        """Test email-related encryption operations"""

        @pytest.mark.asyncio
        async def test_hash_email_success(self, encryption_service, mock_hmac_response):
            """Test successful email hashing"""
            email = "test@example.com"
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_hmac_response):
                result = await encryption_service.hash_email(email)
                assert result == "test-hmac-digest"

        @pytest.mark.asyncio
        async def test_hash_email_empty_input(self, encryption_service):
            """Test email hashing with empty input"""
            result = await encryption_service.hash_email("")
            assert result == ""

        @pytest.mark.asyncio
        async def test_hash_email_failure(self, encryption_service):
            """Test email hashing failure"""
            email = "test@example.com"
            
            with patch.object(encryption_service, '_vault_request', side_effect=Exception("HMAC failed")):
                with pytest.raises(Exception):
                    await encryption_service.hash_email(email)

        @pytest.mark.asyncio
        async def test_verify_email_hash_success(self, encryption_service):
            """Test successful email hash verification"""
            email = "test@example.com"
            stored_hash = "test-hash"
            
            with patch.object(encryption_service, 'hash_email', return_value=stored_hash):
                result = await encryption_service.verify_email_hash(email, stored_hash)
                assert result is True

        @pytest.mark.asyncio
        async def test_verify_email_hash_mismatch(self, encryption_service):
            """Test email hash verification with mismatch"""
            email = "test@example.com"
            stored_hash = "test-hash"
            computed_hash = "different-hash"
            
            with patch.object(encryption_service, 'hash_email', return_value=computed_hash):
                result = await encryption_service.verify_email_hash(email, stored_hash)
                assert result is False

        @pytest.mark.asyncio
        async def test_verify_email_hash_empty_input(self, encryption_service):
            """Test email hash verification with empty input"""
            result = await encryption_service.verify_email_hash("", "hash")
            assert result is False
            
            result = await encryption_service.verify_email_hash("email", "")
            assert result is False

        @pytest.mark.asyncio
        async def test_verify_email_hash_error(self, encryption_service):
            """Test email hash verification with error"""
            email = "test@example.com"
            stored_hash = "test-hash"
            
            with patch.object(encryption_service, 'hash_email', side_effect=Exception("Hash error")):
                result = await encryption_service.verify_email_hash(email, stored_hash)
                assert result is False

    class TestEmailDecryption:
        """Test email decryption with PyNaCl"""

        def test_decrypt_with_email_key_success(self, encryption_service):
            """Test successful email decryption"""
            # This test requires PyNaCl to be installed
            try:
                import nacl.secret
                import nacl.utils
            except ImportError:
                pytest.skip("PyNaCl not available")
            
            # Create test data
            email = "test@example.com"
            email_encryption_key = nacl.utils.random(32)
            
            # Encrypt email
            box = nacl.secret.SecretBox(email_encryption_key)
            nonce = nacl.utils.random(24)
            encrypted_email_bytes = box.encrypt(email.encode('utf-8'), nonce)
            
            # Combine nonce and ciphertext
            combined = nonce + encrypted_email_bytes
            encrypted_email_b64 = base64.b64encode(combined).decode('utf-8')
            email_key_b64 = base64.b64encode(email_encryption_key).decode('utf-8')
            
            # Test decryption
            result = encryption_service.decrypt_with_email_key(encrypted_email_b64, email_key_b64)
            assert result == email

        def test_decrypt_with_email_key_invalid_key_length(self, encryption_service):
            """Test email decryption with invalid key length"""
            encrypted_email = "dGVzdA=="  # base64 for "test"
            invalid_key = "dGVzdA=="  # 4 bytes instead of 32
            
            result = encryption_service.decrypt_with_email_key(encrypted_email, invalid_key)
            assert result is None

        def test_decrypt_with_email_key_invalid_base64(self, encryption_service):
            """Test email decryption with invalid base64"""
            encrypted_email = "invalid-base64!"
            email_key = base64.b64encode(b"test-key-32-bytes-long-123456789").decode('utf-8')
            
            result = encryption_service.decrypt_with_email_key(encrypted_email, email_key)
            assert result is None

        def test_decrypt_with_email_key_too_short(self, encryption_service):
            """Test email decryption with too short encrypted data"""
            encrypted_email = base64.b64encode(b"short").decode('utf-8')  # Less than 24 bytes
            email_key = base64.b64encode(b"test-key-32-bytes-long-123456789").decode('utf-8')
            
            result = encryption_service.decrypt_with_email_key(encrypted_email, email_key)
            assert result is None

        def test_decrypt_with_email_key_missing_pynacl(self, encryption_service):
            """Test email decryption when PyNaCl is not available"""
            with patch('nacl.secret', side_effect=ImportError("No module named 'nacl'")):
                encrypted_email = "dGVzdA=="
                email_key = base64.b64encode(b"test-key-32-bytes-long-123456789").decode('utf-8')
                
                result = encryption_service.decrypt_with_email_key(encrypted_email, email_key)
                assert result is None

        def test_decrypt_with_email_key_empty_input(self, encryption_service):
            """Test email decryption with empty input"""
            result = encryption_service.decrypt_with_email_key("", "key")
            assert result is None
            
            result = encryption_service.decrypt_with_email_key("data", "")
            assert result is None

    class TestServiceLifecycle:
        """Test service initialization and cleanup"""

        @pytest.mark.asyncio
        async def test_initialize_success(self, encryption_service):
            """Test successful service initialization"""
            with patch.object(encryption_service, '_validate_token', return_value=True):
                result = await encryption_service.initialize()
                assert result is True

        @pytest.mark.asyncio
        async def test_initialize_failure(self, encryption_service):
            """Test service initialization failure"""
            with patch.object(encryption_service, '_validate_token', return_value=False):
                result = await encryption_service.initialize()
                assert result is False

        @pytest.mark.asyncio
        async def test_close(self, encryption_service):
            """Test service cleanup"""
            # Should not raise any exceptions
            await encryption_service.close()

    class TestEnsureKeysExist:
        """Test key existence verification and creation"""

        @pytest.mark.asyncio
        async def test_ensure_keys_exist_transit_enabled(self, encryption_service):
            """Test when transit engine is already enabled"""
            mock_response = {"data": {"type": "transit"}}
            
            with patch.object(encryption_service, '_vault_request', return_value=mock_response):
                # Should not raise any exceptions
                await encryption_service.ensure_keys_exist()

        @pytest.mark.asyncio
        async def test_ensure_keys_exist_transit_not_enabled(self, encryption_service):
            """Test when transit engine needs to be enabled"""
            # First call fails (transit not enabled), second succeeds (enabling transit)
            with patch.object(encryption_service, '_vault_request', side_effect=[
                Exception("404"),  # Transit not found
                {"data": {}}       # Transit enabled successfully
            ]):
                await encryption_service.ensure_keys_exist()

        @pytest.mark.asyncio
        async def test_ensure_keys_exist_email_key_exists(self, encryption_service):
            """Test when email HMAC key already exists"""
            mock_responses = [
                {"data": {"type": "transit"}},  # Transit enabled
                {"data": {"name": "email-hmac-key"}}  # Email key exists
            ]
            
            with patch.object(encryption_service, '_vault_request', side_effect=mock_responses):
                await encryption_service.ensure_keys_exist()

        @pytest.mark.asyncio
        async def test_ensure_keys_exist_email_key_creation(self, encryption_service):
            """Test email HMAC key creation"""
            mock_responses = [
                {"data": {"type": "transit"}},  # Transit enabled
                Exception("404"),              # Email key not found
                {"data": {}}                   # Email key created
            ]
            
            with patch.object(encryption_service, '_vault_request', side_effect=mock_responses):
                await encryption_service.ensure_keys_exist()

    class TestWaitForValidToken:
        """Test token waiting functionality"""

        @pytest.mark.asyncio
        async def test_wait_for_valid_token_success(self, encryption_service):
            """Test successful token waiting"""
            with patch.object(encryption_service, '_get_token_from_file', return_value="valid-token"):
                with patch.object(encryption_service, '_validate_token', return_value=True):
                    result = await encryption_service.wait_for_valid_token(max_attempts=1, delay=0)
                    assert result is True

        @pytest.mark.asyncio
        async def test_wait_for_valid_token_timeout(self, encryption_service):
            """Test token waiting timeout"""
            with patch.object(encryption_service, '_get_token_from_file', return_value=None):
                with patch.object(encryption_service, '_validate_token', return_value=False):
                    result = await encryption_service.wait_for_valid_token(max_attempts=1, delay=0)
                    assert result is False

        @pytest.mark.asyncio
        async def test_wait_for_valid_token_cached(self, encryption_service):
            """Test token waiting with cached valid token"""
            # Set up cached valid token
            encryption_service._token_valid_until = float('inf')
            
            result = await encryption_service.wait_for_valid_token(max_attempts=1, delay=0)
            assert result is True


# Integration tests that require actual Vault instance
class TestEncryptionServiceIntegration:
    """Integration tests for EncryptionService (requires running Vault)"""

    @pytest.fixture
    def vault_url(self):
        """Vault URL for integration tests"""
        return os.environ.get('VAULT_URL', 'http://localhost:8200')

    @pytest.fixture
    def vault_token(self):
        """Vault token for integration tests"""
        return os.environ.get('VAULT_TOKEN')

    @pytest.mark.skipif(
        not os.environ.get('VAULT_TOKEN'),
        reason="Integration tests require VAULT_TOKEN environment variable"
    )
    @pytest.mark.asyncio
    async def test_full_encryption_cycle(self, vault_url, vault_token):
        """Test complete encryption/decryption cycle with real Vault"""
        service = EncryptionService()
        service.vault_url = vault_url
        service.vault_token = vault_token
        
        # Initialize service
        await service.initialize()
        await service.ensure_keys_exist()
        
        # Create user key
        key_id = await service.create_user_key()
        assert key_id.startswith("user_")
        
        # Test encryption/decryption
        plaintext = "test data for encryption"
        ciphertext, key_version = await service.encrypt_with_user_key(plaintext, key_id)
        assert ciphertext != plaintext
        assert key_version is not None
        
        decrypted = await service.decrypt_with_user_key(ciphertext, key_id)
        assert decrypted == plaintext
        
        # Test email operations
        email = "test@example.com"
        email_hash = await service.hash_email(email)
        assert email_hash is not None
        
        verification = await service.verify_email_hash(email, email_hash)
        assert verification is True
        
        # Cleanup
        await service.close()

    @pytest.mark.skipif(
        not os.environ.get('VAULT_TOKEN'),
        reason="Integration tests require VAULT_TOKEN environment variable"
    )
    @pytest.mark.asyncio
    async def test_email_decryption_integration(self, vault_url, vault_token):
        """Test email decryption with real PyNaCl"""
        try:
            import nacl.secret
            import nacl.utils
        except ImportError:
            pytest.skip("PyNaCl not available")
        
        service = EncryptionService()
        service.vault_url = vault_url
        service.vault_token = vault_token
        
        # Test email decryption
        email = "integration@test.com"
        email_encryption_key = nacl.utils.random(32)
        
        # Encrypt email
        box = nacl.secret.SecretBox(email_encryption_key)
        nonce = nacl.utils.random(24)
        encrypted_email_bytes = box.encrypt(email.encode('utf-8'), nonce)
        
        # Combine nonce and ciphertext
        combined = nonce + encrypted_email_bytes
        encrypted_email_b64 = base64.b64encode(combined).decode('utf-8')
        email_key_b64 = base64.b64encode(email_encryption_key).decode('utf-8')
        
        # Test decryption
        result = service.decrypt_with_email_key(encrypted_email_b64, email_key_b64)
        assert result == email


if __name__ == "__main__":
    pytest.main([__file__, "-v"])