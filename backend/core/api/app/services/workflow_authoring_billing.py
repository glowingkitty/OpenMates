"""Meter and settle provider calls made while authoring a workflow.

The authoring session is one billing subject. Each provider call has a stable
charge identity independent of the number of workflows in the generated batch.
No prompt, graph, correction text, or provider response enters usage details.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from backend.core.api.app.utils.config_manager import ConfigManager
from backend.shared.python_utils.billing_utils import (
    BillingError, calculate_total_credits, ensure_credit_headroom,
)


APP_ID = "workflows"
SKILL_ID = "create-or-modify"
JEV_MODEL = "typesafe/jev-1.13"
GEMINI_MODEL = "google/gemini-3.8-flash"


class WorkflowAuthoringBillingError(RuntimeError):
    """Safe failure that does not expose billing internals or user data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class WorkflowAuthoringBilling:
    def __init__(self, *, user_id: str, session_id: str,
                 config_manager: Any = None, app_id: str = APP_ID, skill_id: str = SKILL_ID,
                 team_id: str | None = None, team_precheck: Any = None) -> None:
        if not user_id or not session_id:
            raise WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_BILLING_INVALID_CONTEXT")
        self.user_id = user_id
        self.session_id = session_id
        self.user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        self.config_manager = config_manager or ConfigManager()
        self.app_id, self.skill_id = app_id, skill_id
        self.team_id, self.team_precheck = team_id, team_precheck
        self.entries: list[dict[str, Any]] = []
        self.usage_complete = True

    def _pricing(self, model: str) -> dict[str, Any]:
        provider, model_id = model.split("/", 1)
        details = self.config_manager.get_model_pricing(provider, model_id)
        pricing = details.get("pricing") if isinstance(details, dict) else None
        if not isinstance(pricing, dict) or not isinstance(pricing.get("tokens"), dict):
            raise WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_PRICING_UNAVAILABLE")
        return pricing

    def operation_id(self, *, provider_step: str) -> str:
        return str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"openmates:workflow-authoring:{self.user_id}:{self.session_id}:{provider_step}",
        ))

    async def precheck(self, *, model: str) -> None:
        # Validate the current catalog before starting paid inference. The
        # balance endpoint is cache-backed and does not read Directus.
        self._pricing(model)
        if self.team_id:
            if not callable(self.team_precheck):
                raise WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_BILLING_UNAVAILABLE")
            try:
                await self.team_precheck(self.team_id, self.user_id)
            except WorkflowAuthoringBillingError:
                raise
            except Exception as exc:
                raise WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_BILLING_UNAVAILABLE") from exc
            return
        try:
            await ensure_credit_headroom(
                user_id=self.user_id, estimated_credits=1,
                operation_name="workflow authoring",
                log_prefix="[WorkflowAuthoringBilling]",
            )
        except BillingError as exc:
            raise WorkflowAuthoringBillingError("INSUFFICIENT_CREDITS") from exc

    async def settle(self, *, model: str, provider_step: str,
                     usage: Any, provider: str | None = None) -> int:
        """Charge only usage returned by a provider, even on a failed plan."""
        if not isinstance(usage, dict):
            usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if (not isinstance(input_tokens, int) or isinstance(input_tokens, bool)
                or not isinstance(output_tokens, int) or isinstance(output_tokens, bool)
                or input_tokens < 0 or output_tokens < 0
                or input_tokens + output_tokens == 0):
            self.usage_complete = False
            self.entries.append({"provider_step": provider_step, "model_used": model,
                                 "metered": False, "credits_charged": 0})
            return 0

        credits = calculate_total_credits(
            pricing_config=self._pricing(model),
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        if credits <= 0:
            raise WorkflowAuthoringBillingError("WORKFLOW_AUTHORING_PRICING_UNAVAILABLE")
        operation_id = self.operation_id(provider_step=provider_step)
        jev_servers = {
            "typesafe": ("TypeSafe", "US"),
            "openrouter": ("OpenRouter", "global"),
        }
        # Older injected clients do not report the transport and historically
        # used OpenRouter; an unfamiliar transport must not be mislabeled.
        jev_server = (jev_servers[provider] if provider in jev_servers else
                      ("OpenRouter", "global") if provider is None else
                      ("Unknown", "unknown"))
        server_provider, server_region = (
            jev_server if model == JEV_MODEL else ("Google AI Studio", "US")
        )
        details = {
            "source": "direct",
            "operation_id": operation_id,
            "model_used": model,
            "server_provider": server_provider,
            "server_region": server_region,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "provider_step": provider_step,
        }
        try:
            from backend.core.api.app.routes import apps_api

            result = await apps_api.charge_credits_via_internal_api(
                user_id=self.user_id,
                user_id_hash=self.user_id_hash,
                credits=credits,
                app_id=self.app_id,
                skill_id=self.skill_id,
                usage_details=details,
                idempotency_key=operation_id,
                raise_on_error=True,
                **({"team_id": self.team_id} if self.team_id else {}),
            )
            charged = result.get("charged_credits") if isinstance(result, dict) else None
            if not isinstance(charged, int) or isinstance(charged, bool) or charged < 0:
                raise RuntimeError("Billing response omitted charged credits")
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            code = "INSUFFICIENT_CREDITS" if status == 402 else "WORKFLOW_AUTHORING_BILLING_UNAVAILABLE"
            raise WorkflowAuthoringBillingError(code) from exc
        self.entries.append({"provider_step": provider_step, "model_used": model,
                             "metered": True, "credits_charged": charged,
                             "operation_id": operation_id})
        return charged


class MeteredJevClient:
    """Keep billing around every Jev stage, including staged fallback calls."""

    def __init__(self, client: Any, billing: WorkflowAuthoringBilling) -> None:
        self.client = client
        self.billing = billing
        self.call_count = 0

    async def evaluate(self, **kwargs: Any) -> Any:
        step = f"jev:{self.call_count}"
        self.call_count += 1
        await self.billing.precheck(model=JEV_MODEL)
        try:
            response = await self.client.evaluate(**kwargs)
        except BaseException as exc:
            # A rejected or interrupted transport may not expose usage. Do
            # not infer tokens from the request or the USD cost estimate.
            await self.billing.settle(model=JEV_MODEL, provider_step=step,
                                      usage=getattr(exc, "usage", None),
                                      provider=getattr(exc, "provider", None))
            raise
        await self.billing.settle(model=JEV_MODEL, provider_step=step,
                                  usage=getattr(response, "usage", None),
                                  provider=getattr(response, "provider", None))
        return response
