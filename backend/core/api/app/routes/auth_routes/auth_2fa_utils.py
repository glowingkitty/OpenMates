import secrets
import string
import pyotp
import hashlib # Added for SHA256 hashing
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Initialize Argon2 hasher
argon2_hasher = PasswordHasher()

# Generate a new 2FA secret
def generate_2fa_secret(app_name="OpenMates", username=""):
    """Generate a new TOTP secret for 2FA"""
    secret = pyotp.random_base32()
    display_name = username if username else "User"
    otpauth_url = pyotp.totp.TOTP(secret).provisioning_uri(
        name=display_name,
        issuer_name=app_name
    )
    return secret, otpauth_url, app_name

# Helper function to hash a backup code with SHA256 (for cache checks)
def sha_hash_backup_code(code: str) -> str:
    """Hash a backup code using SHA256 and return hex digest. No normalization."""
    if not isinstance(code, str):
        raise TypeError("Input code must be a string")
    return hashlib.sha256(code.encode('utf-8')).hexdigest()

# Helper function to hash a backup code with Argon2 (for storage)
def hash_backup_code(code):
    """Hash a backup code using Argon2. No normalization."""
    return argon2_hasher.hash(code)

# Helper function to verify a backup code against hashed codes (Argon2)
def verify_backup_code(code, hashed_codes):
    """Verify a backup code against a list of hashed codes"""
    for hashed_code in hashed_codes:
        try:
            argon2_hasher.verify(hashed_code, code)
            return True, hashed_codes.index(hashed_code)
        except VerifyMismatchError:
            continue
    return False, -1

# Helper function to generate backup codes
def generate_backup_codes(count=5, length=12):
    """Generate random backup codes with hyphens every 4 characters."""
    backup_codes = []
    for _ in range(count):
        chars = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
        # Insert hyphens every 4 characters
        formatted_code = '-'.join(chars[i:i+4] for i in range(0, len(chars), 4))
        backup_codes.append(formatted_code)
    return backup_codes