#!/usr/bin/env python3
"""
Shared utility module for OpenMates backend inspection scripts.

Centralises duplicated helpers (logging setup, timestamp formatting, string
truncation, email censoring, hashing, ANSI colours, Vault API-key retrieval,
production API requests, and Vault encryption helpers) so that individual
inspect_*.py scripts can import them instead of re-implementing the same
logic.

Architecture context: See docs/claude/inspection-scripts.md
Tests: None (inspection utility, not production code)
"""

# ── Standard library ──────────────────────────────────────────────────────────
import base64
import hashlib
import json
import logging
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple


if TYPE_CHECKING:
    from backend.core.api.app.services.directus.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

# ── Third-party (always available in the Docker image) ────────────────────────
import httpx

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
) -> Dict[str, Any]:
    """Make an authenticated request to the Admin Debug API.

    Handles common HTTP error codes (401 / 403 / 404 / 5xx), connection
    errors, and timeouts — printing a user-facing message and calling
    ``sys.exit(1)`` on failure, matching the behaviour of the original
    per-script implementations.

    Args:
        endpoint: The API endpoint path (appended to *base_url*).
        api_key: Bearer token for authentication.
        base_url: One of :data:`PROD_API_URL` / :data:`DEV_API_URL`.
        params: Optional query parameters.
        method: HTTP method (``"GET"`` or ``"DELETE"``).
        entity_label: Human-readable label used in error messages
            (e.g. ``"Chat"`` or ``"Embed"``).

    Returns:
        Parsed JSON response body.

    Raises:
        SystemExit: On any request failure.
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
                print(f"Error: {entity_label} not found", file=sys.stderr)
                sys.exit(1)
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
