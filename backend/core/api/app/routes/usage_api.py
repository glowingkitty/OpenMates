# backend/core/api/app/routes/usage_api.py
#
# Usage API endpoints wrapper for OpenAPI documentation
# This router re-exports the usage endpoints from settings.py so they appear in /docs
# The actual implementation is in settings.py - this is just a thin wrapper to avoid
# code duplication while making endpoints visible in the OpenAPI schema.

from fastapi import APIRouter
from backend.core.api.app.routes.settings import get_usage_summaries, get_usage_details, export_usage_csv, get_chat_total_credits, get_message_cost, get_daily_overview

# Create a router that will be included in OpenAPI docs
router = APIRouter(prefix="/v1/settings/usage", tags=["Usage"])

# Re-export the endpoint functions from settings.py
# This allows them to appear in the OpenAPI schema while keeping the implementation in one place
router.get("/summaries")(get_usage_summaries)
router.get("/details")(get_usage_details)
router.get("/chat-total")(get_chat_total_credits)
router.get("/message-cost")(get_message_cost)
router.get("/daily-overview")(get_daily_overview)
router.get("/export")(export_usage_csv)
