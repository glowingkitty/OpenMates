import pytest
from server.api.security.crypto import encrypt, decrypt, hashing, verify_hash
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

@pytest.fixture(scope="module")
def setup_crypto():
    # Ensure CRYPTO_KEY and CRYPTO_SALT are set
    if not os.getenv("CRYPTO_KEY") or not os.getenv("CRYPTO_SALT"):
        pytest.skip("CRYPTO_KEY or CRYPTO_SALT not set in .env file")

def test_encrypt_decrypt_string(setup_crypto):
    original_message = "Hello, World!"
    encrypted = encrypt(original_message)
    decrypted = decrypt(encrypted)
    assert decrypted == original_message

def test_encrypt_decrypt_dict(setup_crypto):
    original_message = {"key": "value", "number": 42}
    encrypted = encrypt(original_message)
    decrypted = decrypt(encrypted, type='dict')
    assert decrypted == original_message

def test_encrypt_decrypt_list(setup_crypto):
    original_message = [1, 2, 3, "four", {"five": 5}]
    encrypted = encrypt(original_message)
    decrypted = decrypt(encrypted, type='json')
    assert decrypted == original_message

def test_decrypt_none():
    assert decrypt(None) is None

def test_hashing_and_verify():
    original_text = "password123"
    hashed = hashing(original_text)
    assert verify_hash(hashed, original_text) == True
    assert verify_hash(hashed, "wrong_password") == False

def test_different_encryptions():
    message = "Same message"
    encryption1 = encrypt(message)
    encryption2 = encrypt(message)
    assert encryption1 != encryption2
    assert decrypt(encryption1) == decrypt(encryption2) == message