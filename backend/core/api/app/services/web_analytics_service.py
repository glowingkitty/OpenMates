# backend/core/api/app/services/web_analytics_service.py
#
# Privacy-preserving, first-party web analytics service.
#
# Design principles:
# - No PII stored anywhere — IPs are used only transiently for GeoIP lookup,
#   never persisted. User-Agent strings are parsed to metadata only.
# - Aggregate-only storage: all data lands in Redis counters (day-keyed hashes)
#   and is flushed to Directus every 10 minutes by a Celery task.
# - Graceful shutdown persistence: on SIGTERM, counters are dumped to disk
#   (/shared/cache/web_analytics_backup.json) and restored on next startup,
#   preventing data loss during container restarts.
# - HyperLogLog for unique visits: probabilistic estimation (~0.81% error),
#   computed from hash(truncated_ip + ua_family + date), no raw data stored.
#
# Data collected:
#   - Page loads (count)
#   - Approximate unique visits (HyperLogLog)
#   - Country distribution (GeoIP lookup, IP discarded immediately)
#   - Device class: mobile / tablet / desktop
#   - Browser family + major version
#   - OS family
#   - Referrer domain (domain only, never full URL)
#   - Screen size class: sm / md / lg / xl (from client beacon)
#   - Session duration buckets (from client beacon + WebSocket connect/disconnect)
#
# Architecture: see docs/analytics.md

import logging
import json
import os
import hashlib
from datetime import date, datetime
from typing import Optional, Dict, Any, TYPE_CHECKING

import user_agents  # Already in requirements.txt (user-agents==2.2.0)

from backend.core.api.app.utils.encryption import USER_DATA_ENCRYPTION_KEY

if TYPE_CHECKING:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.utils.encryption import EncryptionService

logger = logging.getLogger(__name__)

# Redis key prefixes
WEB_ANALYTICS_DAILY_KEY_PREFIX = "web:analytics:daily:"  # e.g. web:analytics:daily:2026-02-25
WEB_ANALYTICS_HLL_KEY_PREFIX = "web:analytics:hll:"      # HyperLogLog for unique visits

# Disk backup path (same shared volume as payment/reminder backups)
WEB_ANALYTICS_BACKUP_PATH = "/shared/cache/web_analytics_backup.json"

# Redis TTL: 2 days — long enough to survive a full Celery flush cycle
WEB_ANALYTICS_REDIS_TTL = 172800  # 48 hours

# Session duration buckets (label → max seconds, None = unbounded)
SESSION_DURATION_BUCKETS = [
    ("<30s",    30),
    ("30s-2m",  120),
    ("2m-5m",   300),
    ("5m-15m",  900),
    ("15m-30m", 1800),
    ("30m-1h",  3600),
    ("1h+",     None),
]

# Screen width buckets: matches CSS breakpoints
SCREEN_CLASSES = {
    "sm":  (0, 640),
    "md":  (640, 1024),
    "lg":  (1024, 1440),
    "xl":  (1440, None),
}

# GeoLite2 database path — self-hosters should mount or download this file
# See docs/analytics.md for how to obtain the free MaxMind GeoLite2-Country database
GEOLITE2_DB_PATH = os.getenv("GEOLITE2_DB_PATH", "/shared/geoip/GeoLite2-Country.mmdb")

# Lazy-loaded GeoIP reader (None if database file is not available)
_geoip_reader: Optional[Any] = None
_geoip_unavailable: bool = False  # Set to True after first failed load attempt


def _get_geoip_reader() -> Optional[Any]:
    """
    Returns the maxminddb reader, loading it lazily on first call.
    Returns None if the database file is not available — GeoIP is optional.
    """
    global _geoip_reader, _geoip_unavailable

    if _geoip_reader is not None:
        return _geoip_reader

    if _geoip_unavailable:
        return None

    if not os.path.exists(GEOLITE2_DB_PATH):
        logger.warning(
            f"GeoLite2 database not found at {GEOLITE2_DB_PATH}. "
            f"Country/region analytics will be unavailable. "
            f"Set GEOLITE2_DB_PATH env var or place the file at the default path. "
            f"See docs/analytics.md for instructions."
        )
        _geoip_unavailable = True
        return None

    try:
        import maxminddb
        _geoip_reader = maxminddb.open_database(GEOLITE2_DB_PATH)
        logger.info(f"GeoLite2 database loaded from {GEOLITE2_DB_PATH}")
        return _geoip_reader
    except ImportError:
        logger.warning("maxminddb package not installed. Country analytics unavailable.")
        _geoip_unavailable = True
        return None
    except Exception as e:
        logger.error(f"Failed to load GeoLite2 database: {e}")
        _geoip_unavailable = True
        return None


def _lookup_country(ip: str) -> str:
    """
    Performs a GeoIP lookup and returns the ISO 3166-1 alpha-2 country code.
    Returns "unknown" if the database is unavailable or the IP cannot be resolved.
    The IP address is never stored — it is only used transiently for this lookup.
    """
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return "unknown"

    reader = _get_geoip_reader()
    if reader is None:
        return "unknown"

    try:
        record = reader.get(ip)
        if record and "country" in record:
            country = record["country"]
            iso_code = country.get("iso_code")
            if iso_code:
                return iso_code.upper()
    except Exception as e:
        logger.debug(f"GeoIP lookup failed for IP (not stored): {e}")

    return "unknown"


def _parse_user_agent(ua_string: str) -> Dict[str, str]:
    """
    Parses a User-Agent string and returns structured metadata.
    The raw UA string is never stored — only the parsed metadata is kept.

    Returns a dict with keys: browser, browser_version, os, device
    """
    if not ua_string:
        return {"browser": "unknown", "browser_version": "unknown", "os": "unknown", "device": "desktop"}

    try:
        ua = user_agents.parse(ua_string)

        # Browser family and major version only (e.g. "Chrome 120", "Firefox 121")
        browser_family = ua.browser.family or "unknown"
        browser_version = ua.browser.version_string.split(".")[0] if ua.browser.version_string else "0"
        browser_label = f"{browser_family} {browser_version}" if browser_family != "unknown" else "unknown"

        # OS family only (e.g. "Windows", "macOS", "iOS", "Android")
        os_family = ua.os.family or "unknown"

        # Device class
        if ua.is_mobile:
            device = "mobile"
        elif ua.is_tablet:
            device = "tablet"
        else:
            device = "desktop"

        return {
            "browser": browser_label,
            "os": os_family,
            "device": device,
        }
    except Exception as e:
        logger.debug(f"UA parsing failed: {e}")
        return {"browser": "unknown", "browser_version": "unknown", "os": "unknown", "device": "desktop"}


def _extract_referrer_domain(referer_header: str) -> str:
    """
    Extracts only the domain from a referrer URL.
    Full URLs are never stored — only the domain part.
    Returns "(direct)" if the referrer is empty, unparseable, or same-origin.

    NOTE: This function now receives the client-supplied document.referrer value
    (forwarded from the beacon payload), NOT the HTTP Referer request header.
    The HTTP Referer on a beacon POST always contains the app's own URL, making
    it useless for external attribution. document.referrer contains the real
    previous page the user navigated from — what we actually want to track.

    Same-origin filtering is applied as a safety net: if the referrer domain
    matches known app hostnames, it is treated as "(direct)" rather than
    attributing visits to the app itself.
    """
    if not referer_header:
        return "(direct)"

    try:
        from urllib.parse import urlparse
        parsed = urlparse(referer_header)
        domain = parsed.netloc.lower()
        # Strip www. prefix for normalization
        if domain.startswith("www."):
            domain = domain[4:]
        # Remove port number
        if ":" in domain:
            domain = domain.split(":")[0]
        if not domain:
            return "(direct)"
        # Filter same-origin referrers: app subdomains (app.*, app.dev.*)
        # and bare openmates.org domains should not appear as referrers.
        # A user navigating within the app is not "referred" by the app itself.
        if "openmates.org" in domain or "openmates.dev" in domain:
            return "(direct)"
        return domain
    except Exception:
        return "(direct)"


def _truncate_ip(ip: str) -> str:
    """
    Truncates an IP for HyperLogLog input to prevent re-identification.
    IPv4: zero out last octet (203.0.113.42 → 203.0.113.0)
    IPv6: zero out last 80 bits (keep only first 48 bits)
    The truncated value is only used as HLL input and is never stored.
    """
    try:
        if ":" in ip:
            # IPv6: keep only first 3 groups (48 bits)
            parts = ip.split(":")
            return ":".join(parts[:3]) + "::" if len(parts) >= 3 else ip
        else:
            # IPv4: zero last octet
            parts = ip.split(".")
            if len(parts) == 4:
                return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
    except Exception:
        pass
    return ip


def _get_session_duration_bucket(duration_seconds: float) -> str:
    """Maps a duration in seconds to the appropriate bucket label."""
    for label, max_secs in SESSION_DURATION_BUCKETS:
        if max_secs is None or duration_seconds < max_secs:
            return label
    return "1h+"


class WebAnalyticsService:
    """
    Service for collecting and persisting privacy-preserving web analytics.

    All analytics data is:
    - Stored in Redis as daily aggregate counters
    - Flushed to Directus every 10 minutes by a Celery task
    - Persisted to disk on graceful shutdown and restored on startup
    - Free of any PII — IPs and UA strings are never stored

    See docs/analytics.md for the full data model and privacy guarantees.
    """

    def __init__(self, cache_service: "CacheService"):
        self.cache = cache_service

    def _get_daily_key(self, day: Optional[str] = None) -> str:
        """Returns the Redis hash key for a specific day's analytics counters."""
        return f"{WEB_ANALYTICS_DAILY_KEY_PREFIX}{day or date.today().isoformat()}"

    def _get_hll_key(self, day: Optional[str] = None) -> str:
        """Returns the Redis HyperLogLog key for unique visit estimation."""
        return f"{WEB_ANALYTICS_HLL_KEY_PREFIX}{day or date.today().isoformat()}"

    async def record_page_view(
        self,
        client_ip: str,
        ua_string: str,
        referer_header: str,
        screen_class: Optional[str] = None,
        path: Optional[str] = None,
    ) -> None:
        """
        Records a page view event from either the client beacon or a direct request.

        Increments all aggregate counters for today in Redis.
        IPs and UA strings are processed in-memory only and never persisted.

        Args:
            client_ip: Raw client IP (used for GeoIP + HLL, then discarded)
            ua_string: Raw User-Agent string (parsed to metadata, then discarded)
            referer_header: Raw Referer header (domain extracted, then discarded)
            screen_class: Optional screen width class from client beacon ("sm"/"md"/"lg"/"xl")
            path: Optional page path from client beacon (used for SPA route tracking)
        """
        today = date.today().isoformat()
        daily_key = self._get_daily_key(today)
        hll_key = self._get_hll_key(today)

        client = await self.cache.client
        if not client:
            return

        try:
            # Parse UA string → metadata (UA string never stored)
            ua_meta = _parse_user_agent(ua_string)

            # GeoIP lookup → country code (IP never stored)
            country = _lookup_country(client_ip)

            # Extract referrer domain (full URL never stored)
            referrer_domain = _extract_referrer_domain(referer_header)

            # HyperLogLog unique visit estimation:
            # Input = hash of (truncated_ip + ua_family + date) — not reversible to IP
            truncated_ip = _truncate_ip(client_ip)
            ua_family = ua_meta.get("browser", "unknown").split(" ")[0]  # e.g. "Chrome"
            hll_input = hashlib.sha256(
                f"{truncated_ip}|{ua_family}|{today}".encode()
            ).hexdigest()

            # Build all field increments in a pipeline for efficiency
            pipe = client.pipeline()

            # Core counters
            pipe.hincrby(daily_key, "page_loads", 1)
            pipe.pfadd(hll_key, hll_input)

            # Geographic distribution
            pipe.hincrby(daily_key, f"countries:{country}", 1)

            # Device and browser distribution
            pipe.hincrby(daily_key, f"devices:{ua_meta['device']}", 1)
            pipe.hincrby(daily_key, f"browsers:{ua_meta['browser']}", 1)
            pipe.hincrby(daily_key, f"os:{ua_meta['os']}", 1)

            # Referrer distribution
            pipe.hincrby(daily_key, f"referrers:{referrer_domain}", 1)

            # Screen size class (from client beacon only)
            if screen_class and screen_class in ("sm", "md", "lg", "xl"):
                pipe.hincrby(daily_key, f"screen_classes:{screen_class}", 1)

            # Set TTL on the daily hash to 48 hours
            pipe.expire(daily_key, WEB_ANALYTICS_REDIS_TTL)
            pipe.expire(hll_key, WEB_ANALYTICS_REDIS_TTL)

            await pipe.execute()

        except Exception as e:
            logger.error(f"WebAnalyticsService: Failed to record page view: {e}", exc_info=True)

    async def record_session_duration_bucket(self, bucket: str) -> None:
        """
        Records a pre-bucketed session duration directly.

        Used when the client beacon already has a bucket label (e.g. from pagehide),
        avoiding the need to re-bucket on the server side.

        Args:
            bucket: One of the SESSION_DURATION_BUCKETS labels (e.g. "2m-5m")
        """
        today = date.today().isoformat()
        daily_key = self._get_daily_key(today)

        client = await self.cache.client
        if not client:
            return

        try:
            pipe = client.pipeline()
            pipe.hincrby(daily_key, f"duration:{bucket}", 1)
            pipe.expire(daily_key, WEB_ANALYTICS_REDIS_TTL)
            await pipe.execute()
        except Exception as e:
            logger.error(f"WebAnalyticsService: Failed to record session duration bucket: {e}", exc_info=True)

    async def record_session_duration(self, duration_seconds: float) -> None:
        """
        Records a bucketed session duration event.

        Called either from the client beacon (pagehide event) or from WebSocket
        disconnect (for authenticated users). The exact duration is bucketed
        immediately and only the bucket counter is incremented.

        Args:
            duration_seconds: Session duration in seconds (never stored directly)
        """
        bucket = _get_session_duration_bucket(duration_seconds)
        today = date.today().isoformat()
        daily_key = self._get_daily_key(today)

        client = await self.cache.client
        if not client:
            return

        try:
            pipe = client.pipeline()
            pipe.hincrby(daily_key, f"duration:{bucket}", 1)
            pipe.expire(daily_key, WEB_ANALYTICS_REDIS_TTL)
            await pipe.execute()
        except Exception as e:
            logger.error(f"WebAnalyticsService: Failed to record session duration: {e}", exc_info=True)

    async def get_daily_counters(self, day: str) -> Dict[str, Any]:
        """
        Returns all analytics counters for a specific day from Redis.
        Used by the Celery flush task to persist data to Directus.

        Returns a dict with all hash fields for the given day.
        """
        daily_key = self._get_daily_key(day)
        hll_key = self._get_hll_key(day)

        client = await self.cache.client
        if not client:
            return {}

        try:
            pipe = client.pipeline()
            pipe.hgetall(daily_key)
            pipe.pfcount(hll_key)
            results = await pipe.execute()

            raw_hash = results[0] or {}
            unique_visits = results[1] or 0

            # Decode bytes keys/values
            decoded = {
                (k.decode() if isinstance(k, bytes) else k): int(v)
                for k, v in raw_hash.items()
            }
            decoded["unique_visits_approx"] = unique_visits
            return decoded

        except Exception as e:
            logger.error(f"WebAnalyticsService: Failed to get daily counters for {day}: {e}", exc_info=True)
            return {}

    def _build_json_fields(self, counters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts flat Redis hash fields into nested JSON objects for Directus storage.

        Example:
          Input: {"countries:DE": 50, "countries:US": 30, "page_loads": 100}
          Output: {"countries": {"DE": 50, "US": 30}, "page_loads": 100}
        """
        result: Dict[str, Any] = {}
        json_buckets: Dict[str, Dict[str, int]] = {}

        for key, value in counters.items():
            if ":" in key:
                prefix, sub_key = key.split(":", 1)
                if prefix not in json_buckets:
                    json_buckets[prefix] = {}
                json_buckets[prefix][sub_key] = value
            else:
                result[key] = value

        # Merge JSON buckets
        for prefix, sub_dict in json_buckets.items():
            result[prefix] = sub_dict

        return result

    async def dump_to_disk(self, encryption_service: Optional["EncryptionService"] = None) -> int:
        """
        Persists all in-memory analytics counters to disk before shutdown.

        This ensures no data is lost when the API container is restarted.
        The backup file is restored on next startup by restore_from_disk().

        All data is encrypted via Vault transit before writing to disk.
        If encryption_service is not available, the dump is skipped entirely
        to prevent cleartext analytics data from being written to disk.

        Args:
            encryption_service: Vault transit encryption service. Required — if None,
                the dump is refused to prevent cleartext writes.

        Returns:
            Number of days whose counters were saved (0 if encryption unavailable).
        """
        if not encryption_service:
            logger.warning(
                "WebAnalyticsService: Cannot dump to disk: no encryption_service provided "
                "(refusing to write cleartext analytics data to disk)"
            )
            return 0

        client = await self.cache.client
        if not client:
            return 0

        try:
            # Find all web analytics keys
            daily_keys = await client.keys(f"{WEB_ANALYTICS_DAILY_KEY_PREFIX}*")
            hll_keys = await client.keys(f"{WEB_ANALYTICS_HLL_KEY_PREFIX}*")

            if not daily_keys and not hll_keys:
                return 0

            backup_data: Dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "daily": {},
                "unique_visits": {},
            }

            # Dump daily hash counters
            for key in daily_keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                day = key_str.replace(WEB_ANALYTICS_DAILY_KEY_PREFIX, "")
                raw = await client.hgetall(key)
                decoded = {
                    (k.decode() if isinstance(k, bytes) else k): int(v)
                    for k, v in raw.items()
                }
                backup_data["daily"][day] = decoded

            # Dump HLL unique visit estimates
            for key in hll_keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                day = key_str.replace(WEB_ANALYTICS_HLL_KEY_PREFIX, "")
                count = await client.pfcount(key)
                backup_data["unique_visits"][day] = count

            # Encrypt via Vault transit before writing to disk
            plaintext_json = json.dumps(backup_data)
            try:
                ciphertext, _key_version = await encryption_service.encrypt(
                    plaintext_json, key_name=USER_DATA_ENCRYPTION_KEY
                )
            except Exception as enc_err:
                logger.error(
                    f"WebAnalyticsService: Failed to encrypt analytics backup — "
                    f"refusing to write cleartext to disk: {enc_err}",
                    exc_info=True,
                )
                return 0

            encrypted_wrapper = {
                "encrypted": ciphertext,
                "version": 1,
            }

            os.makedirs(os.path.dirname(WEB_ANALYTICS_BACKUP_PATH), exist_ok=True)
            with open(WEB_ANALYTICS_BACKUP_PATH, "w") as f:
                json.dump(encrypted_wrapper, f)

            days_saved = len(backup_data["daily"])
            logger.info(f"WebAnalyticsService: Saved analytics for {days_saved} day(s) to {WEB_ANALYTICS_BACKUP_PATH} (Vault-encrypted)")
            return days_saved

        except Exception as e:
            logger.error(f"WebAnalyticsService: Failed to dump analytics to disk: {e}", exc_info=True)
            return 0

    async def restore_from_disk(self, encryption_service: Optional["EncryptionService"] = None) -> int:
        """
        Restores analytics counters from disk backup after a restart.

        Called during API startup (lifespan), AFTER Vault is initialized.
        Handles three backup formats:
        - Vault-encrypted (version 1+): decrypts via encryption_service, then restores
        - Legacy cleartext (has "daily" key at top level): deletes without restoring
        - Unrecognized format: deletes the file

        Args:
            encryption_service: Vault transit encryption service. Required for
                decrypting encrypted backups. If None and backup is encrypted,
                the file is kept for the next startup attempt.

        Returns:
            Number of days restored (0 if file missing, encrypted without service,
            or legacy cleartext detected).
        """
        if not os.path.exists(WEB_ANALYTICS_BACKUP_PATH):
            return 0

        client = await self.cache.client
        if not client:
            return 0

        try:
            with open(WEB_ANALYTICS_BACKUP_PATH, "r") as f:
                backup_data = json.load(f)

            # Detect format: encrypted (version 1+) vs legacy cleartext
            if "encrypted" in backup_data and "version" in backup_data:
                # Vault-encrypted backup — decrypt before processing
                if not encryption_service:
                    logger.warning(
                        "WebAnalyticsService: Analytics backup is encrypted but no encryption_service "
                        "provided — cannot restore. File kept for next attempt."
                    )
                    return 0
                ciphertext = backup_data["encrypted"]
                try:
                    decrypted_json = await encryption_service.decrypt(
                        ciphertext, key_name=USER_DATA_ENCRYPTION_KEY
                    )
                    if not decrypted_json:
                        logger.error("WebAnalyticsService: Vault decryption returned empty result for analytics backup")
                        os.remove(WEB_ANALYTICS_BACKUP_PATH)
                        return 0
                    backup_data = json.loads(decrypted_json)
                except Exception as dec_err:
                    logger.error(
                        f"WebAnalyticsService: Failed to decrypt analytics backup: {dec_err}",
                        exc_info=True,
                    )
                    os.remove(WEB_ANALYTICS_BACKUP_PATH)
                    return 0
            elif "daily" in backup_data:
                # Legacy cleartext backup — delete without restoring
                logger.warning(
                    "WebAnalyticsService: Found legacy cleartext analytics backup — "
                    "deleting without restoring (cleartext should not be on disk)"
                )
                os.remove(WEB_ANALYTICS_BACKUP_PATH)
                return 0
            else:
                logger.error("WebAnalyticsService: Unrecognized analytics backup format — deleting")
                os.remove(WEB_ANALYTICS_BACKUP_PATH)
                return 0

            daily_data = backup_data.get("daily", {})
            days_restored = 0

            for day, counters in daily_data.items():
                daily_key = self._get_daily_key(day)
                pipe = client.pipeline()
                for field, value in counters.items():
                    pipe.hincrby(daily_key, field, value)
                pipe.expire(daily_key, WEB_ANALYTICS_REDIS_TTL)
                await pipe.execute()
                days_restored += 1

            # Delete backup file after successful restore
            os.remove(WEB_ANALYTICS_BACKUP_PATH)
            logger.info(
                f"WebAnalyticsService: Restored analytics for {days_restored} day(s) "
                f"from {WEB_ANALYTICS_BACKUP_PATH}"
            )
            return days_restored

        except Exception as e:
            logger.error(f"WebAnalyticsService: Failed to restore analytics from disk: {e}", exc_info=True)
            return 0
