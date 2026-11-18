"""Event search: documented official conference schedules plus general discovery from public web pages."""
import asyncio
from datetime import datetime, timezone
import logging
import os
import re
import unicodedata
import yaml
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from celery import Celery
from pydantic import BaseModel, Field
from backend.shared.python_utils.internal_llm_policy import InternalLlmPolicy, policy_from_skill_kwargs
from backend.apps.base_skill import BaseSkill
from backend.apps.events.providers import pretalx as pretalx_provider
from backend.apps.events.provider_aliases import PROVIDER_ALIASES, VALID_PROVIDERS
from backend.shared.app_packages.contracts import events_search_input
from backend.shared.app_packages.loader import get_installed_providers
from backend.apps.skill_progress import SkillProgress
from backend.shared.app_packages.contracts import validate_events_search_result
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome, run_installed_providers
from backend.shared.app_packages.web_source import KIND_EVENT, WEB_PROVIDER_ID, run_web_source
from backend.shared.python_utils.web_result_extraction import DEFAULT_MODEL, MODEL_REFS
from backend.shared.python_utils.web_source_billing import (
    WebSourcePrices, WebSourcePricingError, fetch_web_source_prices, group_usage,
)
from backend.shared.python_utils.search_relevance import (
    MAX_RELEVANCE_CRITERIA_CHARS, normalize_url_for_deduplication,
    stable_deduplicate_candidates, normalize_relevance_criteria, rank_search_candidates,
    relevance_candidate_target,
)
logger = logging.getLogger(__name__)
_VALID_PROVIDERS = VALID_PROVIDERS
_PROVIDER_ALIASES = PROVIDER_ALIASES
_PROVIDER_LABELS = {"pretalx": "Conference schedules"}
_EVENT_TITLE_DEDUP_STOPWORDS = frozenset({"a", "an", "and", "at", "event", "events", "in", "of", "on", "the"})
_DEFAULT_COUNT = 10
_MIN_EVENT_RELEVANCE_SCORE = 1.0
_APP_ID, _SKILL_ID, _BUILTIN_PROVIDER = "events", "search", "pretalx"


def _installed_provider_labels() -> Dict[str, str]:
    """Operator-installed providers for this skill from the server registry ({id: name})."""
    return {p.provider_id: p.name for p in get_installed_providers(_APP_ID, _SKILL_ID)}

class SearchRequestItem(BaseModel):
    """A single event search request."""

    id: Optional[Any] = Field(
        default=None,
        description="Optional caller-supplied ID for correlating responses to requests. "
            "Auto-generated as a sequential integer if not provided.",
    )

    query: Optional[str] = Field(
        default=None,
        description="Topic or theme of events to search for (e.g. 'AI', 'Python', 'hackathon', "
        "'startup', 'networking') within a known conference schedule. "
        "Required for every request unless 'conference' names a known conference "
        "(then omit it for the full schedule). Location or dates alone are not a query. "
        "Use the session topic without platform names."
    )
    location: Optional[str] = Field(
        default=None,
        description="City name or 'city, country' string (e.g. 'Berlin, Germany', 'New York'). "
        "Retained for compatibility. A known conference is required for execution.",
    )
    lat: Optional[float] = Field(
        default=None,
        description="Latitude of search center (decimal degrees). Overrides location string if provided.",
    )
    lon: Optional[float] = Field(
        default=None,
        description="Longitude of search center (decimal degrees). Overrides location string if provided.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start of date range in ISO 8601 format with optional matching IANA timezone annotation. Defaults to now if omitted.",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End of date range in ISO 8601 format. No upper bound if omitted.",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="Filter by event type: 'PHYSICAL' (default for city searches) or 'ONLINE' (virtual events).",
    )
    radius_miles: float = Field(
        default=25,
        description="Search radius in miles from the center coordinates (default: 25, ~40 km). Only for PHYSICAL events.",
    )
    count: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of events to return (default: 10, max: 50).",
    )
    relevance_criteria: Optional[str] = Field(
        default=None,
        max_length=MAX_RELEVANCE_CRITERIA_CHARS,
        description=(
            "Optional concise natural-language event-selection goal used to rank a larger "
            "candidate pool. Populate it when the user states a material purpose such as "
            "networking, promoting a product, or finding future speaking opportunities; "
            "omit it for a plain event search and never invent preferences. "
            "The query topic is checked even when this optional goal is omitted."
        ),
    )
    provider: Optional[str] = Field(
        default=None,
        description="Provider to use for this request. Overrides top-level provider if set.",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Provider list to use for this request. Overrides top-level providers if set.",
    )
    concert_tags: Optional[List[str]] = Field(default=None, description="Reserved concert tags; no concert source is configured.")
    conference: Optional[str] = Field(
        default=None,
        description=(
            "Known conference schedule to search with the Conference Schedule provider. "
            "Supported values include GPN24, 39C3, 38C3, and 37C3."
        ),
    )
    past_events: bool = Field(
        default=False,
        description=(
            "When false, conference schedule searches return only current and upcoming sessions. "
            "Set true to include sessions that have already ended."
        ),
    )


class SearchRequest(BaseModel):
    """
    Request model for event search skill.

    Always uses 'requests' array format for consistency and parallel processing.
    Each request specifies its own parameters; defaults are defined in tool_schema.
    """

    requests: List[SearchRequestItem] = Field(
        ...,
        description=(
            "Array of official conference schedule searches. A known conference is required. "
            "Optional: query, start_date, end_date, event_type, "
            "radius_miles, count, past_events."
        ),
    )
    provider: Optional[str] = Field(
        default=None,
        description="Top-level provider applied to every request unless overridden per request.",
    )
    providers: Optional[List[str]] = Field(
        default=None,
        description="Top-level provider list applied to every request unless overridden per request.",
    )


class SearchResponse(BaseModel):
    """Response model for event search skill."""

    # Results grouped by request ID. Each entry: {'id': ..., 'results': [...]}
    results: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of request results. Each entry contains 'id' (matching the "
            "request id) and 'results' array with event dicts."
        ),
    )
    provider: str = Field(
        default="auto",
        description=(
            "The provider(s) used. 'auto' means all applicable providers were searched."
        ),
    )
    providers: List[str] = Field(
        default_factory=list,
        description=(
            "List of provider IDs searched for the request "
            "(e.g. ['pretalx']). "
            "Providers can be present even when they returned zero results."
        ),
    )
    suggestions_follow_up_requests: Optional[List[str]] = Field(
        None,
        description="Suggested follow-up actions based on search results.",
    )
    error: Optional[str] = Field(None, description="Error message if the skill failed.")
    warnings: List[str] = Field(default_factory=list, description="Providers that failed during a partial search.")
    ignore_fields_for_inference: Optional[List[str]] = Field(
        default_factory=lambda: [
            "type",
            "hash",
            "cover_url",    # Image URL — not useful for LLM reasoning
            "image_url",    # Image URL — not useful for LLM reasoning
        ],
        description=(
            "Fields excluded from LLM inference to reduce token usage. "
            "Preserved in chat history for UI rendering."
        ),
    )


class SearchSkill(BaseSkill):
    """Official conference schedule search with retained result validation."""

    @classmethod
    def resolve_preview_metadata(cls, request: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve selected event providers before provider calls start."""
        raw_providers = request.get("providers")
        if isinstance(raw_providers, list) and raw_providers:
            provider_ids = [
                _PROVIDER_ALIASES.get(str(provider).lower().strip(), str(provider).lower().strip())
                for provider in raw_providers
            ]
        else:
            provider_choice = str(request.get("provider", "auto")).lower().strip()
            provider_choice = _PROVIDER_ALIASES.get(provider_choice, provider_choice)
            if provider_choice == "auto":
                provider_ids = [*_PROVIDER_LABELS, *_installed_provider_labels()]
            elif provider_choice in _VALID_PROVIDERS or provider_choice in _installed_provider_labels():
                provider_ids = [provider_choice]
            else:
                provider_ids = []

        known = {**_PROVIDER_LABELS, **_installed_provider_labels()}
        providers = [provider_id for provider_id in provider_ids if provider_id in known]
        provider = providers[0] if len(providers) == 1 else "auto"
        return {"provider": provider, "providers": providers}


    def __init__(
        self,
        app: Any,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[Dict[str, Any]] = None,
        celery_producer: Optional[Celery] = None,
        skill_operational_defaults: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialise SearchSkill.

        Args:
            app:                        BaseApp instance (required by BaseSkill)
            app_id:                     App identifier ('events')
            skill_id:                   Skill identifier ('search')
            skill_name:                 Display name for the skill
            skill_description:          Description of what the skill does
            stage:                      Deployment stage ('development' / 'production')
            full_model_reference:       Unused (the web source names its extraction model per request)
            pricing_config:             Catalog prices for display; each request group declares its own
                                        usage-based credits (backend/shared/python_utils/web_source_billing.py)
            celery_producer:            Unused for this skill (direct async execution)
            skill_operational_defaults: Optional per-skill config from app.yml
        """
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=celery_producer,
        )

        if skill_operational_defaults:
            logger.debug(
                "SearchSkill '%s' received operational_defaults: %s",
                self.skill_name,
                skill_operational_defaults,
            )

        self.suggestions_follow_up_requests: List[str] = []
        self._providers_meta: List[Dict[str, Any]] = []
        self._load_config_from_app_yml()


    @staticmethod
    def _normalize_event_type(value: Any) -> Optional[str]:
        """Normalize provider-specific event type values to the shared contract."""
        if not value:
            return None
        normalized = str(value).strip().lower().replace("-", "_")
        if normalized in {"online", "virtual", "virtual_event", "remote"}:
            return "ONLINE"
        if normalized in {"physical", "offline", "in_person", "in_person_event", "venue"}:
            return "PHYSICAL"
        return str(value).strip().upper()


    @staticmethod
    def _infer_result_event_type(event: Dict[str, Any]) -> Optional[str]:
        """Infer event type when provider payloads omit the canonical field."""
        explicit_type = SearchSkill._normalize_event_type(event.get("event_type"))
        if explicit_type:
            return explicit_type

        text_parts = [str(event.get("location") or "")]
        venue = event.get("venue")
        if isinstance(venue, dict):
            text_parts.extend(str(value or "") for value in venue.values())
            has_physical_venue = any(
                venue.get(key) for key in ("name", "address", "city", "country", "lat", "lon")
            )
        else:
            text_parts.append(str(venue or ""))
            has_physical_venue = bool(venue)

        text = " ".join(text_parts).lower()
        if any(term in text for term in ("online", "virtual", "remote", "webinar")):
            return "ONLINE"
        if has_physical_venue:
            return "PHYSICAL"
        return None


    @staticmethod
    def _parse_event_datetime(value: Any) -> Optional[datetime]:
        if not value or not isinstance(value, str):
            return None
        try:
            timestamp, separator, zone_suffix = value.strip().partition("[")
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if separator:
                if not zone_suffix.endswith("]"):
                    raise ValueError("Unclosed timezone annotation")
                zone = ZoneInfo(zone_suffix[:-1])
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=zone)
                elif parsed.astimezone(zone).utcoffset() != parsed.utcoffset():
                    raise ValueError("Timezone annotation conflicts with UTC offset")
            return parsed
        except (ValueError, ZoneInfoNotFoundError):
            logger.warning("[events:search] Invalid event datetime")
            return None


    @staticmethod
    def _align_event_datetime(value: datetime, reference: datetime) -> datetime:
        """Avoid naive/aware comparison errors from provider-local date strings."""
        if value.tzinfo is None and reference.tzinfo is not None:
            return value.replace(tzinfo=reference.tzinfo)
        if value.tzinfo is not None and reference.tzinfo is None:
            return value.replace(tzinfo=None)
        return value


    @staticmethod
    def _event_start(event: Dict[str, Any]) -> Optional[datetime]:
        """Parse an event start and attach its declared timezone when needed."""
        parsed = SearchSkill._parse_event_datetime(event.get("date_start"))
        if parsed is None or parsed.tzinfo is not None:
            return parsed
        timezone_name = event.get("timezone")
        if isinstance(timezone_name, str) and timezone_name:
            try:
                return parsed.replace(tzinfo=ZoneInfo(timezone_name))
            except ZoneInfoNotFoundError:
                logger.warning("[events:search] Invalid provider timezone")
        return parsed


    @staticmethod
    def _dedup_text(value: Any) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = "".join(char for char in normalized if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()


    @staticmethod
    def _title_tokens(event: Dict[str, Any]) -> set[str]:
        return {
            token
            for token in SearchSkill._dedup_text(event.get("title")).split()
            if token not in _EVENT_TITLE_DEDUP_STOPWORDS and not token.isdigit()
        }


    @staticmethod
    def _venue_identity(event: Dict[str, Any]) -> str:
        venue = event.get("venue")
        if isinstance(venue, dict):
            return SearchSkill._dedup_text(
                " ".join(str(venue.get(field) or "") for field in ("name", "address", "city"))
            )
        return SearchSkill._dedup_text(venue or event.get("location"))


    @staticmethod
    def _description_identity(event: Dict[str, Any]) -> str:
        return SearchSkill._dedup_text(event.get("description"))[:800]


    @staticmethod
    def _description_urls(event: Dict[str, Any]) -> set[str]:
        urls = re.findall(r"https?://[^\s\])>]+", str(event.get("description") or ""))
        return {
            normalized
            for url in urls
            if (normalized := normalize_url_for_deduplication(url.rstrip(".,;")))
        }


    @classmethod
    def _events_are_duplicates(cls, first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        first_url = normalize_url_for_deduplication(_event_result_url(first))
        second_url = normalize_url_for_deduplication(_event_result_url(second))
        if first_url and first_url == second_url:
            return True

        first_start = cls._event_start(first)
        second_start = cls._event_start(second)
        if first_start is None or second_start is None:
            return False
        second_start = cls._align_event_datetime(second_start, first_start)
        if abs((first_start - second_start).total_seconds()) > 90 * 60:
            return False

        if cls._description_urls(first) & cls._description_urls(second):
            return True

        first_tokens = cls._title_tokens(first)
        second_tokens = cls._title_tokens(second)
        if first_tokens and second_tokens:
            overlap = len(first_tokens & second_tokens) / min(len(first_tokens), len(second_tokens))
            if overlap >= 0.75:
                return True

        first_description = cls._description_identity(first)
        second_description = cls._description_identity(second)
        if (
            len(first_description) >= 80
            and first_description == second_description
            and cls._venue_identity(first) == cls._venue_identity(second)
        ):
            return True
        return False


    @classmethod
    def _deduplicate_events(cls, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep one stable representative for each real-world event."""
        unique: List[Dict[str, Any]] = []
        for event in events:
            if any(cls._events_are_duplicates(existing, event) for existing in unique):
                continue
            unique.append(event)
        return unique


    @staticmethod
    def _parse_money(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        match = re.search(r"\d+(?:[.,]\d+)?", str(value))
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            return None


    @staticmethod
    def _extract_price_amount(event: Dict[str, Any]) -> Optional[float]:
        """Extract a comparable event price when provider data exposes one."""
        for candidate in (event.get("price"), event.get("fee")):
            if candidate in (None, ""):
                continue
            if isinstance(candidate, dict):
                for key in ("amount", "min", "display"):
                    amount = SearchSkill._parse_money(candidate.get(key))
                    if amount is not None:
                        return amount
                continue
            amount = SearchSkill._parse_money(candidate)
            if amount is not None:
                return amount
        if event.get("is_paid") is False:
            return 0.0
        return None


    @staticmethod
    def _has_price_intent(query: Optional[str]) -> bool:
        if not query:
            return False
        lowered = query.lower()
        return any(term in lowered for term in ("free", "cheap", "budget", "low cost", "low-cost", "affordable"))


    @staticmethod
    def _has_accessibility_intent(query: Optional[str]) -> bool:
        if not query:
            return False
        lowered = query.lower()
        return any(term in lowered for term in ("wheelchair", "accessible", "accessibility", "barrier-free", "barrier free"))


    @staticmethod
    def _accessibility_match(event: Dict[str, Any]) -> str:
        text_parts = [str(event.get(field) or "") for field in ("title", "description", "location")]
        venue = event.get("venue")
        if isinstance(venue, dict):
            text_parts.extend(str(value or "") for value in venue.values())
        else:
            text_parts.append(str(venue or ""))
        text = " ".join(text_parts).lower()
        if any(term in text for term in ("wheelchair", "accessible", "barrier-free", "barrier free")):
            return "mentioned"
        return "unknown"


    @staticmethod
    def _apply_quality_filters(
        events: List[Dict[str, Any]],
        *,
        event_type: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        query: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply deterministic post-provider filters and ranking guardrails."""
        normalized_type = SearchSkill._normalize_event_type(event_type)
        start_dt = SearchSkill._parse_event_datetime(start_date)
        end_dt = SearchSkill._parse_event_datetime(end_date)
        price_intent = SearchSkill._has_price_intent(query)
        accessibility_intent = SearchSkill._has_accessibility_intent(query)
        applied_filters: List[str] = []
        filtered: List[Dict[str, Any]] = []
        filtered_out_count = 0

        if normalized_type:
            applied_filters.append("event_type")
        if start_dt or end_dt:
            applied_filters.append("date_window")

        for event in events:
            result = dict(event)
            result_type = SearchSkill._infer_result_event_type(result)
            if result_type:
                result["event_type"] = result_type
            if normalized_type and result_type and result_type != normalized_type:
                filtered_out_count += 1
                continue

            event_start = SearchSkill._event_start(result)
            if (start_dt or end_dt) and event_start is None:
                filtered_out_count += 1
                continue
            if start_dt and event_start and SearchSkill._align_event_datetime(event_start, start_dt) < start_dt:
                filtered_out_count += 1
                continue
            if end_dt and event_start and SearchSkill._align_event_datetime(event_start, end_dt) >= end_dt:
                filtered_out_count += 1
                continue

            constraint_matches = dict(result.get("constraint_matches") or {})
            if price_intent:
                price = SearchSkill._extract_price_amount(result)
                if price is None:
                    constraint_matches["price"] = "unknown"
                elif price == 0:
                    constraint_matches["price"] = "free"
                elif price <= 15:
                    constraint_matches["price"] = "cheap"
                else:
                    constraint_matches["price"] = "paid"
                result["price_amount"] = price
            if accessibility_intent:
                constraint_matches["accessibility"] = SearchSkill._accessibility_match(result)
            if constraint_matches:
                result["constraint_matches"] = constraint_matches
            filtered.append(result)

        if price_intent:
            def price_rank(event: Dict[str, Any]) -> tuple[int, float]:
                match = (event.get("constraint_matches") or {}).get("price")
                rank = {"free": 0, "cheap": 1, "unknown": 2, "paid": 3}.get(match, 4)
                amount = event.get("price_amount")
                numeric_amount = float(amount) if isinstance(amount, (int, float)) else float("inf")
                return rank, numeric_amount

            filtered.sort(key=price_rank)

        metadata: Dict[str, Any] = {
            "applied_filters": applied_filters,
            "filtered_out_count": filtered_out_count,
            "price_intent": "free_or_cheap" if price_intent else None,
            "accessibility_intent": accessibility_intent,
            "no_result_reason": "filtered_out" if events and not filtered else None,
        }
        if metadata["no_result_reason"]:
            metadata["suggestions"] = [
                "Relax one or more filters",
                "Try a wider date range",
                "Search another provider or nearby city",
            ]
        return filtered, metadata


    def _load_config_from_app_yml(self) -> None:
        """Load follow-up suggestions and provider metadata from app.yml."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            app_yml_path = os.path.join(os.path.dirname(current_dir), "app.yml")

            if not os.path.exists(app_yml_path):
                logger.error(
                    "app.yml not found at %s — config will use defaults",
                    app_yml_path,
                )
                return

            with open(app_yml_path, "r", encoding="utf-8") as fh:
                config = yaml.safe_load(fh)

            for skill in (config or {}).get("skills", []):
                if skill.get("id", "").strip() == "search":
                    suggestions = skill.get("suggestions_follow_up_requests", [])
                    if isinstance(suggestions, list):
                        self.suggestions_follow_up_requests = [str(s) for s in suggestions]

                    providers = skill.get("providers", [])
                    if isinstance(providers, list):
                        self._providers_meta = providers
                        logger.debug(
                            "Loaded %d provider metadata entries from app.yml",
                            len(self._providers_meta),
                        )
                    return

            logger.warning(
                "Search skill not found in app.yml — config will use defaults"
            )

        except Exception as exc:
            logger.error(
                "Error loading config from app.yml: %s",
                exc,
                exc_info=True,
            )


    def _validate_event_requests(
        self,
        requests: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """Validate event requests without letting one bad LLM item poison the batch."""
        if not requests:
            return [], [], (
                "No search requests provided. 'requests' array must contain at "
                "least one request with 'query' and 'location' (or 'lat'/'lon')."
            )

        valid_requests: List[Dict[str, Any]] = []
        invalid_results: List[Dict[str, Any]] = []
        request_ids: set[Any] = set()
        total_requests = len(requests)

        for i, req in enumerate(requests):
            request_id, error = self._validate_and_normalize_request_id(
                req=req,
                request_index=i,
                total_requests=total_requests,
                request_ids=request_ids,
                logger=logger,
            )
            if error:
                logger.error("Request %d validation failed: %s", i + 1, error)
                return [], [], error

            if not req.get("query"):
                error_message = (
                    f"Request {i + 1} (id: {request_id}) is missing the required 'query' field. "
                    "Retry with 'query' set to the event topic (for example 'AI' or 'hackathon'); "
                    "'query' may be omitted only when 'conference' names a known conference schedule."
                )
                logger.warning("[events:search] %s; preserving as per-request error", error_message)
                invalid_results.append({
                    "id": request_id,
                    "results": [],
                    "error": error_message,
                    "total_available": 0,
                })
                continue

            # Normalize before provider dispatch: providers accept ISO offsets, while
            # the tool schema also permits an IANA timezone annotation.
            normalized = dict(req)
            bounds: Dict[str, datetime] = {}
            date_error = None
            for field in ("start_date", "end_date"):
                if req.get(field) is None:
                    continue
                parsed = self._parse_event_datetime(req[field])
                if parsed is None:
                    date_error = f"Invalid {field}: expected an ISO 8601 datetime"
                    break
                bounds[field] = parsed
                normalized[field] = parsed.isoformat()
            if not date_error and len(bounds) == 2:
                start = bounds["start_date"]
                end = self._align_event_datetime(bounds["end_date"], start)
                if end <= start:
                    date_error = "Invalid date range: end_date must be after start_date"
            if date_error:
                logger.warning("[events:search] Request %s: %s", request_id, date_error)
                invalid_results.append({
                    "id": request_id, "results": [], "error": date_error,
                    "total_available": 0,
                })
                continue
            valid_requests.append(normalized)

        if not valid_requests:
            return [], invalid_results, invalid_results[0]["error"] if invalid_results else None

        return valid_requests, invalid_results, None


    async def _search_pretalx(
        self,
        query: str,
        location_str: str,
        conference: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
        count: int,
        past_events: bool,
    ) -> Tuple[List[Dict[str, Any]], int, Optional[str]]:
        """
        Search known pretalx/C3VOC conference schedules and return (events, total, error_or_None).
        Never raises — errors are returned as the third tuple element.
        """
        try:
            events, total = await pretalx_provider.search_events_async(
                query=query,
                conference=conference,
                location=location_str,
                start_date=start_date,
                end_date=end_date,
                count=count,
                past_events=past_events,
            )
            return events, total, None
        except ValueError:
            # No known conference was requested. In auto mode this is not an error.
            return [], 0, "Unknown conference schedule"
        except Exception as exc:
            logger.warning("Conference schedule search failed for query=%r: %s", query, exc)
            return [], 0, str(exc)


    @staticmethod
    def _merge_and_sort(
        *provider_results: List[Dict[str, Any]],
        count: int,
    ) -> List[Dict[str, Any]]:
        """
        Merge results from multiple providers, deduplicate by URL, and sort by date.

        Deduplication key: lowercased event URL. When two events have the same URL
        (e.g. present in two schedule exports), the first occurrence is kept.

        Sorting: ascending by date_start (soonest first). Events with no date_start
        are placed at the end.

        Args:
            *provider_results: Variable number of event lists from different providers.
            count:             Maximum number of events to return.

        Returns:
            Merged, deduplicated, sorted list limited to count.
        """
        seen_urls: set = set()
        merged: List[Dict[str, Any]] = []

        for events in provider_results:
            for event in events:
                url = (event.get("url") or "").lower().strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                merged.append(event)

        # Sort by start date ascending; None dates go to end.
        merged.sort(key=lambda e: (e.get("date_start") or "9999"))

        return merged[:count]


    @staticmethod
    def _relevance_deduplication_key(event: Dict[str, Any]) -> str:
        """Identify cross-provider copies before relevance ranking."""

        title = re.sub(r"\s+", " ", str(event.get("title") or "")).strip().lower()
        date_start = str(event.get("date_start") or "").strip().lower()
        venue = event.get("venue")
        if isinstance(venue, dict):
            venue_text = "|".join(
                str(venue.get(field) or "").strip().lower()
                for field in ("name", "address", "city")
            )
        else:
            venue_text = str(venue or event.get("location") or "").strip().lower()
        if title and date_start:
            return f"event:{title}|{date_start}|{venue_text}"
        url = normalize_url_for_deduplication(_event_result_url(event))
        if url:
            return f"url:{url}"
        return ""


    async def execute(self, request: SearchRequest, secrets_manager: Any = None,
                      **kwargs: Any) -> SearchResponse:
        """Dispatch only known conference schedules, with no proxy or discovery fallback."""
        requests = [item.model_dump() if hasattr(item, "model_dump") else dict(item)
                    for item in request.requests]
        for item in requests:
            if not item.get("providers") and not item.get("provider"):
                item["providers"] = request.providers
                item["provider"] = request.provider
            hint = item.get("provider") or request.provider or "auto"
            choices_hint = " ".join(str(choice) for choice in item.get("providers") or [])
            conference = pretalx_provider.resolve_conference(
                item.get("conference"), query=item.get("query") or "",
                location=item.get("location") or "") or pretalx_provider.resolve_conference(hint) or pretalx_provider.resolve_conference(choices_hint)
            if conference and not item.get("query"):
                item["query"] = conference
            item["conference"] = conference
        valid, groups, error = self._validate_event_requests(requests)
        if error:
            return SearchResponse(results=groups, error=error)
        errors: List[str] = []
        warnings: List[str] = []
        providers: List[str] = []
        progress = SkillProgress(self)
        # Web search and extraction prices, loaded once per call before the web is first searched.
        prices: Dict[str, Optional[WebSourcePrices]] = {}
        for item in valid:
            web_usage: Dict[str, Any] = {}
            identity, events, message, total, dispatched, provider_warnings = await self._process_single_search_request(
                item, item["id"], secrets_manager, progress=progress, policy=policy_from_skill_kwargs(kwargs),
                prices=prices, web_usage=web_usage)
            providers.extend(provider for provider in dispatched if provider not in providers)
            # Provider ids that contributed results; billing re-checks them
            # against the server's installation registry.
            group = {"id": identity, "results": events, "total_available": total,
                     "providers": list(dict.fromkeys(event.get("provider_id") or _BUILTIN_PROVIDER for event in events)),
                     # Credits of this request: web search requests plus extraction tokens it used.
                     "usage": group_usage(has_results=bool(events), failed=bool(message), web=web_usage,
                                          prices=prices.get("web"))}
            if message:
                errors.append(message)
                group["error"] = message
            if provider_warnings:
                group["warnings"] = provider_warnings
                warnings.extend(provider_warnings)
            groups.append(group)
        order = {item["id"]: index for index, item in enumerate(requests)}
        groups.sort(key=lambda group: order.get(group["id"], len(order)))
        provider = providers[0] if len(providers) == 1 else ("auto" if providers else "Unavailable")
        return SearchResponse(results=groups, provider=provider, providers=providers,
                              error="; ".join(errors) or None, warnings=warnings)

    async def _search_web(self, req: Dict[str, Any], secrets_manager: Any, progress: Optional[SkillProgress],
                          *, past_events: bool,
                          prices: Optional[Dict[str, Optional[WebSourcePrices]]] = None) -> InstalledProviderOutcome:
        """Events found on public web pages, as contract-valid results labelled with their source page.

        The web is searched only once its prices are known, so every search request and token is billable.
        """
        prices = prices if prices is not None else {}
        if "web" not in prices:
            try:
                prices["web"] = await fetch_web_source_prices(MODEL_REFS[DEFAULT_MODEL])
            except WebSourcePricingError as exc:
                logger.error("[events.search] Web source prices unavailable: %s", exc)
                prices["web"] = None
        if prices["web"] is None:
            if progress is not None:
                await progress.source_done(0)
            return InstalledProviderOutcome(WEB_PROVIDER_ID, error="Web results are unavailable right now.")
        outcome = await run_web_source(KIND_EVENT, req, secrets_manager)
        today = datetime.now(timezone.utc).date().isoformat()
        kept: List[Dict[str, Any]] = []
        for row in outcome.results:
            event = validate_events_search_result(row)
            last_day = str(row.get("date_end") or row.get("date_start") or "")[:10]
            if event is None or (not past_events and last_day < today):
                continue
            kept.append({**event, **{key: row[key] for key in
                                     ("provider", "provider_id", "source_page_url", "source_page_title")}})
        outcome.results = kept
        if progress is not None:
            await progress.source_done(len(kept))
        return outcome

    async def _process_single_search_request(self, req: Dict[str, Any], request_id: Any,
                                             secrets_manager: Any = None, progress: Optional[SkillProgress] = None,
                                             policy: Optional[InternalLlmPolicy] = None,
                                             prices: Optional[Dict[str, Optional[WebSourcePrices]]] = None,
                                             web_usage: Optional[Dict[str, Any]] = None,
                                             **kwargs: Any) -> Tuple:
        """Fetch and validate one bounded candidate pool from built-in and installed providers.

        ``progress`` counts the sources of this item (built-in conference source, installed providers, web).
        ``web_usage`` receives what the web source used (search requests, model, tokens) for billing.
        """
        choices = req.get("providers") or [req.get("provider") or "auto"]
        normalized = [_PROVIDER_ALIASES.get(str(value).lower().strip(), str(value).lower().strip())
                      for value in choices]
        installed_ids = list(_installed_provider_labels())
        if any(value not in _VALID_PROVIDERS and value not in installed_ids for value in normalized):
            return request_id, [], "Event search provider is unavailable.", 0, [], []
        selected_installed = installed_ids if "auto" in normalized else [v for v in normalized if v in installed_ids]
        conference = pretalx_provider.resolve_conference(
            req.get("conference"), query=req.get("query") or "", location=req.get("location") or "")
        if not conference:
            conference = next((pretalx_provider.resolve_conference(value) for value in choices
                               if pretalx_provider.resolve_conference(value)), None)
        run_builtin = bool(conference) and any(value in _VALID_PROVIDERS for value in normalized)
        query = req.get("query") or conference or ""
        # General discovery (no known conference) also searches public web pages, on every server; the
        # caller naming providers switches that off. Without secrets there is no web search key.
        run_web = bool(query) and not conference and "auto" in normalized and secrets_manager is not None
        if not run_builtin and not selected_installed and not run_web:
            if query and not conference and "auto" in normalized:
                # A topic that only the web can answer, on a call without the server's secrets.
                return request_id, [], "Web search is unavailable for this request.", 0, [], []
            return request_id, [], "Event search needs a topic or a known conference schedule.", 0, [], []
        criteria = normalize_relevance_criteria(req.get("relevance_criteria"))
        topic = f"Events about {query}" if query and (not conference or query.casefold() != conference.casefold()) else None
        count = max(1, min(req.get("count") or _DEFAULT_COUNT, 50))
        target = relevance_candidate_target(count) if criteria else count
        events: List[Dict[str, Any]] = []
        total = 0
        dispatched: List[str] = []
        failures: List[str] = []
        if progress is not None:
            await progress.add_sources(int(run_builtin) + len(selected_installed) + int(run_web))
        web_search = asyncio.create_task(self._search_web(
            {**req, "query": query}, secrets_manager, progress, past_events=bool(req.get("past_events")),
            prices=prices,
        )) if run_web else None
        if run_builtin:
            dispatched.append(_BUILTIN_PROVIDER)
            builtin_events, total, error = await self._search_pretalx(
                query=query, location_str=req.get("location") or "", conference=conference,
                start_date=req.get("start_date"), end_date=req.get("end_date"), count=target,
                past_events=bool(req.get("past_events")))
            if error:
                failures.append("Conference schedule search is unavailable.")
            events.extend(builtin_events)
            if progress is not None:
                await progress.source_done(len(builtin_events))
        if selected_installed:
            async def provider_done(outcome: InstalledProviderOutcome) -> None:
                if progress is not None:
                    await progress.source_done(len(outcome.results))

            outcomes = await run_installed_providers(
                _APP_ID, _SKILL_ID, selected_installed,
                events_search_input({**req, "query": query or None, "count": target}), secrets_manager,
                on_provider_done=provider_done)
            for outcome in outcomes:
                dispatched.append(outcome.provider_id)
                events.extend(outcome.results)
                total += len(outcome.results)
                if outcome.error:
                    failures.append(outcome.error)
        if web_search is not None:
            outcome = await web_search
            if web_usage is not None and outcome.usage:
                web_usage.update(outcome.usage)
            dispatched.append(WEB_PROVIDER_ID)
            events.extend(outcome.results)
            total += len(outcome.results)
            if outcome.error:
                failures.append(outcome.error)
        if failures and not events:
            return request_id, [], " ".join(failures), 0, dispatched, []
        results = []
        for event in events:
            url = _event_result_url(event)
            if url:
                results.append({**event, "url": url, "type": "event_result",
                                "hash": self._generate_result_hash(url)})
        results, quality = self._apply_quality_filters(
            results, event_type=req.get("event_type"), start_date=req.get("start_date"),
            end_date=req.get("end_date"), query=query)
        results = self._deduplicate_events(results)
        if criteria or topic:
            results = stable_deduplicate_candidates(results, key=self._relevance_deduplication_key)[:target]
            original_order = list(results)
            ranking = await rank_search_candidates(
                candidates=results, candidate_projections=[{
                    key: event.get(key) for key in ("title", "description", "date_start", "date_end",
                        "event_type", "venue", "organizer", "provider", "fee", "constraint_matches", "url")
                } for event in results], relevance_criteria=criteria or topic,
                search_parameters={"query": query, "conference": conference, "providers": dispatched,
                                   "location": req.get("location"), "start_date": req.get("start_date"),
                                   "end_date": req.get("end_date"), "event_type": req.get("event_type")},
                profile="events" if criteria else "events_topic", secrets_manager=secrets_manager,
                policy=policy)
            results = ranking.candidates
            if ranking.applied and len(ranking.scores) == len(results):
                results = [event for event, score in zip(results, ranking.scores)
                           if score >= _MIN_EVENT_RELEVANCE_SCORE]
                if not criteria:
                    retained = {id(event) for event in results}
                    results = [event for event in original_order if id(event) in retained]
        return request_id, results[:count], None, total, dispatched, failures


def _event_result_url(event: Dict[str, Any]) -> str:
    for key in ("url", "booking_url"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
