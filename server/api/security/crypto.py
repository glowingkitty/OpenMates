################
# Default Imports
################
import sys
import os
import re

# Fix import path
full_current_path = os.path.realpath(__file__)
main_directory = re.sub('server.*', '', full_current_path)
sys.path.append(main_directory)

from server import *
################

import os
from cryptography.fernet import Fernet
import json
from argon2 import PasswordHasher
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
from dotenv import load_dotenv, find_dotenv
import hashlib


# Load .env file
load_dotenv(find_dotenv())

def generate_key_salt():
    """
    Generates a key and salt and saves them into .env file
    """
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    salt = base64.urlsafe_b64encode(os.urandom(16)).decode()

    with open(".env", "a") as env_file:
        env_file.write(f"\nCRYPTO_KEY={key}\nCRYPTO_SALT={salt}")


def load_key():
    """
    Loads the key from an environment variable
    """
    key = os.getenv("CRYPTO_KEY")
    if key is None:
        raise ValueError("Key not found")
    return key.encode()


def load_salt():
    """
    Loads the salt from an environment variable
    """
    salt = os.getenv("CRYPTO_SALT")
    if salt is None:
        raise ValueError("Salt not found")
    return base64.urlsafe_b64decode(salt)


def encrypt(message:str, type:str=None) -> str:
    """
    Encrypts a message
    """
    key = load_key()
    salt = load_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    encryption_key = base64.urlsafe_b64encode(kdf.derive(key))
    f = Fernet(encryption_key)
    if type == 'json' or type == 'dict':
        message = json.dumps(message)
    encoded_message = message.encode()
    encrypted_message = f.encrypt(encoded_message)

    encrypted_message = base64.urlsafe_b64encode(encrypted_message).decode()

    return encrypted_message


def decrypt(message:str, type:str=None) -> str:
    """
    Decrypts an encrypted message
    """
    key = load_key()
    salt = load_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    encryption_key = base64.urlsafe_b64encode(kdf.derive(key))
    f = Fernet(encryption_key)

    # Decode base64 string back to bytes
    message = base64.urlsafe_b64decode(message)

    decrypted_message = f.decrypt(message)
    if type == 'json' or type == 'dict':
        decrypted_message = json.loads(decrypted_message.decode())
    else:
        decrypted_message = decrypted_message.decode()

    return decrypted_message


def hashing_argon2(text: str) -> str:
    ph = PasswordHasher()
    hashed_text = ph.hash(text)
    return hashed_text


def hashing_sha256(text: str) -> str:
    hashed_text = hashlib.sha256(text.encode()).hexdigest()
    return hashed_text


if __name__ == "__main__":
    # If the script is executed directly, generate and save key and salt if they don't exist yet
    if not os.getenv("CRYPTO_KEY") or not os.getenv("CRYPTO_SALT"):
        add_to_log("Generating key and salt ...")
        generate_key_salt()