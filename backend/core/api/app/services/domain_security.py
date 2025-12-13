"""
Domain Security Service

This service manages domain validation and security checks for both email signup 
and self-hosting scenarios. It implements domain validation rules and security
policies to ensure compliance with platform requirements.
"""

import os
import logging
import re
import hashlib
import base64
from typing import List, Set, Optional, Tuple, Dict
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Key derivation from stable codebase constants (same as encryption script)
# These constants are used elsewhere in the codebase, so removing them would break other functionality
_KEY_DOMAIN = "openmates.org"
_KEY_API_TITLE = "OpenMates API"

# Salt derivation: Use a hash of stable constants for tamper resistance
# This makes the salt less obvious than a plain base64 string, while remaining stable
# across code changes. The salt is derived from stable constants only (not code structure).
def _derive_salt() -> bytes:
    """
    Derive salt from stable constants for tamper resistance.
    
    This creates a deterministic but non-obvious salt by hashing stable constants.
    The salt does NOT depend on code structure, so it remains stable across refactoring.
    
    Components:
    1. Stable codebase constants (domain, API title)
    2. A fixed purpose identifier
    
    This approach makes it slightly harder to derive the key without reading the code,
    while ensuring the salt remains stable across code changes.
    
    Returns:
        16-byte salt for PBKDF2 key derivation
    """
    # Component 1: Stable constants (used elsewhere in codebase)
    constants = (_KEY_DOMAIN + _KEY_API_TITLE).encode('utf-8')
    
    # Component 2: Fixed purpose identifier (stable, doesn't change with code)
    purpose = "domain_security_encryption_salt_v1".encode('utf-8')
    
    # Combine and hash to create final salt (deterministic but less obvious)
    combined = constants + purpose
    salt = hashlib.sha256(combined).digest()[:16]  # 16 bytes for salt
    
    return salt


def _derive_encryption_key() -> bytes:
    """
    Derive encryption key from stable codebase constants.
    
    This function must match the key derivation in scripts/encrypt_domain_security.py
    exactly to ensure encrypted files can be decrypted.
    
    The key derivation uses:
    - Stable codebase constants (domain, API title)
    - A salt derived from stable constants (for tamper resistance)
    - PBKDF2 with 100,000 iterations
    
    Returns:
        32-byte key for Fernet encryption
    """
    # Combine stable constants to create a password (must match encryption script)
    password = (_KEY_DOMAIN + _KEY_API_TITLE).encode('utf-8')
    
    # Derive salt from stable constants (must match encryption script)
    salt = _derive_salt()
    
    # Derive key using PBKDF2 (100,000 iterations - must match encryption script)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password))
    return key

# These will be loaded from encrypted files at runtime
# These are module-level variables that get populated when the service loads its config
_ALLOWED_DOMAIN: Optional[str] = None
_PLATFORM_NAME: Optional[str] = None
_SUSPICIOUS_PATTERNS: List[str] = []

# Resilience: Track validation state to detect tampering
_VALIDATION_ENABLED = True
_CONFIG_LOADED_FLAG = False


class DomainSecurityService:
    """
    Service for managing domain security validation and compliance checks.
    
    The service loads security configuration and provides methods to:
    - Check domain compliance with platform policies
    - Validate domain naming conventions
    - Detect suspicious domain patterns
    - Validate domains at server startup and during signup
    """
    
    def __init__(self, encryption_service: Optional[object] = None):
        """
        Initialize the domain security service.
        
        Args:
            encryption_service: Optional (kept for compatibility, not used for Fernet decryption)
        """
        # Note: encryption_service parameter kept for compatibility but not used
        # Fernet decryption uses key derivation from codebase constants
        self.restricted_domains: Set[str] = set()
        self.config_loaded = False
        
        # Resilience: Store file hashes to detect tampering
        self._file_hashes: Dict[str, str] = {}
        
        # Resilience: Track if validation is properly initialized
        self._validation_initialized = False
        
        # Paths to encrypted security configuration files
        # These should be in a location accessible to the server
        base_path = Path(os.getenv(
            "DOMAIN_SECURITY_CONFIG_DIR",
            "/app/backend/core/api/app/services"
        ))
        
        self.restricted_domains_path = Path(os.getenv(
            "DOMAIN_SECURITY_RESTRICTED_PATH",
            str(base_path / "domain_security_restricted.encrypted")
        ))
        
        self.allowed_domain_path = Path(os.getenv(
            "DOMAIN_SECURITY_ALLOWED_PATH",
            str(base_path / "domain_security_allowed.encrypted")
        ))
        
        self.suspicious_patterns_path = Path(os.getenv(
            "DOMAIN_SECURITY_PATTERNS_PATH",
            str(base_path / "domain_security_patterns.encrypted")
        ))
        
        logger.debug(f"DomainSecurityService initialized. Config paths: restricted={self.restricted_domains_path}, allowed={self.allowed_domain_path}, patterns={self.suspicious_patterns_path}")
    
    def _compute_file_hash(self, file_path: Path) -> str:
        """
        Compute SHA256 hash of a file for integrity checking.
        
        Args:
            file_path: Path to file
            
        Returns:
            Hex digest of file hash
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _load_encrypted_file(self, file_path: Path, description: str) -> Tuple[str, str]:
        """
        Load and decrypt an encrypted configuration file using Fernet.
        
        Args:
            file_path: Path to encrypted file
            description: Description of the file (for error messages)
            
        Returns:
            Tuple of (decrypted_content: str, file_hash: str)
            
        Raises:
            SystemExit: If file is missing or cannot be decrypted
        """
        if not file_path.exists():
            logger.critical(
                f"CRITICAL: Encrypted {description} file not found at {file_path}. "
                "Server files missing. Server cannot start without the configuration."
            )
            raise SystemExit("Server files missing")
        
        try:
            # Compute file hash for integrity checking (resilience measure)
            file_hash = self._compute_file_hash(file_path)
            
            # Read encrypted file (binary format)
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                logger.critical(
                    f"CRITICAL: Encrypted {description} file is empty at {file_path}. "
                    "Server files missing."
                )
                raise SystemExit("Server files missing")
            
            # Derive encryption key (must match encryption script)
            key = _derive_encryption_key()
            fernet = Fernet(key)
            
            try:
                # Decrypt the content
                decrypted_data = fernet.decrypt(encrypted_data).decode('utf-8')
            except Exception as decrypt_error:
                logger.critical(
                    f"CRITICAL: Failed to decrypt {description}: {decrypt_error}. "
                    "Server files missing. Encrypted files may be corrupted or encrypted with different key."
                )
                raise SystemExit("Server files missing")
            
            if not decrypted_data:
                logger.critical(
                    f"CRITICAL: Failed to decrypt {description} - empty result. "
                    "Server files missing."
                )
                raise SystemExit("Server files missing")
            
            return decrypted_data, file_hash
            
        except SystemExit:
            raise
        except Exception as e:
            logger.critical(
                f"CRITICAL: Error loading {description} from {file_path}: {e}. "
                "Server files missing."
            )
            raise SystemExit("Server files missing")
    
    def load_security_config(self) -> bool:
        """
        Load all encrypted security configuration files from disk and decrypt them.
        
        Loads:
        1. Restricted domains list
        2. Allowed domain for platform name variations
        3. Suspicious pattern detection rules
        
        Returns:
            True if all configurations loaded successfully, False otherwise
            
        Raises:
            SystemExit: If any configuration file is missing (server must not start)
        """
        try:
            # Load restricted domains
            restricted_content, restricted_hash = self._load_encrypted_file(
                self.restricted_domains_path,
                "restricted domains configuration"
            )
            self._file_hashes['restricted'] = restricted_hash
            
            domains = []
            for line in restricted_content.strip().split('\n'):
                domain = line.strip().lower()
                if domain and not domain.startswith('#'):
                    domains.append(domain)
            
            self.restricted_domains = set(domains)
            logger.info(f"Loaded {len(self.restricted_domains)} restricted domains")
            
            # Load allowed domain (for platform name variations)
            allowed_content, allowed_hash = self._load_encrypted_file(
                self.allowed_domain_path,
                "allowed domain configuration"
            )
            self._file_hashes['allowed'] = allowed_hash
            
            # Parse allowed domain (should be single line, but handle multiple)
            allowed_lines = [line.strip().lower() for line in allowed_content.strip().split('\n') 
                           if line.strip() and not line.strip().startswith('#')]
            if allowed_lines:
                global _ALLOWED_DOMAIN
                _ALLOWED_DOMAIN = allowed_lines[0]  # Use first non-comment line
                logger.info(f"Loaded allowed domain: {_ALLOWED_DOMAIN}")
            else:
                logger.critical("CRITICAL: Allowed domain configuration is empty")
                raise SystemExit("Server files missing")
            
            # Load platform name (for pattern matching)
            # Extract platform name from allowed domain (everything before the TLD)
            if _ALLOWED_DOMAIN:
                parts = _ALLOWED_DOMAIN.split('.')
                if len(parts) >= 2:
                    global _PLATFORM_NAME
                    _PLATFORM_NAME = parts[0]  # Extract base name
                    logger.info(f"Extracted platform name: {_PLATFORM_NAME}")
            
            # Load suspicious patterns
            patterns_content, patterns_hash = self._load_encrypted_file(
                self.suspicious_patterns_path,
                "suspicious patterns configuration"
            )
            self._file_hashes['patterns'] = patterns_hash
            
            patterns = []
            for line in patterns_content.strip().split('\n'):
                pattern = line.strip()
                if pattern and not pattern.startswith('#'):
                    patterns.append(pattern)
            
            global _SUSPICIOUS_PATTERNS
            _SUSPICIOUS_PATTERNS = patterns
            logger.info(f"Loaded {len(_SUSPICIOUS_PATTERNS)} suspicious patterns")
            
            # Resilience: Mark configuration as loaded and validation as initialized
            self.config_loaded = True
            self._validation_initialized = True
            global _CONFIG_LOADED_FLAG
            _CONFIG_LOADED_FLAG = True
            
            logger.info("Successfully loaded all domain security configurations")
            return True
            
        except SystemExit:
            raise
        except Exception as e:
            logger.critical(
                f"CRITICAL: Error loading domain security configurations: {e}. "
                "Server files missing."
            )
            raise SystemExit("Server files missing")
    
    def _normalize_domain(self, domain: str) -> str:
        """
        Normalize a domain for comparison (lowercase, strip whitespace).
        
        Args:
            domain: Domain string to normalize
            
        Returns:
            Normalized domain string
        """
        return domain.strip().lower()
    
    def _contains_platform_name(self, domain: str) -> bool:
        """
        Check if a domain contains the platform name (case-insensitive).
        
        Args:
            domain: Domain to check
            
        Returns:
            True if domain contains the platform name, False otherwise
        """
        if not _PLATFORM_NAME:
            return False
        normalized = self._normalize_domain(domain)
        return _PLATFORM_NAME in normalized
    
    def _is_suspicious_pattern(self, domain: str) -> bool:
        """
        Check if a domain matches suspicious pattern detection rules.
        
        Args:
            domain: Domain to check
            
        Returns:
            True if domain appears to match suspicious patterns, False otherwise
        """
        if not _PLATFORM_NAME or not _SUSPICIOUS_PATTERNS:
            return False
        
        normalized = self._normalize_domain(domain)
        
        # Check if it's exactly the allowed domain (permitted) - do this first
        if _ALLOWED_DOMAIN and normalized == _ALLOWED_DOMAIN:
            return False
        
        # Check against suspicious patterns FIRST (before checking platform name)
        # This catches variations like "0penmates" or "open-mates" that don't contain
        # the exact platform name string but are still suspicious variations
        for pattern in _SUSPICIOUS_PATTERNS:
            try:
                if re.search(pattern, normalized, re.IGNORECASE):
                    return True
            except re.error as e:
                logger.warning(f"Invalid regex pattern in suspicious patterns: {pattern} - {e}")
                continue
        
        # If domain contains platform name but isn't exactly the allowed domain, it's restricted
        # This catches variations like alternative TLDs, separators, etc.
        # This is a fallback for domains that contain the platform name but didn't match patterns
        if _PLATFORM_NAME in normalized:
            return True
        
        return False
    
    def _verify_integrity(self) -> bool:
        """
        Verify integrity of configuration files (resilience measure).
        Detects if files have been tampered with.
        
        Returns:
            True if integrity check passes, False otherwise
        """
        try:
            # Check if files still exist and have same hashes
            if 'restricted' in self._file_hashes:
                if not self.restricted_domains_path.exists():
                    logger.warning("Resilience check: Restricted domains file missing")
                    return False
                current_hash = self._compute_file_hash(self.restricted_domains_path)
                if current_hash != self._file_hashes['restricted']:
                    logger.warning("Resilience check: Restricted domains file hash mismatch")
                    return False
            
            if 'allowed' in self._file_hashes:
                if not self.allowed_domain_path.exists():
                    logger.warning("Resilience check: Allowed domain file missing")
                    return False
                current_hash = self._compute_file_hash(self.allowed_domain_path)
                if current_hash != self._file_hashes['allowed']:
                    logger.warning("Resilience check: Allowed domain file hash mismatch")
                    return False
            
            if 'patterns' in self._file_hashes:
                if not self.suspicious_patterns_path.exists():
                    logger.warning("Resilience check: Suspicious patterns file missing")
                    return False
                current_hash = self._compute_file_hash(self.suspicious_patterns_path)
                if current_hash != self._file_hashes['patterns']:
                    logger.warning("Resilience check: Suspicious patterns file hash mismatch")
                    return False
            
            return True
        except Exception as e:
            logger.warning(f"Resilience check error: {e}")
            return False
    
    def is_domain_restricted(self, domain: str, check_patterns: bool = True) -> Tuple[bool, Optional[str]]:
        """
        Check if a domain is restricted by security policies.
        
        This method checks in order:
        1. If domain contains platform name - only the allowed domain is permitted
        2. Suspicious pattern detection (only applies if platform name is present)
        3. Domains in the encrypted restricted domains list (applies to all domains)
        
        Domains that have nothing to do with the platform name are only restricted
        if they appear in the encrypted restricted domains list.
        
        Args:
            domain: Domain to check
            check_patterns: Whether to check for suspicious patterns (default: True)
            
        Returns:
            Tuple of (is_restricted: bool, reason: Optional[str])
            - is_restricted: True if domain is restricted, False otherwise
            - reason: Human-readable reason for restriction, or None if not restricted
        """
        # Resilience: Verify validation is enabled and initialized
        if not _VALIDATION_ENABLED:
            logger.critical("CRITICAL: Domain validation disabled - security breach detected")
            return True, "Domain not supported"
        
        if not self._validation_initialized or not _CONFIG_LOADED_FLAG:
            logger.critical("CRITICAL: Domain validation not properly initialized")
            return True, "Domain not supported"
        
        # Resilience: Periodic integrity check (every 10th call, approximate)
        import random
        if random.random() < 0.1:  # 10% chance
            if not self._verify_integrity():
                logger.critical("CRITICAL: Configuration file integrity check failed")
                return True, "Domain not supported"
        
        if not domain:
            return False, None
        
        normalized = self._normalize_domain(domain)
        
        # Check 1: Platform name variations - only the allowed domain is permitted
        # Only check this if platform name and allowed domain are configured
        if _PLATFORM_NAME and _ALLOWED_DOMAIN and self._contains_platform_name(normalized):
            if normalized == _ALLOWED_DOMAIN:
                # This is the allowed domain
                return False, None
            else:
                # Contains platform name but isn't exactly the allowed domain
                return True, "Domain not supported"
        
        # Check 2: Suspicious pattern detection
        if check_patterns and self._is_suspicious_pattern(normalized):
            return True, "Domain not supported"
        
        # Check 3: Encrypted security configuration
        if not self.config_loaded:
            logger.warning(
                "Domain security configuration not loaded. Restricting all domains until configuration is loaded."
            )
            return True, "Domain not supported"
        
        if normalized in self.restricted_domains:
            return True, "Domain not supported"
        
        # Domain is not restricted
        return False, None
    
    def extract_domain_from_email(self, email: str) -> Optional[str]:
        """
        Extract domain from an email address.
        
        Args:
            email: Email address (e.g., "user@example.com")
            
        Returns:
            Domain string (e.g., "example.com") or None if invalid format
        """
        if not email or '@' not in email:
            return None
        
        parts = email.split('@')
        if len(parts) != 2:
            return None
        
        domain = parts[1].strip()
        if not domain:
            return None
        
        return domain
    
    def _is_production_environment(self) -> bool:
        """
        Check if the server is running in production environment.
        
        Production is detected by checking if PRODUCTION_URL is set.
        
        Returns:
            True if running in production, False if development
        """
        production_url = os.getenv("PRODUCTION_URL", "").strip()
        return bool(production_url)
    
    def _is_localhost_environment(self) -> bool:
        """
        Check if the server is running on localhost (development local).
        
        Returns:
            True if running on localhost, False if on actual domain
        """
        # Check PRODUCTION_URL first
        production_url = os.getenv("PRODUCTION_URL", "").strip()
        if production_url:
            # If PRODUCTION_URL is set, we're not on localhost
            return False
        
        # Check FRONTEND_URLS for localhost
        frontend_urls = os.getenv("FRONTEND_URLS", "").strip()
        if frontend_urls:
            # Parse URLs to check if any are localhost
            from urllib.parse import urlparse
            for url in frontend_urls.split(','):
                url = url.strip()
                if url:
                    try:
                        parsed = urlparse(url)
                        hostname = parsed.hostname or ""
                        # Check if it's localhost, 127.0.0.1, or ::1
                        if hostname.lower() in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                            return True
                        # If we have a real domain (not localhost), we're not on localhost
                        if hostname and hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                            return False
                    except Exception:
                        pass
        
        # Default: assume localhost if no URLs configured or all are localhost
        return True
    
    def _get_hosting_domain(self) -> Optional[str]:
        """
        Get the domain the server is hosting on.
        
        Returns:
            Domain string (e.g., "openmates.org") or None if localhost
        """
        # Try PRODUCTION_URL first
        production_url = os.getenv("PRODUCTION_URL", "").strip()
        if production_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(production_url)
                hostname = parsed.hostname
                if hostname and hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                    return hostname.lower()
            except Exception:
                pass
        
        # Try FRONTEND_URLS
        frontend_urls = os.getenv("FRONTEND_URLS", "").strip()
        if frontend_urls:
            try:
                from urllib.parse import urlparse
                for url in frontend_urls.split(','):
                    url = url.strip()
                    if url:
                        parsed = urlparse(url)
                        hostname = parsed.hostname
                        if hostname and hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                            return hostname.lower()
            except Exception:
                pass
        
        return None
    
    def validate_email_domain(self, email: str) -> Tuple[bool, Optional[str]]:
        """
        Validate if an email domain is allowed for signup.
        
        Behavior differs by environment:
        - Development on localhost: All domains allowed (except restricted)
        - Development on actual domain (e.g., app.dev.openmates.org): Only official domain allowed (except restricted)
        - Production: All domains allowed (except restricted)
        
        Args:
            email: Email address to validate
            
        Returns:
            Tuple of (is_allowed: bool, error_message: Optional[str])
            - is_allowed: True if email domain is allowed, False if restricted
            - error_message: Error message if restricted, None if allowed
        """
        domain = self.extract_domain_from_email(email)
        if not domain:
            return False, "Domain not supported"
        
        normalized = self._normalize_domain(domain)
        
        # Check if domain is restricted (applies to all environments)
        is_restricted, reason = self.is_domain_restricted(domain)
        if is_restricted:
            return False, reason or "Domain not supported"
        
        # Check environment-specific rules
        is_production = self._is_production_environment()
        is_localhost = self._is_localhost_environment()
        
        if is_production:
            # Production: Allow all domains (restricted ones already checked above)
            return True, None
        elif not is_localhost:
            # Development on actual domain: Only allow official domain
            # Example: app.dev.openmates.org → only openmates.org emails allowed
            if _ALLOWED_DOMAIN and normalized == _ALLOWED_DOMAIN:
                return True, None
            else:
                hosting_domain = self._get_hosting_domain()
                logger.info(
                    f"Development on domain ({hosting_domain}): Only official domain allowed. "
                    f"Blocked: {email}"
                )
                return False, "Domain not supported"
        else:
            # Development on localhost: Allow all domains (restricted ones already checked above)
            return True, None
    
    def validate_hosting_domain(self, domain: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Validate if a domain is allowed for self-hosting OpenMates.
        
        This method should be called at server startup to ensure the server
        is not running on a blocked domain.
        
        Args:
            domain: Domain to check. If None, attempts to detect from environment variables.
            
        Returns:
            Tuple of (is_allowed: bool, error_message: Optional[str])
            - is_allowed: True if domain is allowed, False if blocked
            - error_message: Error message if blocked, None if allowed
        """
        # If domain not provided, try to detect from environment
        if not domain:
            # Try PRODUCTION_URL first (production deployments)
            production_url = os.getenv("PRODUCTION_URL")
            if production_url:
                from urllib.parse import urlparse
                parsed = urlparse(production_url)
                domain = parsed.hostname
            
            # Fallback to FRONTEND_URLS (development)
            if not domain:
                frontend_urls = os.getenv("FRONTEND_URLS")
                if frontend_urls:
                    # Take first URL from comma-separated list
                    first_url = frontend_urls.split(',')[0].strip()
                    from urllib.parse import urlparse
                    parsed = urlparse(first_url)
                    domain = parsed.hostname
        
        # If still no domain, allow localhost/development
        if not domain or domain in ["localhost", "127.0.0.1"]:
            logger.debug("No domain detected or localhost - allowing (development mode)")
            return True, None
        
        # Validate the domain
        is_restricted, reason = self.is_domain_restricted(domain)
        if is_restricted:
            return False, reason or "Domain not supported"
        
        return True, None
