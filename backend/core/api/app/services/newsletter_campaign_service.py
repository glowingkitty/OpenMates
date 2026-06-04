"""Admin newsletter campaign scheduling service.

This service bridges the new Directus-backed campaign workflow to the existing
newsletter renderer/sender. Campaign source is stored in Directus; transient
legacy manifest/i18n files are materialized only so the current sender can be
reused safely until it is refactored to read campaign bodies directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml

from backend.core.api.app.services.directus import DirectusService

logger = logging.getLogger(__name__)

COLLECTION = "newsletter_campaigns"
REPO_ROOT = Path(os.getenv("OPENMATES_REPO_ROOT", "/app"))
ISSUES_DIR = REPO_ROOT / "backend" / "newsletters" / "issues"
I18N_DIR = REPO_ROOT / "frontend" / "packages" / "ui" / "src" / "i18n" / "sources" / "demo_chats"
SUPPORTED_LANGS = ("en", "de")
VALID_STATUSES = {"draft", "approved", "scheduled", "sending", "sent", "failed", "cancelled"}
VALID_MODES = {"email_only", "public_page"}
CATEGORY_TO_KIND = {
    "updates_and_announcements": ("announcements", "news"),
    "tips_and_tricks": ("tips", "features"),
}


class NewsletterCampaignError(ValueError):
    """Raised when campaign input or state is invalid."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snake(slug: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


def _payload_hash(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_language_map(value: Any, field: str, required: bool = True) -> Dict[str, str]:
    if value is None:
        if required:
            raise NewsletterCampaignError(f"{field} is required")
        return {}
    if not isinstance(value, dict):
        raise NewsletterCampaignError(f"{field} must be a language map")
    normalized = {str(k).lower(): str(v).strip() for k, v in value.items() if v is not None and str(v).strip()}
    if required and not normalized.get("en"):
        raise NewsletterCampaignError(f"{field}.en is required")
    return normalized


def normalize_campaign_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = str(payload.get("slug") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,158}[a-z0-9]", slug):
        raise NewsletterCampaignError("slug must be lowercase kebab-case and 3-160 chars")

    category = str(payload.get("category") or "").strip()
    kind, demo_chat_category = CATEGORY_TO_KIND.get(category, (payload.get("kind"), payload.get("demo_chat_category")))
    if kind not in {"announcements", "tips"}:
        raise NewsletterCampaignError("kind must be announcements or tips, or category must map to one")

    mode = str(payload.get("mode") or "email_only").strip()
    if mode not in VALID_MODES:
        raise NewsletterCampaignError("mode must be email_only or public_page")

    chat_id = str(payload.get("chat_id") or "").strip() or None
    public_page_url = str(payload.get("public_page_url") or "").strip() or None
    if mode == "public_page" and not (chat_id or public_page_url):
        raise NewsletterCampaignError("public_page campaigns require chat_id or public_page_url")

    normalized = {
        "slug": slug,
        "status": str(payload.get("status") or "draft"),
        "mode": mode,
        "category": category,
        "kind": kind,
        "demo_chat_category": demo_chat_category,
        "chat_id": chat_id,
        "public_page_url": public_page_url,
        "scheduled_for": payload.get("scheduled_for"),
        "timezone": str(payload.get("timezone") or "UTC"),
        "subject": _normalize_language_map(payload.get("subject"), "subject"),
        "title": _normalize_language_map(payload.get("title"), "title"),
        "subtitle": _normalize_language_map(payload.get("subtitle"), "subtitle", required=False),
        "cta_text": _normalize_language_map(payload.get("cta_text"), "cta_text", required=False),
        "cta_url": str(payload.get("cta_url") or "").strip() or None,
        "body_markdown": _normalize_language_map(payload.get("body_markdown"), "body_markdown"),
        "video": payload.get("video"),
        "hero_image": payload.get("hero_image"),
        "header_icon": payload.get("header_icon"),
        "metadata": payload.get("metadata") or {},
    }
    if normalized["status"] not in VALID_STATUSES:
        raise NewsletterCampaignError(f"invalid status: {normalized['status']}")
    normalized["payload_hash"] = _payload_hash(normalized)
    return normalized


class NewsletterCampaignService:
    def __init__(self, directus: DirectusService) -> None:
        self.directus = directus

    async def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        items = await self.directus.get_items(
            COLLECTION,
            params={"filter": {"slug": {"_eq": slug}}, "limit": 1},
            admin_required=True,
        )
        return items[0] if items else None

    async def list_campaigns(self, limit: int = 25) -> list[Dict[str, Any]]:
        return await self.directus.get_items(
            COLLECTION,
            params={"sort": "-updated_at", "limit": max(1, min(limit, 100))},
            admin_required=True,
        )

    async def upsert_campaign(self, payload: Dict[str, Any], admin_user_id: str) -> Dict[str, Any]:
        normalized = normalize_campaign_payload(payload)
        existing = await self.get_by_slug(normalized["slug"])
        now = _now_iso()
        if existing and existing.get("status") in {"sending", "sent"}:
            raise NewsletterCampaignError("sent or sending campaigns cannot be replaced")

        data = {**normalized, "updated_at": now, "last_error": None}
        if existing:
            if existing.get("payload_hash") != normalized["payload_hash"]:
                data.update({
                    "status": "draft",
                    "preview_sent_at": None,
                    "preview_recipient": None,
                    "approved_at": None,
                    "approved_by": None,
                    "scheduled_for": None,
                })
            data.pop("created_at", None)
            updated = await self.directus.update_item(COLLECTION, existing["id"], data, admin_required=True)
            if not updated:
                raise RuntimeError("Failed to update newsletter campaign")
            return updated

        data.update({"created_at": now, "created_by": admin_user_id})
        ok, created = await self.directus.create_item(COLLECTION, data, admin_required=True)
        if not ok:
            raise RuntimeError(f"Failed to create newsletter campaign: {created}")
        return created

    async def send_preview(self, slug: str, admin_email: str) -> Dict[str, Any]:
        campaign = await self._require_campaign(slug)
        from backend.scripts import send_newsletter

        sent_langs: list[str] = []
        with self._legacy_files(campaign):
            for lang in self._available_langs(campaign):
                rc = await send_newsletter.run(argparse.Namespace(
                    slug=slug,
                    lang=lang,
                    dry_run=False,
                    render_to=None,
                    test_to=admin_email,
                    send=False,
                    admin_email=None,
                    resume=False,
                    simulate=False,
                    limit=None,
                    base_url=None,
                    resend_confirm=False,
                    non_interactive_approved=False,
                ))
                if rc != 0:
                    raise RuntimeError(f"Preview send failed for {lang}")
                sent_langs.append(lang)

        updated = await self.directus.update_item(
            COLLECTION,
            campaign["id"],
            {
                "preview_sent_at": _now_iso(),
                "preview_recipient": _mask_email(admin_email),
                "status": "draft" if campaign.get("status") == "draft" else campaign.get("status"),
                "updated_at": _now_iso(),
            },
            admin_required=True,
        )
        return {"campaign": updated or campaign, "sent_langs": sent_langs}

    async def approve_campaign(self, slug: str, admin_user_id: str) -> Dict[str, Any]:
        campaign = await self._require_campaign(slug)
        if not campaign.get("preview_sent_at"):
            raise NewsletterCampaignError("A test email must be sent to admin before approval")
        if campaign.get("status") in {"sending", "sent", "cancelled"}:
            raise NewsletterCampaignError("Campaign cannot be approved in its current state")
        updated = await self.directus.update_item(
            COLLECTION,
            campaign["id"],
            {"status": "approved", "approved_at": _now_iso(), "approved_by": admin_user_id, "updated_at": _now_iso()},
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to approve campaign")
        return updated

    async def schedule_campaign(self, slug: str, scheduled_for: str) -> Dict[str, Any]:
        campaign = await self._require_campaign(slug)
        if not campaign.get("approved_at"):
            raise NewsletterCampaignError("Campaign must be approved after test email review before scheduling")
        updated = await self.directus.update_item(
            COLLECTION,
            campaign["id"],
            {"status": "scheduled", "scheduled_for": scheduled_for, "updated_at": _now_iso()},
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to schedule campaign")
        return updated

    async def send_campaign_now(self, slug: str, *, simulate: bool = False) -> Dict[str, Any]:
        campaign = await self._require_campaign(slug)
        if not campaign.get("approved_at"):
            raise NewsletterCampaignError("Campaign must be approved after admin preview before sending")
        if campaign.get("status") in {"sent", "cancelled"}:
            raise NewsletterCampaignError("Campaign is already sent or cancelled")

        await self.directus.update_item(
            COLLECTION,
            campaign["id"],
            {"status": "sending", "locked_at": _now_iso(), "last_error": None, "updated_at": _now_iso()},
            admin_required=True,
        )

        from backend.scripts import send_newsletter

        try:
            if campaign.get("mode") == "public_page" and campaign.get("public_page_url"):
                live = await send_newsletter.check_landing_page_live(campaign["public_page_url"])
                if not live:
                    raise NewsletterCampaignError(f"Public newsletter page is not live: {campaign['public_page_url']}")
            with self._legacy_files(campaign):
                rc = await send_newsletter.run(argparse.Namespace(
                    slug=slug,
                    lang=None,
                    dry_run=False,
                    render_to=None,
                    test_to=None,
                    send=True,
                    admin_email=os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL") or "admin@openmates.org",
                    resume=True,
                    simulate=simulate,
                    limit=None,
                    base_url=None,
                    resend_confirm=False,
                    non_interactive_approved=True,
                ))
            status = "sent" if rc == 0 and not simulate else "approved" if simulate else "failed"
            patch: Dict[str, Any] = {"status": status, "updated_at": _now_iso(), "locked_at": None}
            if rc == 0 and not simulate:
                patch["sent_at"] = _now_iso()
            if rc != 0:
                patch.update({"failed_at": _now_iso(), "last_error": f"send_newsletter.py exited {rc}"})
            updated = await self.directus.update_item(COLLECTION, campaign["id"], patch, admin_required=True)
            return {"campaign": updated or campaign, "exit_code": rc, "simulate": simulate}
        except Exception as exc:
            await self.directus.update_item(
                COLLECTION,
                campaign["id"],
                {"status": "failed", "failed_at": _now_iso(), "last_error": str(exc), "locked_at": None, "updated_at": _now_iso()},
                admin_required=True,
            )
            raise

    async def process_due_campaigns(self, limit: int = 3) -> Dict[str, Any]:
        now = _now_iso()
        due = await self.directus.get_items(
            COLLECTION,
            params={
                "filter": {"status": {"_eq": "scheduled"}, "scheduled_for": {"_lte": now}, "approved_at": {"_nnull": True}},
                "sort": "scheduled_for",
                "limit": max(1, min(limit, 10)),
            },
            admin_required=True,
        )
        results = []
        for campaign in due:
            try:
                results.append(await self.send_campaign_now(campaign["slug"]))
            except Exception as exc:
                logger.error("Scheduled newsletter campaign failed: %s", campaign.get("slug"), exc_info=True)
                results.append({"slug": campaign.get("slug"), "error": str(exc)})
        return {"processed": len(results), "results": results}

    async def _require_campaign(self, slug: str) -> Dict[str, Any]:
        campaign = await self.get_by_slug(slug)
        if not campaign:
            raise NewsletterCampaignError("Campaign not found")
        return campaign

    def _available_langs(self, campaign: Dict[str, Any]) -> Iterable[str]:
        body = campaign.get("body_markdown") or {}
        langs = [lang for lang in SUPPORTED_LANGS if body.get(lang)]
        return langs or ["en"]

    def _legacy_paths(self, campaign: Dict[str, Any]) -> tuple[Path, Path]:
        slug = campaign["slug"]
        snake_name = f"{campaign['kind']}_{_snake(slug)}"
        return ISSUES_DIR / f"{slug}.yml", I18N_DIR / f"{snake_name}.yml"

    def _legacy_files(self, campaign: Dict[str, Any]):
        service = self

        class LegacyFilesContext:
            def __enter__(self_inner):
                self_inner.paths = service._legacy_paths(campaign)
                self_inner.previous = []
                for path in self_inner.paths:
                    self_inner.previous.append(path.read_text(encoding="utf-8") if path.exists() else None)
                service._materialize_legacy_files(campaign)
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                for path, previous in zip(self_inner.paths, self_inner.previous):
                    if previous is None:
                        try:
                            path.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        path.write_text(previous, encoding="utf-8")
                return False

        return LegacyFilesContext()

    def _materialize_legacy_files(self, campaign: Dict[str, Any]) -> None:
        slug = campaign["slug"]
        snake_name = f"{campaign['kind']}_{_snake(slug)}"
        manifest = {
            "slug": slug,
            "kind": campaign["kind"],
            "category": campaign["category"],
            "demo_chat_category": campaign.get("demo_chat_category"),
            "chat_id": campaign.get("chat_id") or "",
            "subject": campaign.get("subject") or {},
            "title": campaign.get("title") or {},
            "subtitle": campaign.get("subtitle") or {},
            "cta_url": campaign.get("cta_url"),
            "cta_text": campaign.get("cta_text") or {},
            "body_i18n_key": f"demo_chats.{snake_name}.message",
            "video": campaign.get("video"),
            "hero_image": campaign.get("hero_image"),
            "header_icon": campaign.get("header_icon"),
            "published_at": campaign.get("metadata", {}).get("published_at") if isinstance(campaign.get("metadata"), dict) else None,
            "sent_at": None,
        }
        body_markdown = campaign.get("body_markdown") or {}
        i18n_payload = {
            "message": body_markdown,
            "email_body": body_markdown,
        }
        ISSUES_DIR.mkdir(parents=True, exist_ok=True)
        I18N_DIR.mkdir(parents=True, exist_ok=True)
        (ISSUES_DIR / f"{slug}.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (I18N_DIR / f"{snake_name}.yml").write_text(
            yaml.safe_dump(i18n_payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
