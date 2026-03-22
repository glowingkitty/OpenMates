#!/usr/bin/env python3
"""
Shared utility module for OpenMates backend inspection scripts.

Centralises duplicated helpers (logging setup, timestamp formatting, string
truncation, email censoring, hashing, ANSI colours, Vault API-key retrieval,
production API requests, and Vault encryption helpers) so that individual
inspect_*.py scripts can import them instead of re-implementing the same
logic.

Architecture context: See docs/claude/debugging.md
Tests: None (inspection utility, not production code)
"""

# ── Standard library ──────────────────────────────────────────────────────────
import base64
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote


if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

# ── Third-party (always available in the Docker image) ────────────────────────
import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ── Path bootstrap (same as every inspect script) ────────────────────────────
# Ensures `backend.*` and top-level imports work when running inside Docker.
if '/app/backend' not in sys.path:
    sys.path.insert(0, '/app/backend')
if '/app' not in sys.path:
    sys.path.insert(0, '/app')


# ═════════════════════════════════════════════════════════════════════════════
#  Section 1 — Logging
# ═════════════════════════════════════════════════════════════════════════════

# Logger names whose output we suppress to WARNING regardless of the script.
_NOISY_LOGGERS = (
    'httpx', 'httpcore', 'backend', 'aiohttp', 'botocore', 'boto3',
)


def configure_script_logging(
    name: str,
    *,
    level: int = logging.INFO,
    fmt: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    extra_suppress: Optional[List[str]] = None,
) -> logging.Logger:
    """Set up the standard logging configuration used by every inspect script.

    * Root logger → WARNING (silences library noise)
    * Script logger → *level* (default INFO)
    * Known noisy loggers → WARNING

    Args:
        name: Logger name for the calling script (e.g. ``'inspect_chat'``).
        level: Logging level for the script logger.
        fmt: Log format string.
        extra_suppress: Additional logger names to suppress to WARNING.

    Returns:
        A :class:`logging.Logger` instance for the calling script.
    """
    logging.basicConfig(level=logging.WARNING, format=fmt)

    script_logger = logging.getLogger(name)
    script_logger.setLevel(level)

    suppress = list(_NOISY_LOGGERS)
    if extra_suppress:
        suppress.extend(extra_suppress)
    for noisy in suppress:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return script_logger


# ═════════════════════════════════════════════════════════════════════════════
#  Section 2 — Timestamp formatting
# ═════════════════════════════════════════════════════════════════════════════

def format_timestamp(ts: Any, *, relative: bool = False) -> str:
    """Format a timestamp to a human-readable string.

    Handles Unix timestamps (``int`` / ``float``), ISO-8601 strings, and
    ``datetime`` objects.  Returns ``"N/A"`` for falsy / unparseable input.

    Args:
        ts: The timestamp value (int, float, str, datetime, or None).
        relative: If ``True`` and the timestamp is less than 24 h old, return a
            relative string such as ``"5 minutes ago"`` instead of the absolute
            representation.

    Returns:
        Formatted datetime string, relative string, or ``"N/A"``.
    """
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, datetime):
            dt = ts
        elif isinstance(ts, (int, float)):
            dt = _numeric_ts_to_datetime(float(ts))
        elif isinstance(ts, str):
            # Try numeric first (string-encoded timestamps are common)
            try:
                dt = _numeric_ts_to_datetime(float(ts))
            except ValueError:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            return str(ts)

        if relative:
            return _relative_or_absolute(dt)

        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _numeric_ts_to_datetime(ts_val: float) -> datetime:
    """Convert a numeric timestamp to ``datetime``.

    Handles:
    * Standard seconds-since-epoch.
    * Millisecond-precision timestamps (> 1 trillion).
    * Truncated / ambiguous values (returned with ``(Raw)`` suffix via caller).
    """
    # Millisecond-precision timestamps (e.g. JavaScript Date.now())
    if ts_val > 1_000_000_000_000:
        ts_val = ts_val / 1000.0
    return datetime.fromtimestamp(ts_val)


def _relative_or_absolute(dt: datetime) -> str:
    """Return a relative time string if < 24 h ago, otherwise absolute."""
    now = datetime.now()
    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 0:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
#  Section 3 — String helpers
# ═════════════════════════════════════════════════════════════════════════════

def truncate_string(s: Optional[str], max_len: int = 50) -> str:
    """Truncate *s* to *max_len* characters, appending ``"..."`` if shortened.

    Returns ``"N/A"`` when *s* is falsy.
    """
    if not s:
        return "N/A"
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def censor_email(email: Optional[str]) -> Optional[str]:
    """Censor an email address for privacy-safe display.

    Shows only the first 2 characters of the local part and the full domain.
    Example: ``"john.doe@example.com"`` → ``"jo***@example.com"``

    Returns the input unchanged when *email* is ``None`` or does not contain
    ``'@'``.
    """
    if not email or '@' not in email:
        return email
    local, domain = email.rsplit('@', 1)
    if len(local) <= 2:
        censored_local = local[0] + '***' if local else '***'
    else:
        censored_local = local[:2] + '***'
    return f"{censored_local}@{domain}"


# ── Email key recursive censoring (used by admin_debug_cli) ──────────────────

# Keys known to contain email addresses in API responses.
_EMAIL_KEYS = frozenset({'contact_email', 'email'})


def censor_emails_in_data(data: object) -> object:
    """Recursively walk a JSON-serialisable structure and censor all email fields.

    Modifies dicts **in-place** and returns the same reference for convenience.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key in _EMAIL_KEYS and isinstance(value, str):
                data[key] = censor_email(value)
            else:
                censor_emails_in_data(value)
    elif isinstance(data, list):
        for item in data:
            censor_emails_in_data(item)
    return data


# ═════════════════════════════════════════════════════════════════════════════
#  Section 4 — Hashing helpers
# ═════════════════════════════════════════════════════════════════════════════

def hash_email_sha256(email: str) -> str:
    """SHA-256 hash of an email address, returned as **base64**.

    The email is lowercased and stripped before hashing, matching the Directus
    lookup convention used throughout the backend.
    """
    email_bytes = email.strip().lower().encode('utf-8')
    return base64.b64encode(hashlib.sha256(email_bytes).digest()).decode('utf-8')


def hash_user_id(user_id: str) -> str:
    """SHA-256 hash of a user ID, returned as a **hex** string.

    Matches the hashing convention in ``user_daily_inspiration_methods.py`` and
    other backend services.
    """
    return hashlib.sha256(user_id.encode('utf-8')).hexdigest()


# ═════════════════════════════════════════════════════════════════════════════
#  Section 5 — ANSI colour codes
# ═════════════════════════════════════════════════════════════════════════════

# Bright variants (matching inspect_user_logs.py)
C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"
C_RED     = "\033[91m"
C_YELLOW  = "\033[93m"
C_GREEN   = "\033[92m"
C_CYAN    = "\033[96m"
C_BLUE    = "\033[94m"
C_MAGENTA = "\033[95m"
C_GRAY    = "\033[90m"


def colorize(text: str, color: str) -> str:
    """Wrap *text* in the given ANSI *color* code and reset.

    *color* should be one of the ``C_*`` constants above, or any raw ANSI
    escape sequence.

    Example::

        print(colorize("OK", C_GREEN))
    """
    return f"{color}{text}{C_RESET}"


# ═════════════════════════════════════════════════════════════════════════════
#  Section 6 — Production Admin Debug API
# ═════════════════════════════════════════════════════════════════════════════

# Base URLs for the Admin Debug API.
# See docs/architecture/admin-debug-api.md for endpoint details.
PROD_API_URL = "https://api.openmates.org/v1/admin/debug"
DEV_API_URL  = "https://api.dev.openmates.org/v1/admin/debug"

# HTTP timeout for production API requests (seconds).
PROD_API_TIMEOUT_SECONDS = 60.0


def get_base_url(use_dev: bool = False) -> str:
    """Return the Admin Debug API base URL (production or dev)."""
    return DEV_API_URL if use_dev else PROD_API_URL


async def get_api_key_from_vault() -> str:
    """Retrieve the admin API key from Vault.

    The ``SECRET__ADMIN__DEBUG_CLI__API_KEY`` env var is imported by
    ``vault-setup`` into ``kv/data/providers/admin`` with key
    ``debug_cli__api_key`` (following the ``SECRET__{PROVIDER}__{KEY}``
    convention).

    Returns:
        The admin API key string.

    Raises:
        SystemExit: If the key cannot be found in Vault.
    """
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()

    try:
        api_key = await secrets_manager.get_secret(
            "kv/data/providers/admin", "debug_cli__api_key"
        )
        if not api_key:
            print(
                "Error: Admin API key not found in Vault at "
                "kv/data/providers/admin (key: debug_cli__api_key)",
                file=sys.stderr,
            )
            print("", file=sys.stderr)
            print("To set up the admin API key:", file=sys.stderr)
            print(
                "1. Generate an API key for an admin user in the OpenMates app",
                file=sys.stderr,
            )
            print(
                "2. Add to your environment: SECRET__ADMIN__DEBUG_CLI__API_KEY=sk-api-xxxxx",
                file=sys.stderr,
            )
            print(
                "3. Restart the vault-setup container to import the secret",
                file=sys.stderr,
            )
            sys.exit(1)
        return api_key
    finally:
        await secrets_manager.aclose()


async def make_prod_api_request(
    endpoint: str,
    api_key: str,
    base_url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    method: str = "GET",
    entity_label: str = "Resource",
) -> Optional[Dict[str, Any]]:
    """Make an authenticated request to the Admin Debug API.

    Handles common HTTP error codes with the following strategy:

    * **401 / 403** — authentication / authorisation failures indicate a
      config problem, so ``sys.exit(1)`` is called immediately.
    * **404** — returns ``None`` so the caller (e.g. the auto-fallback
      resolution chain) can try the next server.
    * **Other errors / connection failures / timeouts** — prints a message
      and calls ``sys.exit(1)``.

    Args:
        endpoint: The API endpoint path (appended to *base_url*).
        api_key: Bearer token for authentication.
        base_url: One of :data:`PROD_API_URL` / :data:`DEV_API_URL`.
        params: Optional query parameters.
        method: HTTP method (``"GET"`` or ``"DELETE"``).
        entity_label: Human-readable label used in error messages
            (e.g. ``"Chat"`` or ``"Embed"``).

    Returns:
        Parsed JSON response body, or ``None`` if the server returned 404.

    Raises:
        SystemExit: On auth failures (401/403), non-404 HTTP errors,
            connection errors, or timeouts.
    """
    url = f"{base_url}/{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=PROD_API_TIMEOUT_SECONDS) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers, params=params)
            else:
                print(f"Error: Unsupported HTTP method {method}", file=sys.stderr)
                sys.exit(1)

            if response.status_code == 401:
                print("Error: Invalid or expired API key", file=sys.stderr)
                sys.exit(1)
            elif response.status_code == 403:
                print("Error: Admin privileges required", file=sys.stderr)
                sys.exit(1)
            elif response.status_code == 404:
                return None
            elif response.status_code != 200:
                print(
                    f"Error: API returned status {response.status_code}",
                    file=sys.stderr,
                )
                try:
                    print(response.json(), file=sys.stderr)
                except Exception:
                    print(response.text, file=sys.stderr)
                sys.exit(1)

            return response.json()

    except httpx.ConnectError:
        print(f"Error: Could not connect to {base_url}", file=sys.stderr)
        sys.exit(1)
    except httpx.TimeoutException:
        print(
            f"Error: Request timed out ({PROD_API_TIMEOUT_SECONDS}s)",
            file=sys.stderr,
        )
        sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
#  Section 7 — Vault / encryption helpers
# ═════════════════════════════════════════════════════════════════════════════
# These helpers are used by inspect_chat.py and inspect_embed.py for
# server-side Vault decryption of embed content.

async def resolve_vault_key_id(
    directus_service: "DirectusService",
    hashed_user_id: str,
) -> Optional[str]:
    """Resolve a ``hashed_user_id`` to a ``vault_key_id``.

    Two-step lookup:
    1. ``hashed_user_id`` → ``user_id``  (via ``user_passkeys`` table)
    2. ``user_id`` → ``vault_key_id``   (via Directus users API)

    Args:
        directus_service: A :class:`DirectusService` instance.
        hashed_user_id: SHA-256 hex hash of the user_id.

    Returns:
        The ``vault_key_id`` string, or ``None`` if the lookup fails.
    """
    try:
        user_id = await directus_service.get_user_id_from_hashed_user_id(
            hashed_user_id
        )
        if not user_id:
            return None

        user_data = await directus_service.get_user_fields_direct(
            user_id, ["vault_key_id"]
        )
        if user_data:
            return user_data.get("vault_key_id")
        return None
    except Exception:
        return None


async def decrypt_and_decode_toon(
    encryption_service: "EncryptionService",
    encrypted_content: str,
    vault_key_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Decrypt Vault-encrypted content and TOON-decode (or JSON-decode) it.

    Args:
        encryption_service: An :class:`EncryptionService` instance.
        encrypted_content: The Vault-encrypted ciphertext.
        vault_key_id: The user's Vault transit key ID.

    Returns:
        ``(decoded_dict, None)`` on success, or ``(None, error_message)`` on
        failure.
    """
    try:
        plaintext = await encryption_service.decrypt_with_user_key(
            encrypted_content, vault_key_id
        )
        if not plaintext:
            return None, "Decryption returned None"
    except Exception as e:
        return None, f"Decryption failed: {e}"

    # Try TOON first, fall back to JSON (legacy embeds).
    try:
        from toon_format import decode

        decoded = decode(plaintext)
        if isinstance(decoded, dict):
            return decoded, None
        return None, f"TOON decoded to {type(decoded).__name__}, expected dict"
    except Exception as toon_err:
        try:
            decoded = json.loads(plaintext)
            if isinstance(decoded, dict):
                return decoded, None
            return None, f"JSON decoded to {type(decoded).__name__}, expected dict"
        except Exception:
            return None, f"TOON decode failed: {toon_err}"


def describe_toon_value(value: Any) -> str:
    """Produce a type + size description for a single TOON field value.

    Does **not** expose actual content — only structural info.

    Examples: ``"str(142)"``, ``"list(5)"``, ``"dict(3 keys)"``, ``"null"``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"bool({value})"
    if isinstance(value, int):
        return f"int({value})"
    if isinstance(value, float):
        return f"float({value})"
    if isinstance(value, str):
        return f"str({len(value)})"
    if isinstance(value, list):
        return f"list({len(value)})"
    if isinstance(value, dict):
        return f"dict({len(value)} keys)"
    return f"{type(value).__name__}"


# ═════════════════════════════════════════════════════════════════════════════
#  Section 8 — Health-check timestamp helpers
# ═════════════════════════════════════════════════════════════════════════════
# Used by inspect_chat.py and inspect_embed.py to validate timestamp fields
# in health dashboards.

# Timestamps before this year are flagged as suspicious.
MIN_VALID_TIMESTAMP_YEAR = 2025


def parse_timestamp_value(ts: Any) -> Optional[datetime]:
    """Parse an integer / float / ISO timestamp into a ``datetime``.

    Returns ``None`` for empty / unparseable input.
    """
    if ts is None or ts == "":
        return None

    try:
        if isinstance(ts, (int, float)):
            numeric_ts = float(ts)
            if numeric_ts > 1_000_000_000_000:
                numeric_ts = numeric_ts / 1000.0
            return datetime.fromtimestamp(numeric_ts)

        if isinstance(ts, str):
            normalized = ts.strip()
            if not normalized:
                return None
            if normalized.isdigit():
                return datetime.fromtimestamp(float(normalized))
            return datetime.fromisoformat(normalized.replace('Z', '+00:00'))
    except Exception:
        return None

    return None


def collect_timestamp_issues(label: str, ts: Any, issues: List[str]) -> None:
    """Validate a timestamp and append a health issue string when invalid.

    * Missing / empty timestamps are silently skipped (not an issue).
    * Malformed values add a ``"<label> timestamp is malformed"`` entry.
    * Values before :data:`MIN_VALID_TIMESTAMP_YEAR` add a warning entry.

    Args:
        label: Human-readable label for the field (e.g. ``"embed.created_at"``).
        ts: The raw timestamp value.
        issues: Mutable list to which issue strings are appended.
    """
    if ts is None or ts == "":
        return

    parsed = parse_timestamp_value(ts)
    if not parsed:
        issues.append(f"{label} timestamp is malformed: {ts}")
        return

    if parsed.year < MIN_VALID_TIMESTAMP_YEAR:
        issues.append(
            f"{label} timestamp is before {MIN_VALID_TIMESTAMP_YEAR}: "
            f"{parsed.isoformat()}"
        )


# ═════════════════════════════════════════════════════════════════════════════
#  Section 9 — Auto-fallback resolution
# ═════════════════════════════════════════════════════════════════════════════
# Provides automatic server resolution for debug scripts.  The chain tries
# the local (dev) Directus first, then falls back to the production Admin
# Debug API — so callers don't need to specify ``--prod`` / ``--dev``.

# Admin user ID on the dev server (used for Directus queries).
DEV_ADMIN_USER_ID = "f21b15a5-a36a-4596-b014-0941b6882e96"

# Directus collection names keyed by logical entity type.
_ENTITY_COLLECTION_MAP: Dict[str, str] = {
    "chat": "chats",
    "embed": "embeds",
    "user": "directus_users",
    "issue": "issues",
}

# Admin Debug API endpoint prefixes keyed by logical entity type.
_ENTITY_API_ENDPOINT_MAP: Dict[str, str] = {
    "chat": "chats",
    "embed": "embeds",
    "user": "users",
    "issue": "issues",
}


def _is_dev_server() -> bool:
    """Return ``True`` if we are running on the dev server.

    Checks ``SERVER_ENVIRONMENT`` (set by Docker) — ``"development"`` (or
    absent) means dev; anything else (typically ``"production"``) means prod.
    """
    return os.getenv("SERVER_ENVIRONMENT", "development").lower() == "development"


async def _query_local_directus(
    entity_type: str,
    identifier: str,
) -> Optional[Dict[str, Any]]:
    """Try to find an entity in the local Directus instance.

    Imports :class:`DirectusService` at runtime to avoid import overhead
    when this helper is not called.

    Args:
        entity_type: One of ``"chat"``, ``"embed"``, ``"user"``, ``"issue"``.
        identifier: UUID or other identifier for the entity.

    Returns:
        The entity dict if found, otherwise ``None``.
    """
    collection = _ENTITY_COLLECTION_MAP.get(entity_type)
    if not collection:
        print(
            f"Error: Unknown entity type '{entity_type}'. "
            f"Expected one of: {', '.join(sorted(_ENTITY_COLLECTION_MAP))}",
            file=sys.stderr,
        )
        return None

    # Runtime imports to avoid startup overhead.
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    cache_service = CacheService()
    encryption_service = EncryptionService(cache_service=cache_service)
    directus_service = DirectusService(
        cache_service=cache_service,
        encryption_service=encryption_service,
    )

    try:
        # Build filter — users can be looked up by email (hashed) or by ID.
        if entity_type == "user" and "@" in identifier:
            hashed = hash_email_sha256(identifier)
            params: Dict[str, Any] = {
                "filter[hashed_email][_eq]": hashed,
                "fields": "*",
                "limit": 1,
            }
        else:
            params = {
                "filter[id][_eq]": identifier,
                "fields": "*",
                "limit": 1,
            }

        results = await directus_service.get_items(
            collection, params=params, no_cache=True,
        )
        if results and isinstance(results, list) and len(results) > 0:
            return results[0]
        return None
    except Exception as exc:
        # Log but do not crash — the fallback chain will try production next.
        print(
            f"  {colorize('Warning', C_YELLOW)}: Local Directus query failed: {exc}",
        )
        return None
    finally:
        await directus_service.close()


async def _query_prod_api(
    entity_type: str,
    identifier: str,
) -> Optional[Dict[str, Any]]:
    """Try to find an entity via the production Admin Debug API.

    Retrieves the API key from Vault, then makes a GET request to the
    appropriate endpoint.

    Args:
        entity_type: One of ``"chat"``, ``"embed"``, ``"user"``, ``"issue"``.
        identifier: UUID or other identifier for the entity.

    Returns:
        The response body dict if found, otherwise ``None``.
    """
    endpoint_prefix = _ENTITY_API_ENDPOINT_MAP.get(entity_type)
    if not endpoint_prefix:
        return None

    api_key = await get_api_key_from_vault()
    base_url = PROD_API_URL

    endpoint = f"{endpoint_prefix}/{identifier}"
    result = await make_prod_api_request(
        endpoint,
        api_key,
        base_url,
        entity_label=entity_type.capitalize(),
    )
    return result


class ResolveResult:
    """Container for the result of :func:`auto_resolve_entity`.

    Attributes:
        source: ``"local"`` or ``"prod"`` — which server provided the data.
        data: The entity payload (dict).
        api_key: The production API key (only set when ``source == "prod"``).
            Useful if the caller needs to make follow-up API requests.
    """

    __slots__ = ("source", "data", "api_key")

    def __init__(
        self,
        source: str,
        data: Dict[str, Any],
        api_key: Optional[str] = None,
    ) -> None:
        self.source = source
        self.data = data
        self.api_key = api_key

    def __repr__(self) -> str:  # noqa: D401
        return f"ResolveResult(source={self.source!r}, data_keys={list(self.data.keys())})"


async def auto_resolve_entity(
    entity_type: str,
    identifier: str,
) -> Optional[ResolveResult]:
    """Resolve an entity by trying local Directus first, then production API.

    This is the main entry point for the auto-fallback resolution chain.
    Scripts can call this instead of requiring ``--prod`` / ``--dev`` flags.

    Resolution order:
        1. **Local (dev) Directus** — direct DB query via :class:`DirectusService`.
        2. **Production Admin Debug API** — remote HTTP request.
        3. Returns ``None`` with a clear error if neither server has the entity.

    Args:
        entity_type: One of ``"chat"``, ``"embed"``, ``"user"``, ``"issue"``.
        identifier: UUID, email address, or other identifier for the entity.

    Returns:
        A :class:`ResolveResult` with ``source``, ``data``, and optionally
        ``api_key``; or ``None`` if the entity was not found on any server.
    """
    # Validate entity type early.
    if entity_type not in _ENTITY_COLLECTION_MAP:
        print(
            f"Error: Unknown entity type '{entity_type}'. "
            f"Expected one of: {', '.join(sorted(_ENTITY_COLLECTION_MAP))}",
            file=sys.stderr,
        )
        return None

    # ── Step 1: Try local Directus ────────────────────────────────────────
    print(f"  {colorize('Searching on dev server...', C_CYAN)}")
    local_data = await _query_local_directus(entity_type, identifier)

    if local_data:
        print(f"  {colorize('Found on dev server', C_GREEN)}")
        return ResolveResult(source="local", data=local_data)

    # ── Step 2: Try production API ────────────────────────────────────────
    print(f"  {colorize('Not found locally, trying production...', C_YELLOW)}")

    prod_data = await _query_prod_api(entity_type, identifier)

    if prod_data:
        print(f"  {colorize('Found on production server', C_GREEN)}")
        # Retrieve api_key again for the caller (cheap — cached in Vault).
        api_key = await get_api_key_from_vault()
        return ResolveResult(source="prod", data=prod_data, api_key=api_key)

    # ── Step 3: Not found anywhere ────────────────────────────────────────
    print(
        f"\n  {colorize('Error', C_RED)}: {entity_type.capitalize()} "
        f"'{identifier}' not found on dev or production server.",
    )
    return None


class ServerInfo:
    """Container for the result of :func:`auto_resolve_server`.

    Attributes:
        source: ``"local"`` or ``"prod"``.
        base_url: The Admin Debug API base URL for this server.
        api_key: The API key (only set when ``source == "prod"``).
    """

    __slots__ = ("source", "base_url", "api_key")

    def __init__(
        self,
        source: str,
        base_url: str,
        api_key: Optional[str] = None,
    ) -> None:
        self.source = source
        self.base_url = base_url
        self.api_key = api_key

    def __repr__(self) -> str:  # noqa: D401
        return f"ServerInfo(source={self.source!r}, base_url={self.base_url!r})"


async def auto_resolve_server() -> ServerInfo:
    """Determine which server we are on and return connection info.

    Simpler than :func:`auto_resolve_entity` — used by commands that don't
    look up a specific entity (e.g. ``logs``, ``errors``, ``health``).

    * If ``SERVER_ENVIRONMENT`` is ``"development"`` (or unset), returns
      the dev Admin Debug API URL.  No API key is needed because these
      commands will query local services directly.
    * Otherwise, returns the production URL with an API key from Vault.

    Returns:
        A :class:`ServerInfo` instance.
    """
    if _is_dev_server():
        print(f"  {colorize('Using dev server (local)', C_CYAN)}")
        return ServerInfo(source="local", base_url=DEV_API_URL)

    print(f"  {colorize('Using production server', C_YELLOW)}")
    api_key = await get_api_key_from_vault()
    return ServerInfo(source="prod", base_url=PROD_API_URL, api_key=api_key)


# ═════════════════════════════════════════════════════════════════════════════
#  Section 10 — Share Key Cryptography
# ═════════════════════════════════════════════════════════════════════════════
# Python implementations of the client-side share URL key blob decryption
# and AES-GCM content decryption, matching the TypeScript implementations in:
#   - frontend/packages/ui/src/services/shareEncryption.ts
#   - frontend/packages/ui/src/services/embedShareEncryption.ts
#   - frontend/packages/ui/src/services/cryptoService.ts
# Architecture context: See docs/architecture/share_chat.md
#                       See docs/architecture/zero-knowledge-storage.md
# Previously in: share_key_crypto.py

# --- Crypto constants ---
PBKDF2_ITERATIONS = 100_000
PBKDF2_KEY_LENGTH = 32  # 256 bits
AES_IV_LENGTH = 12  # 12 bytes for GCM mode
SHARE_SALT = b'openmates-share-v1'
PASSWORD_SALT_PREFIX = 'openmates-pwd-'

# Share URL patterns
# Format: https://<domain>/share/chat/<chatId>#key=<encryptedBlob>
# Format: https://<domain>/share/embed/<embedId>#key=<encryptedBlob>
CHAT_SHARE_URL_PATTERN = re.compile(
    r'(?:https?://[^/]+)?/share/chat/([a-f0-9-]+)#key=(.*)',
    re.IGNORECASE,
)
EMBED_SHARE_URL_PATTERN = re.compile(
    r'(?:https?://[^/]+)?/share/embed/([a-f0-9-]+)#key=(.*)',
    re.IGNORECASE,
)


def base64url_decode(s: str) -> bytes:
    """Decode a base64 URL-safe string (as produced by the frontend).

    Matches the frontend's base64UrlDecode exactly:
      replace '-' -> '+', '_' -> '/', then pad with '=' until len % 4 == 0.
    """
    s = s.replace('-', '+').replace('_', '/')
    while len(s) % 4:
        s += '='
    return base64.b64decode(s)


def _derive_key_from_id(entity_id: str) -> bytes:
    """Derive an AES-256 key from an entity ID using PBKDF2-HMAC-SHA256.

    Matches the frontend's deriveKeyFromChatId / deriveKeyFromEmbedId.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_KEY_LENGTH,
        salt=SHARE_SALT,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(entity_id.encode('utf-8'))


def _derive_key_from_password(password: str, entity_id: str) -> bytes:
    """Derive an AES-256 key from a password using entity ID as salt part.

    Matches the frontend's deriveKeyFromPassword.
    """
    salt = f'{PASSWORD_SALT_PREFIX}{entity_id}'.encode('utf-8')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode('utf-8'))


def _aes_gcm_decrypt(raw_bytes: bytes, key: bytes) -> bytes:
    """Decrypt AES-256-GCM data: IV (12 bytes) || ciphertext || tag (16 bytes)."""
    if len(raw_bytes) < AES_IV_LENGTH + 16:
        raise ValueError(
            f"Encrypted data too short: {len(raw_bytes)} bytes "
            f"(need at least {AES_IV_LENGTH + 16} for IV + GCM tag)"
        )
    iv = raw_bytes[:AES_IV_LENGTH]
    ciphertext_with_tag = raw_bytes[AES_IV_LENGTH:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext_with_tag, None)


def parse_share_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse a share URL to extract entity type, ID, and key blob.

    Returns:
        (entity_type, entity_id, key_blob) — entity_type is 'chat' or 'embed'.
        Returns (None, None, None) if the URL doesn't match any known pattern.
    """
    match = CHAT_SHARE_URL_PATTERN.search(url)
    if match:
        return 'chat', match.group(1), match.group(2)
    match = EMBED_SHARE_URL_PATTERN.search(url)
    if match:
        return 'embed', match.group(1), match.group(2)
    return None, None, None


def decrypt_share_key_blob(
    entity_id: str,
    encrypted_blob: str,
    key_field_name: str = 'chat_encryption_key',
    password: Optional[str] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Decrypt a share key blob and extract the raw AES encryption key.

    Reimplements the frontend's decryptShareKeyBlob / decryptEmbedShareKeyBlob.

    Returns:
        (raw_key_bytes, error_message) — on success, error is None.
    """
    try:
        encrypted_blob = unquote(encrypted_blob).strip()
        id_key = _derive_key_from_id(entity_id)
        raw_encrypted = base64url_decode(encrypted_blob)

        try:
            serialised = _aes_gcm_decrypt(raw_encrypted, id_key)
            serialised_str = serialised.decode('utf-8')
        except Exception as e:
            return None, f"AES-GCM decryption failed: {type(e).__name__}: {e}"

        params = parse_qs(serialised_str, keep_blank_values=True)
        encryption_key_value = params.get(key_field_name, [''])[0]
        pwd_flag = params.get('pwd', ['0'])[0]

        if not encryption_key_value:
            return None, f"Blob is missing '{key_field_name}' field"

        if pwd_flag == '1':
            if not password:
                return None, (
                    "Share link is password-protected (pwd=1). "
                    "Provide the password with --share-password"
                )
            pwd_key = _derive_key_from_password(password, entity_id)
            raw_key_encrypted = base64url_decode(encryption_key_value)
            key_base64_bytes = _aes_gcm_decrypt(raw_key_encrypted, pwd_key)
            encryption_key_value = key_base64_bytes.decode('utf-8')

        raw_key = base64.b64decode(encryption_key_value)
        if len(raw_key) != 32:
            return None, (
                f"Decoded key is {len(raw_key)} bytes, expected 32 bytes (AES-256)"
            )
        return raw_key, None

    except Exception as e:
        return None, f"Failed to decrypt share key blob: {e}"


def decrypt_client_aes_content(
    encrypted_base64: str,
    raw_key: bytes,
) -> Tuple[Optional[str], Optional[str]]:
    """Decrypt client-side AES-GCM encrypted content.

    Returns:
        (plaintext_string, error_message) — on success, error is None.
    """
    if not encrypted_base64:
        return None, "Empty encrypted content"
    try:
        raw_bytes = base64.b64decode(encrypted_base64)
        plaintext_bytes = _aes_gcm_decrypt(raw_bytes, raw_key)
        return plaintext_bytes.decode('utf-8'), None
    except Exception as e:
        return None, f"AES-GCM decryption failed: {e}"
