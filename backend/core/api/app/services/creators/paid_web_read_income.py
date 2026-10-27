"""Best-effort creator share after an authoritative web.read debit commits."""
import logging
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

from backend.core.api.app.utils.server_mode import is_payment_enabled

logger = logging.getLogger(__name__)


async def record_paid_web_read_income(server_result_group, receipt) -> bool:
    """Reserve one 10-credit share per committed charge, never per execution.

    Both arguments are internal server outputs, never request input. A stable
    primary key makes receipt retries safe even across concurrent processes.
    Anonymous holds, pending/outbox charges and missing receipts fail closed.
    """
    try:
        if not is_payment_enabled() or not isinstance(receipt, dict):
            return False
        charged = receipt.get("charged_credits")
        charge_id = receipt.get("charge_id")
        if (receipt.get("status") != "success" or receipt.get("state") != "committed"
                or not isinstance(charged, int) or isinstance(charged, bool) or charged < 20
                or not isinstance(charge_id, str) or not charge_id.strip() or len(charge_id) > 256):
            return False
        group = server_result_group
        if (not isinstance(group, dict) or group.get("error")
                or not isinstance(group.get("usage"), dict)
                or group["usage"].get("credits_charged") != 20
                or not isinstance(group.get("results"), list)):
            return False
        pages = [page for page in group["results"] if isinstance(page, dict)
                 and not page.get("error") and isinstance(page.get("markdown"), str)
                 and page["markdown"].strip()]
        # A charged web.read group represents exactly one requested page.
        if len(pages) != 1:
            return False
        url = pages[0].get("source_url") or pages[0].get("url")
        if not isinstance(url, str):
            return False
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False

        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.services.creators.revenue_service import CreatorRevenueService
        from backend.core.api.app.services.directus import DirectusService
        from backend.core.api.app.utils.encryption import EncryptionService
        from backend.shared.python_utils.url_normalizer import extract_domain_from_url, normalize_url_for_content_id

        owner_id = extract_domain_from_url(url)
        content_id = normalize_url_for_content_id(url)
        if not owner_id or not content_id:
            return False
        cache = CacheService()
        encryption = EncryptionService(cache_service=cache)
        directus = DirectusService(cache_service=cache, encryption_service=encryption)
        return await CreatorRevenueService(directus_service=directus, encryption_service=encryption).create_income_entry(
            owner_id=owner_id, content_id=content_id, content_type="website",
            app_id="web", skill_id="read", credits=10, income_source="skill_usage",
            entry_id=str(uuid5(NAMESPACE_URL, f"openmates:web.read:creator-income:{charge_id}")),
        )
    except Exception:
        # Payout failure must not turn a successfully read page into an error.
        # Do not log the content URL or identifiers from the receipt.
        logger.warning("Paid web.read creator income could not be recorded")
        return False
