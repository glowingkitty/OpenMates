# backend/apps/mail/skills/search_skill.py
#
# Mail search skill implementation backed by Proton Mail Bridge IMAP.
# Supports optional query input (empty query returns most recent emails first),
# enforces single-allowed-user access, and runs prompt-injection safeguards on
# returned email content before exposing it to downstream LLM inference.
#
# Architecture: docs/architecture/prompt-injection.md
# Tests: covered through skill execution integration paths.

from __future__ import annotations

import logging
import os
import yaml
from typing import Any, Dict, List, Optional, Tuple

from celery import Celery
from pydantic import BaseModel, Field

from backend.apps.ai.processing.external_result_sanitizer import (
    sanitize_long_text_fields_in_payload,
)
from backend.apps.ai.processing.skill_executor import check_rate_limit, wait_for_rate_limit
from backend.apps.base_skill import BaseSkill
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.protonmail.protonmail_bridge import (
    DEFAULT_MAX_RESULTS,
    build_default_query_label,
    get_protonmail_bridge_config,
    is_bridge_configured,
    is_user_allowed_for_protonmail,
    search_protonmail_messages,
)

logger = logging.getLogger(__name__)


class MailSearchRequestItem(BaseModel):
    """A single mail search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: Optional[str] = Field(
        default=None,
        description="Optional search text (subject/from/body). Empty means recent-first listing.",
    )
    mailbox: Optional[str] = Field(
        default=None,
        description="Optional mailbox name (defaults to INBOX).",
    )
    limit: int = Field(
        default=10,
        description="Maximum number of email results to return (1-50, default 10).",
    )


class SearchRequest(BaseModel):
    """Request model for mail search skill."""

    requests: List[MailSearchRequestItem] = Field(
        ...,
        description=(
            "Array of mail search request objects. Each request can include optional query, "
            "mailbox, and limit. If query is missing or empty, the newest emails are returned first."
        ),
    )


class SearchResponse(BaseModel):
    """Response model for mail search skill."""

    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of request results grouped by id. Each entry includes an id, query label, and mail result items."
        ),
    )
    provider: str = Field(default="Proton Mail Bridge", description="Provider label")
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions",
    )
    error: Optional[str] = Field(None, description="Error message if execution failed")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "uid",
            "message_id",
            "body_html",
        ],
        description=(
            "Fields excluded from LLM inference payloads to limit prompt-injection surface and token size."
        ),
    )


class SearchSkill(BaseSkill):
    """Search emails via Proton Mail Bridge using optional user query input."""

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )

        if skill_operational_defaults:
            logger.debug(
                "Mail Search skill '%s' received operational_defaults: %s",
                self.skill_name,
                skill_operational_defaults,
            )

        self.suggestions_follow_up_requests: List[str] = []
        self._load_suggestions_from_app_yml()

    def _load_suggestions_from_app_yml(self) -> None:
        try:
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            app_dir = os.path.dirname(current_file_dir)
            app_yml_path = os.path.join(app_dir, "app.yml")
            if not os.path.exists(app_yml_path):
                return
            with open(app_yml_path, "r", encoding="utf-8") as app_file:
                app_config = yaml.safe_load(app_file) or {}
            for skill in app_config.get("skills", []):
                if skill.get("id", "").strip() == "search":
                    suggestions = skill.get("suggestions_follow_up_requests", [])
                    if isinstance(suggestions, list):
                        self.suggestions_follow_up_requests = [str(item) for item in suggestions]
                    return
        except Exception as exc:
            logger.warning("Failed to load mail search follow-up suggestions: %s", exc, exc_info=True)

    async def _process_single_request(
        self,
        *,
        req: Dict[str, Any],
        request_id: Any,
        user_id: str,
        secrets_manager: SecretsManager,
        cache_service: CacheService,
    ) -> Tuple[Any, Dict[str, Any], Optional[str]]:
        query = (req.get("query") or "").strip()
        mailbox = (req.get("mailbox") or "").strip() or None
        limit_raw = req.get("limit", DEFAULT_MAX_RESULTS)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = DEFAULT_MAX_RESULTS

        provider_id = "protonmail"
        is_allowed_rate, _ = await check_rate_limit(
            provider_id=provider_id,
            skill_id="search",
            cache_service=cache_service,
        )
        if not is_allowed_rate:
            await wait_for_rate_limit(
                provider_id=provider_id,
                skill_id="search",
                cache_service=cache_service,
                celery_producer=getattr(self.app, "celery_producer", None),
                celery_task_context={
                    "app_id": self.app_id,
                    "skill_id": self.skill_id,
                    "arguments": req,
                    "chat_id": self._current_chat_id,
                    "message_id": self._current_message_id,
                },
            )

        config = await get_protonmail_bridge_config(secrets_manager)
        if not config.enabled:
            return request_id, {}, "Proton Mail Bridge integration is disabled"
        if not is_bridge_configured(config):
            return request_id, {}, "Proton Mail Bridge is not fully configured"

        is_allowed_user = await is_user_allowed_for_protonmail(user_id=user_id, config=config)
        if not is_allowed_user:
            return request_id, {}, "Current user is not authorized for Proton Mail Bridge access"

        raw_results = await search_protonmail_messages(
            config=config,
            query=query,
            mailbox=mailbox,
            limit=limit,
        )

        # Prompt-injection hardening for all returned mail fields (including HTML) using
        # the existing GPT safeguard flow via sanitize_external_content.
        sanitized_results = await sanitize_long_text_fields_in_payload(
            payload=raw_results,
            task_id=f"mail_search_{request_id}",
            secrets_manager=secrets_manager,
            cache_service=cache_service,
            min_chars=40,
            max_parallel=3,
        )

        return (
            request_id,
            {
                "id": request_id,
                "query": build_default_query_label(query),
                "results": sanitized_results,
            },
            None,
        )

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        secrets_manager: Optional[SecretsManager] = None,
        **kwargs,
    ) -> SearchResponse:
        secrets_manager, error_response = await self._get_or_create_secrets_manager(
            secrets_manager=secrets_manager,
            skill_name="MailSearchSkill",
            error_response_factory=lambda msg: SearchResponse(results=[], error=msg),
            logger=logger,
        )
        if error_response:
            return error_response

        if not user_id:
            return SearchResponse(results=[], error="Missing authenticated user context for mail search")

        if not requests:
            requests = [{}]

        cache_service = CacheService()
        grouped_results: List[Dict[str, Any]] = []
        errors: List[str] = []

        for index, req in enumerate(requests):
            request_id = req.get("id") if isinstance(req, dict) else None
            if request_id is None:
                request_id = index
            request_payload = req if isinstance(req, dict) else {}

            try:
                rid, payload, err = await self._process_single_request(
                    req=request_payload,
                    request_id=request_id,
                    user_id=user_id,
                    secrets_manager=secrets_manager,
                    cache_service=cache_service,
                )
                if err:
                    errors.append(f"Request {rid}: {err}")
                    continue
                grouped_results.append(payload)
            except Exception as exc:
                logger.error("Mail search request %s failed: %s", request_id, exc, exc_info=True)
                errors.append(f"Request {request_id}: {exc}")

        return SearchResponse(
            results=grouped_results,
            suggestions_follow_up_requests=(
                self.suggestions_follow_up_requests if grouped_results else None
            ),
            error="; ".join(errors) if errors else None,
        )
