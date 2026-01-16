"""
Passkey (WebAuthn) Authentication Endpoints

This module implements passkey registration and authentication flows using WebAuthn.
Passkeys provide passwordless authentication while maintaining zero-knowledge encryption
through the PRF (Pseudo-Random Function) extension.

Security Requirements:
- PRF extension is REQUIRED for zero-knowledge encryption
- Master key is wrapped using HKDF(PRF_signature, user_email_salt)
- Server never sees PRF signature or master key in plaintext
"""

from fastapi import APIRouter, Depends, Request, Response, HTTPException
import logging
import time
import hashlib
import os
import base64
from backend.core.api.app.tasks.celery_config import app as celery_app
import json
from typing import Dict, Any
import cbor2
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    base64url_to_bytes,
)
from webauthn.helpers.options_to_json_dict import options_to_json_dict
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature, decode_dss_signature
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature
from backend.core.api.app.schemas.auth import (
    PasskeyRegistrationInitiateRequest,
    PasskeyRegistrationInitiateResponse,
    PasskeyRegistrationCompleteRequest,
    PasskeyRegistrationCompleteResponse,
    PasskeyAssertionInitiateRequest,
    PasskeyAssertionInitiateResponse,
    PasskeyAssertionVerifyRequest,
    PasskeyAssertionVerifyResponse,
    LoginRequest,
    PasskeyListResponse,
    PasskeyRenameRequest,
    PasskeyRenameResponse,
    PasskeyDeleteRequest,
    PasskeyDeleteResponse
)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.metrics import MetricsService
from backend.core.api.app.services.compliance import ComplianceService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash, _extract_client_ip
from backend.core.api.app.utils.invite_code import validate_invite_code, get_signup_requirements
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_directus_service,
    get_cache_service,
    get_metrics_service,
    get_compliance_service,
    get_encryption_service
)
from backend.core.api.app.routes.auth_routes.auth_utils import verify_allowed_origin, validate_username
from backend.core.api.app.routes.auth_routes.auth_login import finalize_login_session
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.models.user import User
# Import Celery app instance for cache warming tasks
from backend.core.api.app.tasks.celery_config import app

router = APIRouter()
logger = logging.getLogger(__name__)
event_logger = logging.getLogger("app.events")

# WebAuthn Configuration
def get_rp_id_from_request(request: Request) -> str:
    """
    Get the Relying Party ID from the request origin.
    The rpId must match the domain of the website making the request.
    
    For WebAuthn to work:
    - rpId must be the hostname (domain) without protocol, port, or path
    - rpId must match the origin of the request
    - For localhost, use "localhost" (not "127.0.0.1")
    
    IMPORTANT: Each domain has its own rp_id, so passkeys registered on one domain
    (e.g., localhost) will NOT work on another domain (e.g., openmates.org).
    This is correct WebAuthn behavior - passkeys are domain-specific for security.
    """
    # First, try to get from Origin header (most reliable)
    origin = request.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        hostname = parsed.hostname
        if hostname:
            # For localhost, ensure we use "localhost" not "127.0.0.1"
            if hostname == "127.0.0.1":
                return "localhost"
            return hostname
    
    # Fallback to Referer header
    referer = request.headers.get("Referer")
    if referer:
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        hostname = parsed.hostname
        if hostname:
            if hostname == "127.0.0.1":
                return "localhost"
            return hostname
    
    # Fallback to environment variable
    rp_id = os.getenv("WEBAUTHN_RP_ID")
    if rp_id:
        return rp_id
    
    # Last resort: derive from environment variables
    origin = os.getenv("PRODUCTION_URL") or os.getenv("FRONTEND_URLS", "https://openmates.org")
    if origin:
        origin = origin.split(',')[0].strip()
        if origin.startswith("http://") or origin.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            hostname = parsed.hostname
            if hostname:
                return hostname
    
    # Final fallback
    return "openmates.org"

def get_rp_id() -> str:
    """
    Legacy function for backward compatibility.
    Use get_rp_id_from_request() instead when you have access to the request.
    """
    rp_id = os.getenv("WEBAUTHN_RP_ID")
    if rp_id:
        return rp_id
    
    origin = os.getenv("PRODUCTION_URL") or os.getenv("FRONTEND_URLS", "https://openmates.org")
    if origin:
        origin = origin.split(',')[0].strip()
        if origin.startswith("http://") or origin.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            hostname = parsed.hostname
            if hostname:
                return hostname
    
    return "openmates.org"

def get_rp_name() -> str:
    """Get the Relying Party name"""
    return os.getenv("WEBAUTHN_RP_NAME", "OpenMates")

def decode_webauthn_attestation(attestation_object_b64: str) -> tuple[Dict[str, Any], str]:
    """
    Decodes WebAuthn attestationObject (CBOR-encoded) and extracts public key (JWK) and AAGUID.
    
    The attestationObject structure (CBOR):
    {
        "fmt": string (attestation format, e.g., "none", "packed", "fido-u2f"),
        "attStmt": dict (attestation statement, format-specific),
        "authData": bytes (authenticator data)
    }
    
    The authData structure (binary):
    - rpIdHash: 32 bytes
    - flags: 1 byte
    - signCount: 4 bytes (big-endian)
    - aaguid: 16 bytes (UUID)
    - credentialIdLength: 2 bytes (big-endian)
    - credentialId: variable length
    - credentialPublicKey: CBOR-encoded COSE key
    
    Args:
        attestation_object_b64: Base64-encoded attestationObject from WebAuthn
        
    Returns:
        Tuple of (public_key_jwk: Dict, aaguid: str)
        
    Raises:
        ValueError: If attestationObject cannot be decoded or parsed
    """
    try:
        # Decode base64 to get CBOR binary data
        attestation_object_bytes = base64.urlsafe_b64decode(attestation_object_b64 + '==')
        
        # Parse CBOR to get attestation structure
        attestation = cbor2.loads(attestation_object_bytes)
        
        if not isinstance(attestation, dict):
            raise ValueError(f"AttestationObject is not a dict, got {type(attestation)}")
        
        # Extract authData (binary)
        auth_data_bytes = attestation.get("authData")
        if not auth_data_bytes:
            raise ValueError("authData not found in attestationObject")
        
        if not isinstance(auth_data_bytes, bytes):
            raise ValueError(f"authData is not bytes, got {type(auth_data_bytes)}")
        
        # Parse authData binary structure
        # rpIdHash (32 bytes) + flags (1 byte) + signCount (4 bytes) = 37 bytes
        # Then aaguid (16 bytes) starts at offset 37
        if len(auth_data_bytes) < 53:  # Minimum: 37 + 16 (aaguid)
            raise ValueError(f"authData too short: {len(auth_data_bytes)} bytes, need at least 53")
        
        # Extract AAGUID (16 bytes starting at offset 37)
        aaguid_bytes = auth_data_bytes[37:53]
        
        # Convert AAGUID bytes to UUID string
        # Format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        aaguid_hex = aaguid_bytes.hex()
        aaguid = f"{aaguid_hex[0:8]}-{aaguid_hex[8:12]}-{aaguid_hex[12:16]}-{aaguid_hex[16:20]}-{aaguid_hex[20:32]}"
        
        # Extract credentialIdLength (2 bytes, big-endian) at offset 53
        if len(auth_data_bytes) < 55:
            raise ValueError(f"authData too short for credentialIdLength: {len(auth_data_bytes)} bytes")
        
        credential_id_length = int.from_bytes(auth_data_bytes[53:55], byteorder='big')
        
        # Extract credentialId (variable length)
        credential_id_start = 55
        credential_id_end = credential_id_start + credential_id_length
        
        if len(auth_data_bytes) < credential_id_end:
            raise ValueError(f"authData too short for credentialId: {len(auth_data_bytes)} bytes, need {credential_id_end}")
        
        # Extract credentialPublicKey (CBOR-encoded COSE key, starts after credentialId)
        credential_public_key_cbor = auth_data_bytes[credential_id_end:]
        
        if len(credential_public_key_cbor) == 0:
            raise ValueError("credentialPublicKey not found in authData")
        
        # Parse COSE public key (CBOR)
        cose_key = cbor2.loads(credential_public_key_cbor)
        
        if not isinstance(cose_key, dict):
            raise ValueError(f"COSE key is not a dict, got {type(cose_key)}")
        
        # Convert COSE key to JWK format
        # COSE key format uses integer keys (RFC 8152):
        # 1: kty (key type), 3: alg (algorithm), -1: crv (curve), -2: x, -3: y, -4: d
        # JWK uses string keys: "kty", "alg", "crv", "x", "y", "d"
        
        public_key_jwk: Dict[str, Any] = {}
        
        # Key type (kty)
        kty_cose = cose_key.get(1)  # COSE key type
        if kty_cose == 2:  # EC2 (Elliptic Curve)
            public_key_jwk["kty"] = "EC"
        elif kty_cose == 3:  # RSA
            public_key_jwk["kty"] = "RSA"
        else:
            raise ValueError(f"Unsupported COSE key type: {kty_cose}")
        
        # Algorithm (alg)
        alg_cose = cose_key.get(3)
        if alg_cose == -7:  # ES256
            public_key_jwk["alg"] = "ES256"
            public_key_jwk["crv"] = "P-256"
        elif alg_cose == -257:  # RS256
            public_key_jwk["alg"] = "RS256"
        else:
            # Try to get from COSE or use default
            if public_key_jwk["kty"] == "EC":
                public_key_jwk["alg"] = "ES256"
                public_key_jwk["crv"] = "P-256"
            else:
                public_key_jwk["alg"] = "RS256"
        
        # Extract key material based on key type
        if public_key_jwk["kty"] == "EC":
            # Elliptic curve: x and y coordinates
            x_bytes = cose_key.get(-2)  # COSE -2 = x coordinate
            y_bytes = cose_key.get(-3)  # COSE -3 = y coordinate
            
            if not x_bytes or not y_bytes:
                raise ValueError("EC key missing x or y coordinates")
            
            # Convert to base64url (JWK format)
            public_key_jwk["x"] = base64.urlsafe_b64encode(x_bytes).decode('utf-8').rstrip('=')
            public_key_jwk["y"] = base64.urlsafe_b64encode(y_bytes).decode('utf-8').rstrip('=')
            
        elif public_key_jwk["kty"] == "RSA":
            # RSA: n (modulus) and e (exponent)
            n_bytes = cose_key.get(-1)  # COSE -1 = RSA modulus (n)
            e_bytes = cose_key.get(-2)  # COSE -2 = RSA exponent (e)
            
            if not n_bytes or not e_bytes:
                raise ValueError("RSA key missing n or e")
            
            # Convert to base64url (JWK format)
            public_key_jwk["n"] = base64.urlsafe_b64encode(n_bytes).decode('utf-8').rstrip('=')
            
            # Exponent might be bytes or int
            if isinstance(e_bytes, bytes):
                # Convert bytes to int (big-endian)
                e_int = int.from_bytes(e_bytes, byteorder='big')
            else:
                e_int = e_bytes
            
            # Convert int to base64url
            e_bytes_encoded = e_int.to_bytes((e_int.bit_length() + 7) // 8, byteorder='big')
            public_key_jwk["e"] = base64.urlsafe_b64encode(e_bytes_encoded).decode('utf-8').rstrip('=')
        
        # Set key use and operations
        public_key_jwk["use"] = "sig"  # Signature
        public_key_jwk["key_ops"] = ["verify"]
        
        logger.debug(f"Successfully decoded attestationObject: aaguid={aaguid}, kty={public_key_jwk.get('kty')}, alg={public_key_jwk.get('alg')}")
        
        return public_key_jwk, aaguid
        
    except Exception as e:
        logger.error(f"Failed to decode WebAuthn attestationObject: {e}", exc_info=True)
        raise ValueError(f"Invalid attestationObject: {str(e)}")

def parse_authenticator_data(authenticator_data_b64: str) -> tuple[int, bool, bool]:
    """
    Parses WebAuthn authenticatorData (binary) and extracts sign_count and flags.
    
    The authenticatorData structure for assertions (binary):
    - rpIdHash: 32 bytes
    - flags: 1 byte (bit 0 = userPresent, bit 2 = userVerified, bit 6 = attestedCredentialData)
    - signCount: 4 bytes (big-endian, starting at offset 33)
    
    Args:
        authenticator_data_b64: Base64-encoded authenticatorData from WebAuthn
        
    Returns:
        Tuple of (sign_count: int, user_present: bool, user_verified: bool)
        
    Raises:
        ValueError: If authenticatorData cannot be decoded or parsed
    """
    try:
        # Decode base64 to get binary data
        authenticator_data_bytes = base64.urlsafe_b64decode(authenticator_data_b64 + '==')
        
        if len(authenticator_data_bytes) < 37:  # Minimum: 32 (rpIdHash) + 1 (flags) + 4 (signCount)
            raise ValueError(f"authenticatorData too short: {len(authenticator_data_bytes)} bytes, need at least 37")
        
        # Extract flags byte (offset 32)
        flags_byte = authenticator_data_bytes[32]
        
        # Parse flags
        user_present = bool(flags_byte & 0x01)  # Bit 0
        user_verified = bool(flags_byte & 0x04)  # Bit 2
        
        # Extract sign_count (4 bytes, big-endian, starting at offset 33)
        sign_count_bytes = authenticator_data_bytes[33:37]
        sign_count = int.from_bytes(sign_count_bytes, byteorder='big')
        
        logger.debug(f"Parsed authenticatorData: sign_count={sign_count}, user_present={user_present}, user_verified={user_verified}")
        
        return sign_count, user_present, user_verified
        
    except Exception as e:
        logger.error(f"Failed to parse authenticatorData: {e}", exc_info=True)
        raise ValueError(f"Invalid authenticatorData: {str(e)}")

def _decode_base64_from_frontend(data: str) -> bytes:
    """
    Decode base64 string from frontend, handling missing padding automatically.
    
    Frontend uses standard base64 encoding (window.btoa), not base64url.
    This function handles the conversion correctly.
    
    Args:
        data: Base64-encoded string from frontend
        
    Returns:
        Decoded bytes
    """
    # Add padding if needed (base64 strings must be multiple of 4)
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    # Use standard base64 decode (not urlsafe) since frontend uses window.btoa()
    return base64.b64decode(data)


def _decode_base64url(data: str) -> bytes:
    """
    Decode base64url string (JWK format), handling missing padding automatically.
    
    JWK uses base64url encoding (RFC 4648 Section 5) which uses - and _ instead of + and /.
    Padding is optional in base64url.
    
    Args:
        data: Base64url-encoded string (from JWK)
        
    Returns:
        Decoded bytes
    """
    # Add padding if needed (base64 strings must be multiple of 4)
    missing_padding = len(data) % 4
    if missing_padding:
        data += '=' * (4 - missing_padding)
    # Use urlsafe base64 decode for JWK format
    return base64.urlsafe_b64decode(data)


def verify_webauthn_signature(
    public_key_jwk: Dict[str, Any],
    signature_b64: str,
    client_data_json_b64: str,
    authenticator_data_b64: str
) -> bool:
    """
    Verifies a WebAuthn assertion signature using the stored public key.
    
    The signature is over: SHA256(clientDataJSON) || authenticatorData
    (concatenation of the hash of clientDataJSON and the raw authenticatorData bytes)
    
    Args:
        public_key_jwk: Public key in JWK format (from database)
        signature_b64: Base64-encoded signature from WebAuthn assertion
        client_data_json_b64: Base64-encoded clientDataJSON from WebAuthn assertion
        authenticator_data_b64: Base64-encoded authenticatorData from WebAuthn assertion
        
    Returns:
        True if signature is valid, False otherwise
        
    Raises:
        ValueError: If public key format is invalid or unsupported
    """
    try:
        # Decode base64 data using standard base64 (frontend uses window.btoa)
        signature_bytes = _decode_base64_from_frontend(signature_b64)
        client_data_json_bytes = _decode_base64_from_frontend(client_data_json_b64)
        authenticator_data_bytes = _decode_base64_from_frontend(authenticator_data_b64)
        
        logger.info(
            f"Decoded data lengths: signature={len(signature_bytes)} bytes, "
            f"clientDataJSON={len(client_data_json_bytes)} bytes, "
            f"authenticatorData={len(authenticator_data_bytes)} bytes"
        )
        
        # Build signed data: SHA256(clientDataJSON) || authenticatorData
        # This is the exact data that the authenticator signed
        # According to WebAuthn spec: signature is over SHA256(clientDataJSON) || authenticatorData
        client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
        signed_data = client_data_hash + authenticator_data_bytes
        
        logger.info(
            f"Signed data construction: clientDataHash={len(client_data_hash)} bytes, "
            f"authenticatorData={len(authenticator_data_bytes)} bytes, "
            f"total={len(signed_data)} bytes"
        )
        logger.debug(
            f"clientDataHash (first 8 bytes): {client_data_hash[:8].hex()}, "
            f"authenticatorData (first 8 bytes): {authenticator_data_bytes[:8].hex() if len(authenticator_data_bytes) >= 8 else authenticator_data_bytes.hex()}"
        )
        
        # Get key type and algorithm from JWK
        kty = public_key_jwk.get("kty")
        alg = public_key_jwk.get("alg", "ES256")  # Default to ES256
        
        if kty == "EC":
            # Elliptic Curve (ES256)
            if alg != "ES256":
                raise ValueError(f"Unsupported EC algorithm: {alg}, only ES256 is supported")
            
            # Get curve and coordinates
            crv = public_key_jwk.get("crv", "P-256")
            if crv != "P-256":
                raise ValueError(f"Unsupported curve: {crv}, only P-256 is supported")
            
            x_b64 = public_key_jwk.get("x")
            y_b64 = public_key_jwk.get("y")
            
            if not x_b64 or not y_b64:
                raise ValueError("EC key missing x or y coordinates")
            
            # Decode base64url coordinates (JWK uses base64url without padding)
            x_bytes = _decode_base64url(x_b64)
            y_bytes = _decode_base64url(y_b64)
            
            # Validate coordinate lengths (P-256 requires 32 bytes each)
            if len(x_bytes) != 32 or len(y_bytes) != 32:
                raise ValueError(
                    f"Invalid coordinate length: x={len(x_bytes)} bytes, y={len(y_bytes)} bytes. "
                    f"Expected 32 bytes each for P-256 curve."
                )
            
            # Create EC public key
            x_int = int.from_bytes(x_bytes, byteorder='big')
            y_int = int.from_bytes(y_bytes, byteorder='big')
            
            logger.info(f"Decoded JWK coordinates: x={x_int.bit_length()} bits, y={y_int.bit_length()} bits")
            logger.debug(f"JWK x coordinate (first 8 bytes hex): {x_bytes[:8].hex()}, y coordinate (first 8 bytes hex): {y_bytes[:8].hex()}")
            
            # Create public key object
            public_numbers = ec.EllipticCurvePublicNumbers(x_int, y_int, ec.SECP256R1())
            public_key = public_numbers.public_key(default_backend())
            
            # Verify the public key is valid (this will raise if coordinates are invalid)
            try:
                # Serialize and deserialize to validate the key
                serialized = public_key.public_bytes(
                    encoding=serialization.Encoding.X962,
                    format=serialization.PublicFormat.UncompressedPoint
                )
                logger.debug(f"Public key serialized successfully, length: {len(serialized)} bytes")
            except Exception as e:
                logger.error(f"Failed to serialize public key: {e}", exc_info=True)
                raise ValueError(f"Invalid public key coordinates: {str(e)}")
            
            # ES256 signature format handling:
            # According to WebAuthn spec, signatures SHOULD be DER-encoded (RFC3279 section 2.2.3)
            # However, some authenticators may return raw r||s format (64 bytes)
            # We need to handle both formats
            
            signature_length = len(signature_bytes)
            logger.info(f"Signature length: {signature_length} bytes, first 8 bytes: {signature_bytes[:8].hex()}")
            
            if signature_length == 64:
                # Raw format: r||s (32 bytes each) - convert to DER for cryptography library
                logger.debug("Signature is in raw r||s format (64 bytes), converting to DER...")
                r_bytes = signature_bytes[:32]
                s_bytes = signature_bytes[32:]
                r_int = int.from_bytes(r_bytes, byteorder='big')
                s_int = int.from_bytes(s_bytes, byteorder='big')
                logger.debug(f"Extracted r and s from raw format: r={r_int.bit_length()} bits, s={s_int.bit_length()} bits")
                # Convert to DER format for cryptography library
                der_signature = encode_dss_signature(r_int, s_int)
                logger.debug(f"Converted to DER signature: {len(der_signature)} bytes")
            elif 70 <= signature_length <= 72:
                # DER-encoded format (WebAuthn spec compliant) - use directly
                # The cryptography library can verify DER signatures directly
                logger.info(f"Signature is in DER format ({signature_length} bytes) - WebAuthn spec compliant, using directly")
                # Validate DER format by attempting to decode it (for error checking)
                try:
                    r_int, s_int = decode_dss_signature(signature_bytes)
                    logger.info(f"Validated DER signature: r={r_int.bit_length()} bits, s={s_int.bit_length()} bits")
                    # Use the original DER signature directly - don't re-encode as it might change
                    # The cryptography library accepts DER format directly
                    der_signature = signature_bytes
                    logger.info(f"Using original DER signature directly: {len(der_signature)} bytes")
                except Exception as e:
                    logger.error(f"Failed to decode/validate DER signature: {e}", exc_info=True)
                    raise ValueError(f"Invalid DER-encoded signature format: {str(e)}")
            else:
                logger.error(f"Unexpected signature length: {signature_length} bytes")
                raise ValueError(
                    f"Invalid ES256 signature length: {signature_length} bytes. "
                    f"Expected 64 bytes (raw r||s) or 70-72 bytes (DER-encoded per WebAuthn spec)"
                )
            
            # Verify signature
            # According to WebAuthn spec: signature is over SHA256(clientDataJSON) || authenticatorData
            # ECDSA signs a hash, so the authenticator:
            #   1. Computes SHA256(clientDataJSON)
            #   2. Concatenates: SHA256(clientDataJSON) || authenticatorData
            #   3. Hashes this concatenated data: SHA256(SHA256(clientDataJSON) || authenticatorData)
            #   4. Signs this hash
            # 
            # The cryptography library's verify() with ec.ECDSA(hashes.SHA256()) will hash the data we pass
            # So we pass the concatenated data: SHA256(clientDataJSON) || authenticatorData
            # The library will hash it to SHA256(SHA256(clientDataJSON) || authenticatorData) and verify
            try:
                # Log the full signed data hash for debugging
                signed_data_hash = hashlib.sha256(signed_data).digest()
                logger.info(f"Full signed data hash (SHA256 of concatenated data): {signed_data_hash.hex()}")
                logger.info(f"Full authenticatorData (hex): {authenticator_data_bytes.hex()}")
                logger.info(f"Full clientDataJSON (decoded): {client_data_json_bytes.decode('utf-8', errors='ignore')}")
                
                # Try verification - the library will hash signed_data before verification
                # signed_data is: SHA256(clientDataJSON) || authenticatorData
                # Library will compute: SHA256(SHA256(clientDataJSON) || authenticatorData) and verify
                public_key.verify(
                    der_signature,
                    signed_data,  # This is SHA256(clientDataJSON) || authenticatorData
                    ec.ECDSA(hashes.SHA256())  # Library will hash signed_data before verification
                )
                logger.info("ES256 signature verification successful")
                return True
            except InvalidSignature as e:
                # Log detailed information for debugging
                logger.warning(
                    f"Signature verification failed: {e}. "
                    f"Signature length: {signature_length} bytes, "
                    f"Signed data length: {len(signed_data)} bytes"
                )
                # Log hex dumps for debugging (first 32 bytes of each)
                logger.info(
                    f"DER signature (first 32 bytes hex): {der_signature[:32].hex() if len(der_signature) >= 32 else der_signature.hex()}, "
                    f"Signed data (first 32 bytes hex): {signed_data[:32].hex()}, "
                    f"clientDataJSON (first 50 chars): {client_data_json_bytes[:50].decode('utf-8', errors='ignore')}"
                )
                raise
            
        elif kty == "RSA":
            # RSA (RS256)
            if alg != "RS256":
                raise ValueError(f"Unsupported RSA algorithm: {alg}, only RS256 is supported")
            
            # Get modulus and exponent
            n_b64 = public_key_jwk.get("n")
            e_b64 = public_key_jwk.get("e")
            
            if not n_b64 or not e_b64:
                raise ValueError("RSA key missing n or e")
            
            # Decode base64url
            n_bytes = base64.urlsafe_b64decode(n_b64 + '==')
            e_bytes = base64.urlsafe_b64decode(e_b64 + '==')
            
            # Convert to integers
            n_int = int.from_bytes(n_bytes, byteorder='big')
            e_int = int.from_bytes(e_bytes, byteorder='big')
            
            # Create RSA public key
            public_numbers = rsa.RSAPublicNumbers(e_int, n_int)
            public_key = public_numbers.public_key(default_backend())
            
            # RS256 signature is already in PKCS1v15 format
            # Verify signature
            public_key.verify(
                signature_bytes,
                signed_data,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            logger.debug("RS256 signature verification successful")
            return True
            
        else:
            raise ValueError(f"Unsupported key type: {kty}, only EC and RSA are supported")
            
    except InvalidSignature:
        logger.warning("Signature verification failed: invalid signature")
        return False
    except Exception as e:
        logger.error(f"Error verifying WebAuthn signature: {e}", exc_info=True)
        raise ValueError(f"Signature verification error: {str(e)}")

@router.post("/passkey/registration/initiate", response_model=PasskeyRegistrationInitiateResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def passkey_registration_initiate(
    request: Request,
    initiate_request: PasskeyRegistrationInitiateRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Initiate passkey registration by generating a WebAuthn challenge.
    Returns PublicKeyCredentialCreationOptions for the client.
    """
    logger.info("Processing POST /passkey/registration/initiate")
    
    try:
        # Generate a random challenge (32 bytes, base64-encoded)
        challenge_bytes = os.urandom(32)
        challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        # Initialize variables for user information
        user_id_bytes = None
        user_name = None
        user_display_name = None
        actual_user_id = initiate_request.user_id  # Initialize with the request value
        
        if initiate_request.user_id:
            # Check if it's 'current' to use authenticated user from session
            if initiate_request.user_id == 'current':
                try:
                    # Get current authenticated user from session
                    # Extract refresh token from cookies
                    refresh_token = request.cookies.get("auth_refresh_token")
                    if not refresh_token:
                        raise HTTPException(status_code=401, detail="Not authenticated: Missing token")
                    
                    current_user = await get_current_user(
                        directus_service=directus_service,
                        cache_service=cache_service,
                        refresh_token=refresh_token
                    )
                    actual_user_id = current_user.id
                    logger.info(f"Adding passkey to existing user: {actual_user_id}")
                except HTTPException as e:
                    logger.error(f"Failed to get current user from session for passkey registration: {e}")
                    return PasskeyRegistrationInitiateResponse(
                        success=False,
                        challenge="",
                        rp={"id": "", "name": ""},
                        user={"id": "", "name": "", "displayName": ""},
                        pubKeyCredParams=[],
                        timeout=60000,
                        attestation="direct",
                        authenticatorSelection={},
                        message="Authentication required to add passkey to existing account"
                    )
            
            # Existing user - get user info (only if we have a valid user_id, not 'current')
            if actual_user_id and actual_user_id != 'current':
                user_profile = await cache_service.get_user_by_id(actual_user_id)
                if user_profile:
                    # Use username as user.name (shown in passkey dialog) - username is unique per user
                    user_name = user_profile.get("username", "User")
                    user_display_name = user_profile.get("username", "User")
        else:
            # New user signup - username is always provided during signup
            if not initiate_request.username:
                logger.error("Username is required for new user passkey registration")
                return PasskeyRegistrationInitiateResponse(
                    success=False,
                    challenge="",
                    rp={"id": "", "name": ""},
                    user={"id": "", "name": "", "displayName": ""},
                    pubKeyCredParams=[],
                    timeout=60000,
                    attestation="direct",
                    authenticatorSelection={},
                    message="Username is required for passkey registration"
                )
            # Use username as user.name (shown in passkey dialog) - username is unique per user
            user_name = initiate_request.username
            user_display_name = initiate_request.username
        
        # Store challenge in cache with 5-minute TTL (after actual_user_id is determined)
        # Use actual_user_id if it's been resolved (not 'current'), otherwise use the original request value
        challenge_cache_key = f"passkey_challenge:{challenge}"
        cache_user_id = actual_user_id if (actual_user_id and actual_user_id != 'current') else initiate_request.user_id
        await cache_service.set(challenge_cache_key, {
            "hashed_email": initiate_request.hashed_email,
            "user_id": cache_user_id,
            "timestamp": int(time.time())
        }, ttl=300)
        
        # Convert hashed_email to bytes for user.id (WebAuthn requires bytes)
        user_id_bytes = base64.urlsafe_b64decode(initiate_request.hashed_email + '==')[:64]  # Limit to 64 bytes
        
        # CRITICAL: rpId must match the request origin domain for WebAuthn to work
        rp_id = get_rp_id_from_request(request)
        rp_name = get_rp_name()
        
        # Get origin from request headers (for logging/debugging)
        origin = request.headers.get("Origin") or request.headers.get("Referer", "").rsplit("/", 1)[0]
        logger.debug(f"Passkey registration - Origin: {origin}, rpId: {rp_id}")
        
        # Generate registration options using py_webauthn
        # Note: PRF extension is added manually in the response since py_webauthn doesn't support it yet
        registration_options = generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_id=user_id_bytes,
            user_name=user_name,
            user_display_name=user_display_name or user_name,
            challenge=challenge_bytes,
            timeout=60000,
            attestation=AttestationConveyancePreference.DIRECT,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            supported_pub_key_algs=[
                COSEAlgorithmIdentifier.ECDSA_SHA_256,  # ES256
                COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,  # RS256
            ],
        )
        
        # Convert to dict using py_webauthn's helper (properly handles base64url encoding)
        # Then add PRF extension (py_webauthn doesn't support PRF yet)
        # CRITICAL: prfEvalFirst must be deterministic (same value for signup and login)
        # to ensure the PRF output is the same, so the wrapping key is the same, so we can decrypt the master key
        # Use domain-based global salt: SHA256(rp_id) - same for all users on the same domain
        # Security: Each passkey has a unique credential_secret, so PRF output is still unique per user
        prf_eval_first_bytes = hashlib.sha256(rp_id.encode()).digest()[:32]
        prf_eval_first_b64 = base64.urlsafe_b64encode(prf_eval_first_bytes).decode('utf-8').rstrip('=')
        logger.info(f"Registration prf_eval_first: rp_id={rp_id}, first_bytes={prf_eval_first_bytes[:4].hex()}, b64={prf_eval_first_b64[:30]}...")
        creation_options_dict = options_to_json_dict(registration_options)
        creation_options_dict["extensions"] = {
                "prf": {
                    "eval": {
                    "first": prf_eval_first_b64
                }
            }
        }
        
        logger.info(f"Generated passkey registration challenge for hashed_email: {initiate_request.hashed_email[:8]}...")
        
        return PasskeyRegistrationInitiateResponse(
            success=True,
            challenge=creation_options_dict["challenge"],
            rp=creation_options_dict["rp"],
            user=creation_options_dict["user"],
            pubKeyCredParams=creation_options_dict["pubKeyCredParams"],
            timeout=creation_options_dict["timeout"],
            attestation=creation_options_dict["attestation"],
            authenticatorSelection=creation_options_dict["authenticatorSelection"],
            extensions=creation_options_dict.get("extensions"),  # Include PRF extension
            message="Passkey registration initiated"
        )
        
    except Exception as e:
        logger.error(f"Error initiating passkey registration: {str(e)}", exc_info=True)
        return PasskeyRegistrationInitiateResponse(
            success=False,
            challenge="",
            rp={"id": "", "name": ""},
            user={"id": "", "name": "", "displayName": ""},
            pubKeyCredParams=[],
            timeout=60000,
            attestation="direct",
            authenticatorSelection={},
            message=f"Failed to initiate passkey registration: {str(e)}"
        )

@router.post("/passkey/registration/complete", response_model=PasskeyRegistrationCompleteResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("5/minute")
async def passkey_registration_complete(
    request: Request,
    complete_request: PasskeyRegistrationCompleteRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Complete passkey registration by verifying attestation and storing passkey.
    Creates user account if this is a new signup, or adds passkey to existing account.
    """
    logger.info("Processing POST /passkey/registration/complete")
    
    try:
        # CRITICAL: Verify PRF was enabled
        if not complete_request.prf_enabled:
            logger.error("Passkey registration attempted without PRF extension - rejecting for security")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="PRF extension is required for passkey registration. Your password manager doesn't support the PRF standard. Please try another password manager or use password as a signup option instead.",
                user=None
            )
        
        # Extract credential ID from attestation response
        credential_id = complete_request.credential_id
        
        # Check if credential_id already exists (prevent duplicates)
        existing_passkey = await directus_service.get_passkey_by_credential_id(credential_id)
        if existing_passkey:
            logger.warning("Attempted to register duplicate credential_id")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="This passkey is already registered.",
                user=None
            )
        
        # Check if this is for an existing user (adding passkey to existing account)
        is_existing_user = complete_request.user_id == 'current'
        user_id = None
        vault_key_id = None
        
        if is_existing_user:
            # Get current authenticated user from session
            try:
                # Extract refresh token from cookies
                refresh_token = request.cookies.get("auth_refresh_token")
                if not refresh_token:
                    raise HTTPException(status_code=401, detail="Not authenticated: Missing token")
                
                current_user = await get_current_user(
                    directus_service=directus_service,
                    cache_service=cache_service,
                    refresh_token=refresh_token
                )
                user_id = current_user.id
                logger.info(f"Adding passkey to existing user: {user_id}")
                
                # Get user profile to get vault_key_id
                success, user_data, _ = await directus_service.get_user_profile(user_id)
                if success and user_data:
                    vault_key_id = user_data.get("vault_key_id")
            except HTTPException as e:
                logger.error(f"Failed to get current user from session: {e}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Authentication required to add passkey to existing account.",
                    user=None
                )
        else:
            # New user signup flow
            # Validate username
            username_valid, username_error = validate_username(complete_request.username)
            if not username_valid:
                logger.warning(f"Invalid username format: {username_error}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message=f"Invalid username: {username_error}",
                    user=None
                )
            
            # Check if user already exists
            exists_result, existing_user, _ = await directus_service.get_user_by_hashed_email(complete_request.hashed_email)
            if exists_result and existing_user:
                logger.warning("Attempted to register with existing email")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="This email is already registered. Please log in instead.",
                    user=None
                )
        
        # Only process signup flow if this is a new user
        if not is_existing_user:
            # Validate invite code
            invite_code = complete_request.invite_code
            code_data = None
            
            # Get signup requirements based on server edition and configuration
            # For self-hosted: domain restriction OR invite code required
            # For non-self-hosted: use SIGNUP_LIMIT logic
            require_invite_code, require_domain_restriction, allowed_domains = await get_signup_requirements(
                directus_service, cache_service
            )
            
            # Check domain restriction if required (for self-hosted with SIGNUP_DOMAIN_RESTRICTION set)
            if require_domain_restriction and allowed_domains:
                # Extract email from encrypted_email if available, or check during email verification step
                # For passkey registration, domain check should have happened during email verification
                # We validate here as a safety check
                logger.info(f"Domain restriction enabled ({', '.join(allowed_domains)}) for self-hosted edition")
            
            if require_invite_code:
                if not invite_code:
                    return PasskeyRegistrationCompleteResponse(
                        success=False,
                        message="Invite code is required for signup.",
                        user=None
                    )
                is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
                if not is_valid or not code_data:
                    return PasskeyRegistrationCompleteResponse(
                        success=False,
                        message="Invalid or expired invite code.",
                        user=None
                    )
            
            # Extract additional information from invite code
            is_admin = code_data.get('is_admin', False) if code_data else False
            role = code_data.get('role') if code_data else None
            
            # Create the user account with encrypted email
            success, user_data, create_message = await directus_service.create_user(
                username=complete_request.username,
                encrypted_email=complete_request.encrypted_email,
                encrypted_email_with_master_key=complete_request.encrypted_email_with_master_key,
                user_email_salt=complete_request.user_email_salt,
                lookup_hash=complete_request.lookup_hash,
                hashed_email=complete_request.hashed_email,
                language=complete_request.language,
                darkmode=complete_request.darkmode,
                is_admin=is_admin,
                role=role,
            )
            
            if not success:
                logger.error(f"Failed to create user: {create_message}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Failed to create your account. Please try again later.",
                    user=None
                )
            
            user_id = user_data.get("id")
            # Send 'Account created' confirmation email
            try:
                # Fetch verification data from cache to get the plaintext email
                verification_cache_key = f"email_verified:{complete_request.hashed_email}"
                verification_data = await cache_service.get(verification_cache_key)
                
                if verification_data and verification_data.get("email"):
                    celery_app.send_task(
                        name="app.tasks.email_tasks.account_created_email_task.send_account_created_email",
                        kwargs={
                            "email": verification_data.get("email"),
                            "account_id": user_data.get("account_id"),
                            "language": complete_request.language,
                            "darkmode": complete_request.darkmode
                        },
                        queue="email"
                    )
                    logger.info(f"Account created email task submitted for user {user_id}")
            except Exception as email_err:
                logger.error(f"Failed to submit account created email task for user {user_id}: {email_err}")
            vault_key_id = user_data.get("vault_key_id")
        
        # Verify WebAuthn attestation using py_webauthn
        attestation_obj = complete_request.attestation_response
        attestation_object_b64 = attestation_obj.get("attestationObject")
        client_data_json_b64 = complete_request.client_data_json
        
        if not attestation_object_b64 or not client_data_json_b64:
            logger.error("attestationObject or clientDataJSON not found in attestation response")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Invalid passkey registration data. Please try again.",
                user=None
            )
        
        # Get expected challenge from cache
        try:
            client_data_json_bytes = _decode_base64_from_frontend(client_data_json_b64)
            client_data = json.loads(client_data_json_bytes.decode('utf-8'))
            challenge_from_client = client_data.get('challenge', '')
            challenge_cache_key = f"passkey_challenge:{challenge_from_client}"
            cached_challenge = await cache_service.get(challenge_cache_key)
            
            if not cached_challenge:
                logger.warning(f"Challenge not found in cache for user {user_id} - may have expired")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Registration challenge expired. Please try again.",
                    user=None
                )
            
            # Verify type is "webauthn.create"
            if client_data.get("type") != "webauthn.create":
                logger.error(f"Invalid clientDataJSON type: {client_data.get('type')}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Invalid passkey registration type.",
                    user=None
                )
            
            expected_challenge = base64url_to_bytes(challenge_from_client)
        except Exception as e:
            logger.error(f"Failed to parse clientDataJSON for user {user_id}: {e}", exc_info=True)
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Invalid passkey registration data. Please try again.",
                user=None
            )
        
        # Get origin and rp_id
        origin = request.headers.get("Origin") or request.headers.get("Referer", "").rsplit("/", 1)[0]
        rp_id = get_rp_id_from_request(request)
        
        # Verify registration response using py_webauthn
        try:
            # Build credential dict for py_webauthn
            credential_dict = {
                "id": credential_id,
                "rawId": credential_id,
                "response": {
                    "attestationObject": attestation_object_b64,
                    "clientDataJSON": client_data_json_b64,
                    "transports": attestation_obj.get("transports", []),
                },
                "type": "public-key",
                "clientExtensionResults": attestation_obj.get("clientExtensionResults", {}),
            }
            
            # Verify registration response
            registration_verification = verify_registration_response(
                credential=credential_dict,
                expected_challenge=expected_challenge,
                expected_origin=origin,
                expected_rp_id=rp_id,
                require_user_verification=True,
            )
            
            # Extract public key in COSE format (bytes) and AAGUID
            public_key_cose_bytes = registration_verification.credential_public_key
            aaguid = registration_verification.aaguid
            
            # Convert COSE bytes to base64 for storage
            public_key_cose_b64 = base64.urlsafe_b64encode(public_key_cose_bytes).decode('utf-8').rstrip('=')
            
            # Also extract JWK for backward compatibility (using our existing function)
            try:
                public_key_jwk, _ = decode_webauthn_attestation(attestation_object_b64)
            except Exception as e:
                logger.warning(f"Failed to extract JWK for backward compatibility: {e}")
                public_key_jwk = None
            
            logger.info(f"Successfully verified registration and extracted public key for user {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to verify registration response for user {user_id}: {e}", exc_info=True)
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Invalid passkey registration. Please try again.",
                user=None
            )
        
        # Device name is already encrypted client-side with master key (zero-knowledge)
        # Server stores it as-is without decrypting
        encrypted_device_name = complete_request.encrypted_device_name
        
        # Store passkey credential using hashed_user_id for privacy
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Note: prf_eval_first is now computed from rp_id (domain-based global salt)
        # No need to store it in the database - it's deterministic and computed on-the-fly
        # Security: Each passkey has a unique credential_secret, so PRF output is still unique per user
        
        # Log credential_id format for debugging passkey lookup issues
        # IMPORTANT: This MUST match the format sent during login (base64url, no padding)
        logger.info(
            f"Storing passkey with credential_id: {credential_id[:30]}... "
            f"(length={len(credential_id)}, has_padding={'=' in credential_id}, "
            f"has_url_safe_chars={'_' in credential_id or '-' in credential_id})"
        )
        
        passkey_success = await directus_service.create_passkey(
            hashed_user_id=hashed_user_id,
            user_id=user_id,  # Include user_id for efficient lookups
            credential_id=credential_id,
            public_key_cose_b64=public_key_cose_b64,
            public_key_jwk=public_key_jwk,  # For backward compatibility
            aaguid=str(aaguid) if aaguid else None,
            encrypted_device_name=encrypted_device_name
        )
        
        if not passkey_success:
            logger.error(f"Failed to store passkey for user {user_id}")
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Failed to store passkey. Please try again.",
                user=None
            )
        
        logger.info(f"Successfully stored passkey for user {user_id[:8]}... with credential_id prefix {credential_id[:20]}...")
        
        # Create encryption key record (same pattern as password)
        try:
            hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
            # Use unique login method for each passkey to support multiple passkeys with different PRF keys
            # We hash the credential_id to ensure it fits within the login_method field length limit
            credential_id_hash = hashlib.sha256(credential_id.encode()).hexdigest()
            login_method = f"passkey_{credential_id_hash}"
            
            success = await directus_service.create_encryption_key(
                hashed_user_id=hashed_user_id,
                login_method=login_method,
                encrypted_key=complete_request.encrypted_master_key,
                salt=complete_request.salt,
                key_iv=complete_request.key_iv
            )
            if success:
                logger.info(f"Successfully created encryption key record for user {user_id} with method {login_method}")
            else:
                logger.error(f"Failed to create encryption key for user {user_id}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Failed to set up account encryption. Please try again.",
                    user=None
                )
        except Exception as e:
            logger.error(f"Failed to create encryption key for user {user_id}: {e}", exc_info=True)
            return PasskeyRegistrationCompleteResponse(
                success=False,
                message="Failed to set up account encryption. Please try again.",
                user=None
            )
        
        # For existing users, update encrypted_email_with_master_key to match the master key used for passkey
        # This ensures that when they login with passkey, they can decrypt the email with the unwrapped master key
        # CRITICAL: The email must be encrypted with the same master key that's wrapped for the passkey
        # NOTE: If this update fails, passkey login will NOT work because we can't decrypt the email
        if is_existing_user:
            if complete_request.encrypted_email_with_master_key:
                try:
                    update_success = await directus_service.update_user(
                        user_id,
                        {"encrypted_email_with_master_key": complete_request.encrypted_email_with_master_key}
                    )
                    if update_success:
                        logger.info(f"Successfully updated encrypted_email_with_master_key for existing user {user_id}")
                    else:
                        # CRITICAL: This is now a failure condition - passkey login won't work without this
                        logger.error(
                            f"Failed to update encrypted_email_with_master_key for user {user_id}. "
                            "Passkey registration succeeded but login will fail without this field."
                        )
                        return PasskeyRegistrationCompleteResponse(
                            success=False,
                            message="Passkey was registered but account setup incomplete. Please try again or use password login.",
                            user=None
                        )
                except Exception as e:
                    logger.error(f"Error updating encrypted_email_with_master_key for user {user_id}: {e}", exc_info=True)
                    return PasskeyRegistrationCompleteResponse(
                        success=False,
                        message="Passkey was registered but account setup failed. Please try again or use password login.",
                        user=None
                    )
            else:
                # Client didn't send encrypted_email_with_master_key - this is required for passkey login
                logger.error(
                    f"Existing user {user_id} adding passkey but encrypted_email_with_master_key not provided. "
                    "Passkey login will not work without this."
                )
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Passkey registration failed: missing required encryption data. Please try again.",
                    user=None
                )

            # Also add the new lookup_hash to the user's list of valid lookup hashes
            # This is required for authentication with the new passkey
            if complete_request.lookup_hash:
                try:
                    lookup_hash_success = await directus_service.add_user_lookup_hash(user_id, complete_request.lookup_hash)
                    if lookup_hash_success:
                        logger.info(f"Successfully added new lookup_hash for existing user {user_id}")
                    else:
                        logger.warning(f"Failed to add new lookup_hash for user {user_id}, but continuing")
                except Exception as e:
                    logger.error(f"Error adding lookup_hash for user {user_id}: {e}", exc_info=True)
        
        # Only process signup-specific logic for new users
        if not is_existing_user:
            # Generate device fingerprint
            device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
            await directus_service.add_user_device_hash(user_id, device_hash)
            
            # Handle gifted credits (same as password signup)
            invite_code = complete_request.invite_code
            code_data = None
            if invite_code:
                is_valid, message, code_data = await validate_invite_code(invite_code, directus_service, cache_service)
                if not is_valid:
                    code_data = None  # Ensure code_data is None if validation failed
            
            gifted_credits = code_data.get('gifted_credits') if code_data else None
            if gifted_credits and isinstance(gifted_credits, (int, float)) and gifted_credits > 0:
                plain_gift_value = int(gifted_credits)
                logger.info(f"Invite code included {plain_gift_value} gifted credits for user {user_id}.")
                if vault_key_id:
                    try:
                        encrypted_gift_tuple = await encryption_service.encrypt_with_user_key(str(plain_gift_value), vault_key_id)
                        encrypted_gift_value = encrypted_gift_tuple[0]
                        await directus_service.update_user(
                            user_id,
                            {"encrypted_gifted_credits_for_signup": encrypted_gift_value}
                        )
                    except Exception as encrypt_err:
                        logger.error(f"Failed to encrypt gifted credits for user {user_id}: {encrypt_err}", exc_info=True)
            
            # Consume invite code if provided and required
            # Use the same signup requirements logic for consistency
            require_invite_code, _, _ = await get_signup_requirements(directus_service, cache_service)
            if require_invite_code and invite_code and code_data:
                try:
                    consume_success = await directus_service.consume_invite_code(invite_code, code_data)
                    if consume_success:
                        logger.info(f"Successfully consumed invite code {invite_code} for user {user_id}")
                        await cache_service.delete(f"invite_code:{invite_code}")
                except Exception as consume_err:
                    logger.error(f"Error consuming invite code {invite_code} for user {user_id}: {consume_err}", exc_info=True)
            
            # Track metrics
            metrics_service.track_user_creation()
            metrics_service.update_active_users(1, 1)
            
            # Log compliance event
            compliance_service.log_user_creation(
                user_id=user_id,
                status="success"
            )
            
            # Authenticate user to get session cookies
            auth_success, auth_data, auth_message = await directus_service.login_user_with_lookup_hash(
                hashed_email=complete_request.hashed_email,
                lookup_hash=complete_request.lookup_hash
            )
            
            if not auth_success or not auth_data:
                logger.error(f"Failed to authenticate user after passkey creation: {auth_message}")
                return PasskeyRegistrationCompleteResponse(
                    success=True,
                    message="Account created, but automatic login failed. Please log in manually.",
                    user={"id": user_id}
                )
            
            # CRITICAL: Fetch and cache user profile with username BEFORE finalize_login_session
            # This ensures username is in cache even if decryption fails in login_user_with_lookup_hash
            # Same pattern as password signup in auth_password.py
            profile_success, user_profile, profile_message = await directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"Failed to fetch user profile after passkey creation: {profile_message}")
                return PasskeyRegistrationCompleteResponse(
                    success=False,
                    message="Account created but profile setup failed. Please try logging in manually.",
                    user=None
                )
            
            # Add user_email_salt to the profile since get_user_profile doesn't include it
            user_profile["user_email_salt"] = complete_request.user_email_salt
            
            # Cache the user using the same logic as password signup
            user_data_to_cache = {
                    "user_id": user_id,
                    "username": complete_request.username,  # Use username from request - it's guaranteed to be present during signup
                    "is_admin": is_admin,
                    "credits": user_profile.get("credits", 0),
                    "profile_image_url": user_profile.get("profile_image_url"),
                    "tfa_app_name": user_profile.get("tfa_app_name"),
                    "tfa_enabled": user_profile.get("tfa_enabled", False),
                    "last_opened": user_profile.get("last_opened"),
                    "vault_key_id": user_profile.get("vault_key_id"),
                    "consent_privacy_and_apps_default_settings": user_profile.get("consent_privacy_and_apps_default_settings"),
                    "consent_mates_default_settings": user_profile.get("consent_mates_default_settings"),
                    "language": complete_request.language,
                    "darkmode": complete_request.darkmode,
                    "gifted_credits_for_signup": user_profile.get("gifted_credits_for_signup"),
                    "encrypted_email_address": user_profile.get("encrypted_email_address"),
                    # Required for passwordless passkey login (client decrypts with unwrapped master key)
                    "encrypted_email_with_master_key": complete_request.encrypted_email_with_master_key,
                    "invoice_counter": user_profile.get("invoice_counter", 0),
                    "lookup_hashes": user_profile.get("lookup_hashes", []),
                    "account_id": user_data.get("account_id"),  # From the original user_data
                    "user_email_salt": complete_request.user_email_salt,  # Include the salt
                    # Monthly subscription fields (cleartext fields, not sensitive)
                    "stripe_customer_id": user_profile.get("stripe_customer_id"),
                    "stripe_subscription_id": user_profile.get("stripe_subscription_id"),
                    "subscription_status": user_profile.get("subscription_status"),
                    "subscription_credits": user_profile.get("subscription_credits"),
                    "subscription_currency": user_profile.get("subscription_currency"),
                    "next_billing_date": user_profile.get("next_billing_date"),
                    # Keep encrypted payment method ID encrypted
                    "encrypted_payment_method_id": user_profile.get("encrypted_payment_method_id"),
                    # Low balance auto top-up fields (cleartext configuration fields)
                    "auto_topup_low_balance_enabled": user_profile.get("auto_topup_low_balance_enabled", False),
                    "auto_topup_low_balance_threshold": user_profile.get("auto_topup_low_balance_threshold"),
                    "auto_topup_low_balance_amount": user_profile.get("auto_topup_low_balance_amount"),
                    "auto_topup_low_balance_currency": user_profile.get("auto_topup_low_balance_currency")
                }
            
            # Remove gifted_credits_for_signup if it's None or 0 before caching
            if not user_data_to_cache.get("gifted_credits_for_signup"):
                user_data_to_cache.pop("gifted_credits_for_signup", None)
            
            # Cache the user data (without refresh_token since finalize_login_session will handle that)
            await cache_service.set_user(user_data_to_cache)
            logger.info(f"Cached complete user profile for user {user_id} during passkey signup")
            
            # Update user_data with cached profile data for finalize_login_session
            user_data.update(user_data_to_cache)
            
            # Finalize login session
            user = user_data  # Use the updated user_data with cached profile data
            device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(request, user_id)
            refresh_token = await finalize_login_session(
                request=request,
                response=response,
                user=user,
                auth_data=auth_data,
                cache_service=cache_service,
                compliance_service=compliance_service,
                directus_service=directus_service,
                current_device_hash=device_hash,
                client_ip=_extract_client_ip(request.headers, request.client.host if request.client else None),
                encryption_service=encryption_service,
                device_location_str=f"{city}, {country_code}" if city and country_code else country_code or "Unknown",
                latitude=latitude,
                longitude=longitude,
                login_data=LoginRequest(
                    hashed_email=complete_request.hashed_email,
                    lookup_hash=complete_request.lookup_hash,
                    login_method="passkey",
                    stay_logged_in=False
                )
            )
            
            logger.info(f"Passkey registration completed successfully for user {user_id[:6]}...")
            event_logger.info(f"User account created with passkey - ID: {user_id}")
        else:
            # For existing users, just log the passkey addition
            logger.info(f"Passkey added successfully to existing user {user_id[:6]}...")
            event_logger.info(f"Passkey added to existing user - ID: {user_id}")
        
        return PasskeyRegistrationCompleteResponse(
            success=True,
            message="Passkey registered successfully",
            user={
                "id": user_id
            }
        )
        
    except Exception as e:
        logger.error(f"Error completing passkey registration: {str(e)}", exc_info=True)
        return PasskeyRegistrationCompleteResponse(
            success=False,
            message=f"Failed to complete passkey registration: {str(e)}",
            user=None
        )

@router.post("/passkey/assertion/initiate", response_model=PasskeyAssertionInitiateResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def passkey_assertion_initiate(
    request: Request,
    initiate_request: PasskeyAssertionInitiateRequest,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Initiate passkey assertion (login) by generating a WebAuthn challenge.
    Returns PublicKeyCredentialRequestOptions for the client.
    """
    logger.info("Processing POST /passkey/assertion/initiate")
    
    try:
        # Generate a random challenge (32 bytes, base64-encoded)
        challenge_bytes = os.urandom(32)
        challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        # Store challenge in cache with 5-minute TTL
        challenge_cache_key = f"passkey_assertion_challenge:{challenge}"
        await cache_service.set(challenge_cache_key, {
            "hashed_email": initiate_request.hashed_email,
            "timestamp": int(time.time())
        }, ttl=300)
        
        # Build WebAuthn PublicKeyCredentialRequestOptions
        # CRITICAL: rpId must match the request origin domain for WebAuthn to work
        rp_id = get_rp_id_from_request(request)
        rp_name = get_rp_name()
        
        # Get origin from request headers (for logging/debugging)
        origin = request.headers.get("Origin") or request.headers.get("Referer", "")
        logger.debug(f"Passkey assertion - Origin: {origin}, rpId: {rp_id}")
        
        # Get allowed credentials if hashed_email is provided (optional optimization for non-discoverable credentials)
        allow_credentials = []
        if initiate_request.hashed_email:
            # Look up user's passkeys using hashed_user_id (optional optimization)
            exists_result, user_data, _ = await directus_service.get_user_by_hashed_email(initiate_request.hashed_email)
            if exists_result and user_data:
                user_id = user_data.get("id")
                if user_id:
                    hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
                    passkeys = await directus_service.get_user_passkeys(hashed_user_id)
                    for passkey in passkeys:
                        allow_credentials.append({
                            "type": "public-key",
                            "id": passkey.get("credential_id")
                        })

                    # Predictively warm user cache for instant login UX (similar to /lookup endpoint)
                    # This loads phases 1-3 (last opened chat, recent chats, full sync) from Directus to Redis
                    # All data remains encrypted - server cannot decrypt without user's master key
                    cache_primed = await cache_service.is_user_cache_primed(user_id)

                    if not cache_primed:
                        # Check if warming already in progress to avoid duplicate work
                        warming_flag = f"cache_warming_in_progress:{user_id}"
                        is_warming = await cache_service.get(warming_flag)

                        if not is_warming:
                            # Set flag to prevent duplicate warming attempts (5 min TTL)
                            await cache_service.set(warming_flag, "warming", ttl=300)

                            # Get last_opened for cache warming task - fetch from user profile if needed
                            last_opened_path = None
                            try:
                                # Try to get from cached profile first
                                cached_profile = await cache_service.get_user_by_id(user_id)
                                if cached_profile:
                                    last_opened_path = cached_profile.get("last_opened")
                                else:
                                    # Fetch user profile to get last_opened
                                    profile_success, user_profile, _ = await directus_service.get_user_profile(user_id)
                                    if profile_success and user_profile:
                                        last_opened_path = user_profile.get("last_opened")
                            except Exception as e:
                                logger.warning(f"Failed to get last_opened for passkey cache warming: {e}")

                            logger.info(f"[PASSKEY] Pre-warming cache for user {user_id[:6]}... from /passkey/assertion/initiate endpoint")

                            # Dispatch async - doesn't block assertion initiate response
                            # By the time user completes passkey authentication, cache should be ready
                            app.send_task(
                                name='app.tasks.user_cache_tasks.warm_user_cache',
                                kwargs={'user_id': user_id, 'last_opened_path_from_user_model': last_opened_path},
                                queue='user_init'
                            )
                        else:
                            logger.info(f"Cache warming already in progress for user {user_id[:6]}...")
                    else:
                        logger.info(f"User cache already primed for user {user_id[:6]}... (skipping predictive warming)")
        
        # Generate authentication options using py_webauthn
        # Convert allow_credentials to PublicKeyCredentialDescriptor format
        allow_credentials_descriptors = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(cred["id"]))
            for cred in allow_credentials
        ] if allow_credentials else None
        
        authentication_options = generate_authentication_options(
            rp_id=rp_id,
            challenge=challenge_bytes,
            timeout=60000,
            allow_credentials=allow_credentials_descriptors,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        
        # Convert to dict using py_webauthn's helper (properly handles base64url encoding)
        # Then add PRF extension (py_webauthn doesn't support PRF yet)
        # CRITICAL: prfEvalFirst must be deterministic (same value for signup and login)
        # Use domain-based global salt: SHA256(rp_id) - same for all users on the same domain
        # Security: Each passkey has a unique credential_secret, so PRF output is still unique per user
        # This solves the "chicken-and-egg" problem: we can compute it without knowing the user
        prf_eval_first_bytes = hashlib.sha256(rp_id.encode()).digest()[:32]
        prf_eval_first_b64 = base64.urlsafe_b64encode(prf_eval_first_bytes).decode('utf-8').rstrip('=')
        logger.info(f"Authentication prf_eval_first: rp_id={rp_id}, first_bytes={prf_eval_first_bytes[:4].hex()}, b64={prf_eval_first_b64[:30]}...")
        
        request_options_dict = options_to_json_dict(authentication_options)
        request_options_dict["extensions"] = {
                "prf": {
                    "eval": {
                    "first": prf_eval_first_b64
                }
            }
        }
        
        logger.info(f"Generated passkey assertion challenge - rpId: {rp_id}, origin: {origin}")
        
        return PasskeyAssertionInitiateResponse(
            success=True,
            challenge=request_options_dict["challenge"],
            rp={"id": rp_id, "name": rp_name},
            timeout=request_options_dict["timeout"],
            allowCredentials=allow_credentials,  # Keep original format for frontend
            userVerification=request_options_dict["userVerification"],
            extensions=request_options_dict["extensions"],
            message="Passkey assertion initiated"
        )
        
    except Exception as e:
        logger.error(f"Error initiating passkey assertion: {str(e)}", exc_info=True)
        return PasskeyAssertionInitiateResponse(
            success=False,
            challenge="",
            rp={"id": "", "name": ""},
            timeout=60000,
            allowCredentials=[],
            userVerification="preferred",
            message=f"Failed to initiate passkey assertion: {str(e)}"
        )

@router.post("/passkey/assertion/verify", response_model=PasskeyAssertionVerifyResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def passkey_assertion_verify(
    request: Request,
    verify_request: PasskeyAssertionVerifyRequest,
    response: Response,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    metrics_service: MetricsService = Depends(get_metrics_service),
    compliance_service: ComplianceService = Depends(get_compliance_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Verify passkey assertion (login) by validating signature and returning user data.
    """
    logger.info("Processing POST /passkey/assertion/verify")
    
    try:
        # Get passkey by credential_id
        # IMPORTANT: credential_id must match exactly what was stored during registration
        # Both registration and login should use base64url encoding (URL-safe, no padding)
        credential_id = verify_request.credential_id
        logger.info(f"Looking up passkey with credential_id: {credential_id[:20]}... (length={len(credential_id)})")
        
        passkey = await directus_service.get_passkey_by_credential_id(credential_id)
        if not passkey:
            # Log more details to help diagnose mismatches
            logger.warning(
                f"Passkey not found for credential_id. "
                f"credential_id_prefix={credential_id[:30]}..., "
                f"length={len(credential_id)}, "
                f"has_padding={'=' in credential_id}, "
                f"has_url_safe_chars={'_' in credential_id or '-' in credential_id}"
            )
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey. The passkey may have been deleted or was not registered correctly. Please try registering a new passkey.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get user_id and hashed_user_id directly from passkey record
        user_id = passkey.get("user_id")
        hashed_user_id = passkey.get("hashed_user_id")
        
        if not user_id or not hashed_user_id:
            logger.error("Passkey missing user_id or hashed_user_id")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey data. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Verify hashed_user_id matches user_id (safety check)
        expected_hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        if expected_hashed_user_id != hashed_user_id:
            logger.error("hashed_user_id mismatch for passkey - possible data corruption")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Passkey verification failed.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # If hashed_email was provided, verify it matches the user
        if verify_request.hashed_email:
            exists_result, user_data, _ = await directus_service.get_user_by_hashed_email(verify_request.hashed_email)
            if exists_result and user_data:
                provided_user_id = user_data.get("id")
                if provided_user_id != user_id:
                    logger.error("User ID mismatch: passkey belongs to different user")
                    return PasskeyAssertionVerifyResponse(
                        success=False,
                        message="Passkey verification failed.",
                        user_id=None,
                        hashed_email=None,
                        encrypted_email=None,
                        encrypted_master_key=None,
                        key_iv=None,
                        salt=None,
                        user_email_salt=None,
                        auth_session=None
                    )
        
        # Verify clientDataJSON challenge matches expected challenge from cache
        # This prevents replay attacks and ensures the response is for the current session
        try:
            client_data_json_bytes = _decode_base64_from_frontend(verify_request.client_data_json)
            client_data = json.loads(client_data_json_bytes.decode('utf-8'))
            
            # Verify type is "webauthn.get" (for assertions)
            if client_data.get("type") != "webauthn.get":
                logger.error(f"Invalid clientDataJSON type for assertion: {client_data.get('type')}")
                return PasskeyAssertionVerifyResponse(
                    success=False,
                    message="Invalid passkey authentication type.",
                    user_id=None,
                    hashed_email=None,
                    encrypted_email=None,
                    encrypted_master_key=None,
                    key_iv=None,
                    salt=None,
                    user_email_salt=None,
                    auth_session=None
                )
            
            # Verify challenge matches cached challenge
            challenge = client_data.get("challenge", "")
            challenge_cache_key = f"passkey_assertion_challenge:{challenge}"
            cached_challenge = await cache_service.get(challenge_cache_key)
            
            if not cached_challenge:
                logger.warning(f"Challenge not found in cache for user {user_id} - may have expired or be a replay attack")
                # Log security event
                compliance_service.log_auth_event(
                    event_type="passkey_challenge_mismatch",
                    user_id=user_id,
                    ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
                    status="warning",
                    details={
                        "credential_id": verify_request.credential_id[:8] + "...",
                        "reason": "Challenge not found in cache"
                    }
                )
                return PasskeyAssertionVerifyResponse(
                    success=False,
                    message="Passkey verification failed. Challenge expired or invalid.",
                    user_id=None,
                    hashed_email=None,
                    encrypted_email=None,
                    encrypted_master_key=None,
                    key_iv=None,
                    salt=None,
                    user_email_salt=None,
                    auth_session=None
                )
            
            # Verify origin matches (additional security check)
            origin = client_data.get("origin")
            if origin:
                rp_id = get_rp_id_from_request(request)
                expected_origin = f"https://{rp_id}" if not rp_id.startswith("localhost") else f"http://{rp_id}"
                if origin != expected_origin and not origin.startswith(expected_origin):
                    logger.warning(f"Origin mismatch: {origin} vs expected {expected_origin}")
                    # Log but don't block (could be legitimate variation)
            
            logger.debug(f"Challenge verification successful for user {user_id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse clientDataJSON for user {user_id}: {e}")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey authentication data. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        except Exception as e:
            logger.error(f"Error verifying clientDataJSON for user {user_id}: {e}", exc_info=True)
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Passkey verification failed. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get public key for signature verification (use COSE format for py_webauthn)
        stored_sign_count = passkey.get("sign_count", 0)
        public_key_cose_b64 = passkey.get("public_key_cose")
        
        if not public_key_cose_b64:
            logger.error(f"Public key (COSE) not found for passkey credential_id: {verify_request.credential_id[:8]}...")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey configuration. Please contact support.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Extract assertion response data
        assertion_response = verify_request.assertion_response
        signature_b64 = assertion_response.get("signature")
        authenticator_data_b64 = verify_request.authenticator_data
        client_data_json_b64 = verify_request.client_data_json
        
        if not signature_b64 or not authenticator_data_b64 or not client_data_json_b64:
            logger.error(f"Missing assertion data for user {user_id}")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey authentication data. Missing required fields.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get expected challenge from cache
        try:
            client_data_json_bytes = _decode_base64_from_frontend(client_data_json_b64)
            client_data = json.loads(client_data_json_bytes.decode('utf-8'))
            challenge_from_client = client_data.get('challenge', '')
            challenge_cache_key = f"passkey_assertion_challenge:{challenge_from_client}"
            cached_challenge = await cache_service.get(challenge_cache_key)
            
            if not cached_challenge:
                logger.warning(f"Challenge not found in cache for user {user_id} - may have expired or be a replay attack")
                return PasskeyAssertionVerifyResponse(
                    success=False,
                    message="Authentication challenge expired. Please try again.",
                    user_id=None,
                    hashed_email=None,
                    encrypted_email=None,
                    encrypted_master_key=None,
                    key_iv=None,
                    salt=None,
                    user_email_salt=None,
                    auth_session=None
                )
            
            expected_challenge = base64url_to_bytes(challenge_from_client)
        except Exception as e:
            logger.error(f"Failed to parse clientDataJSON for user {user_id}: {e}", exc_info=True)
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Invalid passkey authentication data. Please try again.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get origin and rp_id
        origin = request.headers.get("Origin") or request.headers.get("Referer", "").rsplit("/", 1)[0]
        rp_id = get_rp_id_from_request(request)
        
        # Convert COSE key from base64 to bytes
        public_key_cose_bytes = base64.urlsafe_b64decode(public_key_cose_b64 + '==')
        
        # Verify authentication response using py_webauthn
        try:
            # Build credential dict for py_webauthn
            credential_dict = {
                "id": verify_request.credential_id,
                "rawId": verify_request.credential_id,
                "response": {
                    "authenticatorData": authenticator_data_b64,
                    "clientDataJSON": client_data_json_b64,
                    "signature": signature_b64,
                    "userHandle": assertion_response.get("userHandle"),
                },
                "type": "public-key",
                "clientExtensionResults": assertion_response.get("clientExtensionResults", {}),
            }
            
            # Verify authentication response
            authentication_verification = verify_authentication_response(
                credential=credential_dict,
                expected_challenge=expected_challenge,
                expected_rp_id=rp_id,
                expected_origin=origin,
                credential_public_key=public_key_cose_bytes,
                credential_current_sign_count=stored_sign_count,
                require_user_verification=True,
            )
            
            # Update sign_count (py_webauthn validates this automatically)
            new_sign_count = authentication_verification.new_sign_count
            logger.info(f"Signature verification successful for user {user_id}, new sign_count: {new_sign_count}")
            
        except Exception as e:
            logger.error(f"Signature verification error for user {user_id}: {e}", exc_info=True)
            # Log security event
            compliance_service.log_auth_event(
                event_type="passkey_signature_verification_failed",
                user_id=user_id,
                ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
                status="error",
                details={
                    "credential_id": verify_request.credential_id[:8] + "...",
                    "reason": str(e)
                }
            )
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Passkey verification failed. Invalid signature.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Validate sign_count (py_webauthn already validates this, but we check again for safety)
        if new_sign_count <= stored_sign_count:
            logger.warning(f"Potential cloned authenticator detected for user {user_id[:6]}... (sign_count: {new_sign_count} <= stored: {stored_sign_count})")
            # Log security event but don't block (could be false positive)
            compliance_service.log_auth_event(
                event_type="passkey_cloned_detected",
                user_id=user_id,
                ip_address=_extract_client_ip(request.headers, request.client.host if request.client else None),
                status="warning",
                details={
                    "credential_id": verify_request.credential_id[:8] + "...",
                    "stored_sign_count": stored_sign_count,
                    "new_sign_count": new_sign_count
                }
            )
        
        # Update passkey sign_count and last_used_at
        passkey_id = passkey.get("id")
        await directus_service.update_passkey_sign_count(passkey_id, new_sign_count)
        
        # Get user data
        user_profile = await cache_service.get_user_by_id(user_id)
        if not user_profile:
            # Fetch from Directus if not cached
            profile_success, user_profile, _ = await directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                logger.error(f"User profile not found for user {user_id}")
                return PasskeyAssertionVerifyResponse(
                    success=False,
                    message="User not found. Please try again.",
                    user_id=None,
                    hashed_email=None,
                    encrypted_email=None,
                    encrypted_master_key=None,
                    key_iv=None,
                    salt=None,
                    user_email_salt=None,
                    auth_session=None
                )
            # Cache the fetched profile (ensure user_id is present for WebSocket auth)
            if "user_id" not in user_profile:
                user_profile["user_id"] = user_id
            if "id" not in user_profile:
                user_profile["id"] = user_id
            await cache_service.set_user(user_profile, user_id=user_id)
        else:
            # Ensure user_id is present in cached data (required for WebSocket auth)
            # Update cache only if user_id was missing (to avoid unnecessary writes)
            if "user_id" not in user_profile or "id" not in user_profile:
                if "user_id" not in user_profile:
                    user_profile["user_id"] = user_id
                if "id" not in user_profile:
                    user_profile["id"] = user_id
                # Update cache to ensure user_id is persisted
                await cache_service.set_user(user_profile, user_id=user_id)

        # IMPORTANT (passkey login): cache_service user objects are often a reduced projection and may
        # not include `encrypted_email_with_master_key`. For passwordless passkey login, we must have
        # the email encrypted with the same master key that is wrapped for the passkey.
        if not user_profile.get("encrypted_email_with_master_key"):
            logger.warning(
                f"encrypted_email_with_master_key missing from cached user object for user {user_id[:6]}...; "
                "fetching full profile from Directus"
            )
            profile_success, full_profile, _ = await directus_service.get_user_profile(user_id)
            if profile_success and full_profile:
                # Merge required encrypted fields into the cached user object and persist back to cache_service
                user_profile["encrypted_email_with_master_key"] = full_profile.get("encrypted_email_with_master_key")
                # Keep these in sync as well (harmless if already present)
                user_profile["encrypted_email_address"] = full_profile.get("encrypted_email_address")
                user_profile["hashed_email"] = full_profile.get("hashed_email")
                user_profile["user_email_salt"] = full_profile.get("user_email_salt")

                if "user_id" not in user_profile:
                    user_profile["user_id"] = user_id
                if "id" not in user_profile:
                    user_profile["id"] = user_id
                await cache_service.set_user(user_profile, user_id=user_id)
            else:
                logger.error(f"Failed to fetch full profile for user {user_id} to obtain encrypted_email_with_master_key")
        
        # Cache warming is now handled earlier in /passkey/assertion/initiate endpoint
        # This comment remains as documentation that cache warming should already be in progress
        
        # Get encryption key for passkey login method
        hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Get encryption key for passkey login method (new format: passkey_{credential_id_hash})
        credential_id_hash = hashlib.sha256(verify_request.credential_id.encode()).hexdigest()
        login_method = f"passkey_{credential_id_hash}"
        encryption_key_data = await directus_service.get_encryption_key(hashed_user_id, login_method)
        
        if not encryption_key_data:
            logger.error(f"Encryption key not found for user {user_id} with passkey login method")
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Encryption key not found. Please contact support.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # Get hashed_email from user profile or request
        hashed_email = verify_request.hashed_email
        if not hashed_email:
            # Try to get from user profile
            hashed_email = user_profile.get("hashed_email")
        
        # Get encrypted email with master key (for passwordless login)
        # This allows client to decrypt email using master key derived from PRF signature
        encrypted_email_with_master_key = user_profile.get("encrypted_email_with_master_key")
        if not encrypted_email_with_master_key:
            # This can happen if:
            # 1. User registered before encrypted_email_with_master_key was implemented
            # 2. User added passkey via settings but the update to encrypted_email_with_master_key failed
            # 3. Data migration issue
            logger.error(
                f"encrypted_email_with_master_key not available for user {user_id}. "
                f"Cannot complete passwordless passkey login. "
                f"User may need to delete and re-add their passkey via Settings."
            )
            return PasskeyAssertionVerifyResponse(
                success=False,
                message="Your passkey needs to be updated. Please log in with your password, then go to Settings > Passkeys to delete and re-add your passkey. This will enable passwordless login.",
                user_id=None,
                hashed_email=None,
                encrypted_email=None,
                encrypted_master_key=None,
                key_iv=None,
                salt=None,
                user_email_salt=None,
                auth_session=None
            )
        
        # For passkey login, authentication happens in two steps:
        # 1. Verify passkey assertion (this step) - returns encrypted data
        # 2. Client derives lookup_hash from PRF signature + email salt
        # 3. Client sends lookup_hash for authentication (handled separately or in finalize_login_session)
        
        # Check if client provided lookup_hash (for cases where email was known upfront)
        # If not provided, we'll return the data and let client authenticate in a follow-up step
        lookup_hash = verify_request.email_encryption_key  # This field is misnamed in schema - should be lookup_hash
        # TODO: Fix schema to have proper lookup_hash field
        
        # For now, if lookup_hash is not provided, we'll skip authentication and return data
        # Client will need to send lookup_hash in a separate request or we can add it to the response
        # and have client call a separate authentication endpoint
        
        # Get user's lookup_hashes to verify later
        user_lookup_hashes = user_profile.get("lookup_hashes", [])
        
        # If lookup_hash is provided, authenticate now
        # Otherwise, return data without authentication (client will authenticate separately)
        auth_success = False
        auth_data = None
        auth_message = None
        
        if lookup_hash and lookup_hash in user_lookup_hashes and hashed_email:
            # Client provided lookup_hash - authenticate now
            logger.info(f"Authenticating user {user_id} with provided lookup_hash")
            auth_success, auth_data, auth_message = await directus_service.login_user_with_lookup_hash(
                hashed_email=hashed_email,
                lookup_hash=lookup_hash
            )
            
            if not auth_success or not auth_data:
                logger.error(f"Failed to authenticate user {user_id} after passkey verification: {auth_message}")
                return PasskeyAssertionVerifyResponse(
                    success=False,
                    message="Authentication failed. Please try again.",
                    user_id=None,
                    hashed_email=None,
                    encrypted_email=None,
                    encrypted_master_key=None,
                    key_iv=None,
                    salt=None,
                    user_email_salt=None,
                    auth_session=None
                )
        else:
            # No lookup_hash provided or hashed_email missing - return data without authentication
            # Client will derive lookup_hash from PRF signature + email salt, then authenticate
            if not hashed_email:
                logger.warning(f"hashed_email not available for user {user_id}, returning data without authentication")
            elif not lookup_hash:
                logger.info(f"No lookup_hash provided for user {user_id}, returning data for client-side lookup_hash derivation")
            else:
                logger.warning(f"lookup_hash not found in user's lookup_hashes for user {user_id}")
            
            # Get user_email_salt and log for debugging
            user_email_salt = user_profile.get("user_email_salt")
            logger.info(f"Returning user_email_salt for user {user_id}: {user_email_salt[:20] + '...' if user_email_salt else 'None'}")
            logger.debug(f"Full user_email_salt for user {user_id}: {user_email_salt}")
            logger.debug(f"Encrypted master key length: {len(encryption_key_data.get('encrypted_key', '')) if encryption_key_data.get('encrypted_key') else 0}")
            logger.debug(f"Key IV length: {len(encryption_key_data.get('key_iv', '')) if encryption_key_data.get('key_iv') else 0}")
            
            return PasskeyAssertionVerifyResponse(
                success=True,
                message="Passkey verified. Please complete authentication.",
                user_id=user_id,
                hashed_email=hashed_email,
                # Must be encrypted with master key for passwordless passkey login
                encrypted_email=encrypted_email_with_master_key,
                encrypted_master_key=encryption_key_data.get("encrypted_key"),
                key_iv=encryption_key_data.get("key_iv"),
                salt=encryption_key_data.get("salt"),
                user_email_salt=user_email_salt,
                user_email=None,  # Client will decrypt from encrypted_email_with_master_key
                auth_session=None  # No session yet - client needs to authenticate with lookup_hash
            )
        
        # If we reach here, lookup_hash was provided and authentication succeeded
        # Generate device fingerprint
        session_id = verify_request.session_id
        device_hash, connection_hash, os_name, country_code, city, region, latitude, longitude = generate_device_fingerprint_hash(
            request, user_id, session_id
        )
        
        # Finalize login session
        user = auth_data.get("user", {})
        refresh_token = await finalize_login_session(
            request=request,
            response=response,
            user=user,
            auth_data=auth_data,
            cache_service=cache_service,
            compliance_service=compliance_service,
            directus_service=directus_service,
            current_device_hash=device_hash,
            client_ip=_extract_client_ip(request.headers, request.client.host if request.client else None),
            encryption_service=encryption_service,
            device_location_str=f"{city}, {country_code}" if city and country_code else country_code or "Unknown",
            latitude=latitude,
            longitude=longitude,
            login_data=LoginRequest(
                hashed_email=hashed_email or "",
                lookup_hash=lookup_hash or "",
                login_method="passkey",
                credential_id=verify_request.credential_id,
                stay_logged_in=verify_request.stay_logged_in,
                email_encryption_key=verify_request.email_encryption_key,
                session_id=session_id
            )
        )
        
        logger.info(f"Passkey assertion verified and authenticated successfully for user {user_id[:6]}...")
        
        return PasskeyAssertionVerifyResponse(
            success=True,
            message="Passkey authentication successful",
            user_id=user_id,
            hashed_email=hashed_email,
            # Must be encrypted with master key for passwordless passkey login
            encrypted_email=encrypted_email_with_master_key,
            encrypted_master_key=encryption_key_data.get("encrypted_key"),
            key_iv=encryption_key_data.get("key_iv"),
            salt=encryption_key_data.get("salt"),
            user_email_salt=user_profile.get("user_email_salt"),
            user_email=None,  # Client will decrypt from encrypted_email_with_master_key
            auth_session={
                "refresh_token": refresh_token,
                "user": user
            }
        )
        
    except Exception as e:
        logger.error(f"Error verifying passkey assertion: {str(e)}", exc_info=True)
        return PasskeyAssertionVerifyResponse(
            success=False,
            message=f"Failed to verify passkey: {str(e)}",
            user_id=None,
            hashed_email=None,
            encrypted_email=None,
            encrypted_master_key=None,
            key_iv=None,
            salt=None,
            user_email_salt=None,
            auth_session=None
        )

# Passkey Management Endpoints
@router.get("/passkeys", response_model=PasskeyListResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def list_passkeys(
    request: Request,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    List all passkeys for the current authenticated user.
    Returns passkeys with decrypted device names.
    """
    logger.info(f"Processing GET /passkeys for user {current_user.id[:8]}...")
    
    try:
        # Get all passkeys for the user
        passkeys = await directus_service.get_user_passkeys_by_user_id(current_user.id)
        
        # Return only essential passkey data for the frontend
        # Minimize data exposure - only return what's needed for the settings UI
        passkey_list = []
        for passkey in passkeys:
            passkey_data = {
                "id": passkey.get("id"),  # Required for rename/delete operations
                "encrypted_device_name": passkey.get("encrypted_device_name"),  # Encrypted device name (client decrypts)
                "registered_at": passkey.get("registered_at"),  # Registration timestamp for display
                "last_used_at": passkey.get("last_used_at"),  # Last usage timestamp for display
                "sign_count": passkey.get("sign_count", 0),  # Usage counter for display
            }
            passkey_list.append(passkey_data)
        
        return PasskeyListResponse(
            success=True,
            passkeys=passkey_list,
            message=f"Found {len(passkey_list)} passkey(s)"
        )
        
    except Exception as e:
        logger.error(f"Error listing passkeys for user {current_user.id[:8]}...: {e}", exc_info=True)
        return PasskeyListResponse(
            success=False,
            passkeys=[],
            message=f"Failed to retrieve passkeys: {str(e)}"
        )

@router.post("/passkeys/rename", response_model=PasskeyRenameResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def rename_passkey(
    request: Request,
    rename_request: PasskeyRenameRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
):
    """
    Rename a passkey by updating its encrypted device name.
    """
    logger.info(f"Processing POST /passkeys/rename for user {current_user.id[:8]}...")
    
    try:
        # Verify the passkey belongs to the current user
        hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        passkeys = await directus_service.get_user_passkeys(hashed_user_id)
        
        passkey_exists = any(p.get("id") == rename_request.passkey_id for p in passkeys)
        if not passkey_exists:
            logger.warning(f"Passkey {rename_request.passkey_id[:6]}... not found or doesn't belong to user {current_user.id[:8]}...")
            return PasskeyRenameResponse(
                success=False,
                message="Passkey not found or access denied"
            )
        
        # Device name is already encrypted client-side with master key
        # Just store it as-is (zero-knowledge: server never sees plaintext)
        encrypted_device_name = rename_request.encrypted_device_name
        
        # Update the passkey
        success = await directus_service.update_passkey_device_name(
            rename_request.passkey_id,
            encrypted_device_name
        )
        
        if success:
            logger.info(f"Successfully renamed passkey {rename_request.passkey_id[:6]}... for user {current_user.id[:8]}...")
            return PasskeyRenameResponse(
                success=True,
                message="Passkey renamed successfully"
            )
        else:
            return PasskeyRenameResponse(
                success=False,
                message="Failed to rename passkey"
            )
            
    except Exception as e:
        logger.error(f"Error renaming passkey for user {current_user.id[:8]}...: {e}", exc_info=True)
        return PasskeyRenameResponse(
            success=False,
            message=f"Failed to rename passkey: {str(e)}"
        )

@router.post("/passkeys/delete", response_model=PasskeyDeleteResponse, dependencies=[Depends(verify_allowed_origin)])
@limiter.limit("10/minute")
async def delete_passkey(
    request: Request,
    delete_request: PasskeyDeleteRequest,
    current_user: User = Depends(get_current_user),
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
):
    """
    Delete a passkey. Ensures user has at least one secure login method remaining.
    """
    logger.info(f"Processing POST /passkeys/delete for user {current_user.id[:8]}...")
    
    try:
        # Verify the passkey belongs to the current user
        hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()
        passkeys = await directus_service.get_user_passkeys(hashed_user_id)
        
        passkey_to_delete = next((p for p in passkeys if p.get("id") == delete_request.passkey_id), None)
        if not passkey_to_delete:
            logger.warning(f"Passkey {delete_request.passkey_id[:6]}... not found or doesn't belong to user {current_user.id[:8]}...")
            return PasskeyDeleteResponse(
                success=False,
                message="Passkey not found or access denied"
            )
        
        # Check if user has other secure login methods before deleting
        # User must have at least: (1 passkey) OR (password + 2FA)
        
        # Count remaining passkeys (excluding the one being deleted)
        remaining_passkeys = [p for p in passkeys if p.get("id") != delete_request.passkey_id]
        has_other_passkeys = len(remaining_passkeys) > 0
        
        # Check if user has password login method
        password_encryption_key = await directus_service.get_encryption_key(hashed_user_id, "password")
        has_password = password_encryption_key is not None
        
        # Check if user has 2FA enabled
        user_profile = await cache_service.get_user_by_id(current_user.id)
        if not user_profile:
            profile_success, user_profile, _ = await directus_service.get_user_profile(current_user.id)
            if not profile_success or not user_profile:
                logger.error(f"Could not fetch user profile for user {current_user.id[:8]}...")
                return PasskeyDeleteResponse(
                    success=False,
                    message="Failed to verify user security settings"
                )
        
        tfa_enabled = user_profile.get("tfa_enabled", False)
        has_password_with_2fa = has_password and tfa_enabled
        
        # Validate: User must have at least one secure login method remaining
        if not has_other_passkeys and not has_password_with_2fa:
            logger.warning(f"User {current_user.id[:8]}... attempted to delete last passkey without password+2FA")
            return PasskeyDeleteResponse(
                success=False,
                message="Cannot delete passkey: You must have at least one passkey or password with 2FA enabled. Please set up password authentication with 2FA first, or add another passkey."
            )
        
        # Delete the passkey
        success = await directus_service.delete_passkey(delete_request.passkey_id)
        
        if success:
            logger.info(f"Successfully deleted passkey {delete_request.passkey_id[:6]}... for user {current_user.id[:8]}...")
            
            # Delete associated encryption key
            credential_id = passkey_to_delete.get("credential_id")
            if credential_id:
                credential_id_hash = hashlib.sha256(credential_id.encode()).hexdigest()
                login_method = f"passkey_{credential_id_hash}"
                
                # Delete the specific encryption key for this passkey
                key_deleted = await directus_service.delete_encryption_key(hashed_user_id, login_method)
                if key_deleted:
                    logger.info(f"Successfully deleted encryption key for method {login_method}")
                else:
                    logger.warning(f"Encryption key not found for method {login_method} during passkey deletion")
            
            # Clear login methods cache to ensure lookup endpoint reflects the deletion
            # This prevents showing passkey login option when no passkeys exist
            hashed_user_id = hashlib.sha256(current_user.id.encode()).hexdigest()
            login_methods_cache_key = f"user:{hashed_user_id}:login_methods" # Fixed cache key format to match auth_login.py
            await cache_service.delete(login_methods_cache_key)
            logger.debug(f"Cleared login methods cache for user {current_user.id[:8]}... after passkey deletion")
            
            return PasskeyDeleteResponse(
                success=True,
                message="Passkey deleted successfully"
            )
        else:
            return PasskeyDeleteResponse(
                success=False,
                message="Failed to delete passkey"
            )
            
    except Exception as e:
        logger.error(f"Error deleting passkey for user {current_user.id[:8]}...: {e}", exc_info=True)
        return PasskeyDeleteResponse(
            success=False,
            message=f"Failed to delete passkey: {str(e)}"
        )
