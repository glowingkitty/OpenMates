"""Business company ownership skill.

Looks up who owns or runs a company, or which companies a person holds or
directs, in the official company register of the requested country. Each
request routes by its ``country`` to exactly one register: DE OpenRegister,
GB Companies House, FR Recherche d'entreprises. A country without a register
returns ``coverage_gap`` and never falls back to another country's source.
Successful lookups are cached for 7 days because the German source has a
small monthly allowance.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.company_registers import (
    CompaniesHouseClient,
    OpenRegisterClient,
    RechercheEntreprisesClient,
    RegisterProviderError,
    provider_api_key,
)

logger = logging.getLogger(__name__)

MAX_REQUESTS = 5
CACHE_TTL_SECONDS = 7 * 24 * 3600
CACHE_PREFIX = "business:company_ownership:v1:"
INCLUDE_VALUES = ("owners", "holdings", "officers")
COUNTRY_PROVIDERS: dict[str, tuple[str, str]] = {
    "DE": ("openregister", "OpenRegister"),
    "GB": ("companies_house", "Companies House"),
    "FR": ("recherche_entreprises", "Annuaire des Entreprises"),
}
COUNTRY_ALIASES = {"UK": "GB"}
LIMITATION = "Register data is public business information, not legal or investment advice."


class RegisterClient(Protocol):
    provider_name: str

    async def lookup(self, query: str, *, subject: str, include: list[str]) -> dict[str, Any]: ...


class CacheLike(Protocol):
    async def get(self, key: str) -> Any: ...

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool: ...


class OwnershipRequest(BaseModel):
    """One register lookup."""

    model_config = ConfigDict(extra="forbid")

    id: str | int | None = None
    query: str = Field(min_length=1, max_length=160)
    subject: Literal["company", "person"] = "company"
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    include: list[Literal["owners", "holdings", "officers"]] = Field(default_factory=lambda: ["owners"], max_length=3)

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value

    @field_validator("country")
    @classmethod
    def _upper_country(cls, value: str) -> str:
        value = value.upper()
        return COUNTRY_ALIASES.get(value, value)

    @field_validator("include")
    @classmethod
    def _dedupe_include(cls, value: list[str]) -> list[str]:
        return [item for item in INCLUDE_VALUES if item in value] or ["owners"]


class CompanyOwnershipResponse(BaseModel):
    success: bool = False
    app_id: str = "business"
    skill_id: str = "company_ownership"
    status: str = "finished"
    query: str = ""
    providers: list[str] = Field(default_factory=list)
    result_count: int = 0
    records: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitation: str = LIMITATION
    summary: str | None = None
    error: str | None = None
    error_code: str | None = None
    ignore_fields_for_inference: list[str] = Field(
        default_factory=lambda: ["records.subject.source_url", "records.holdings.source_url"]
    )


class CompanyOwnershipSkill(BaseSkill):
    """Look up company owners, holdings and officers in official registers."""

    async def execute(
        self,
        requests: list[dict[str, Any]] | None = None,
        secrets_manager: Any = None,
        cache_service: CacheLike | None = None,
        provider_clients: dict[str, RegisterClient] | None = None,
        **kwargs: Any,
    ) -> CompanyOwnershipResponse:
        del kwargs
        try:
            items = parse_requests(requests)
        except ValueError as exc:
            return CompanyOwnershipResponse(error=str(exc), error_code="invalid_request")

        needs_key = not provider_clients and any(i.country in ("DE", "GB") for i in items)
        if secrets_manager is None and needs_key:
            secrets_manager, failure = await self._get_or_create_secrets_manager(
                secrets_manager=None,
                skill_name="CompanyOwnershipSkill",
                error_response_factory=lambda msg: CompanyOwnershipResponse(error=msg, error_code="provider_error"),
                logger=logger,
            )
            if failure is not None:
                return failure
        cache = cache_service if cache_service is not None else _default_cache()
        records: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        providers: list[str] = []
        for item in items:
            try:
                record = await self._lookup(item, secrets_manager, cache, provider_clients or {})
            except RegisterProviderError as exc:
                error: dict[str, Any] = {"query": item.query, "country": item.country, "code": exc.code,
                                         "message": exc.message}
                if exc.candidates:
                    error["candidates"] = exc.candidates
                if item.id is not None:
                    error["id"] = item.id
                errors.append(error)
                continue
            if item.id is not None:
                record = {**record, "id": item.id}
            records.append(record)
            if record["provider"] not in providers:
                providers.append(record["provider"])

        query = ", ".join(item.query for item in items)
        warnings = list(dict.fromkeys(w for r in records for w in r.get("warnings") or []))
        if not records:
            first = errors[0] if errors else {"code": "not_found", "message": "No register entry was found"}
            return CompanyOwnershipResponse(query=query, errors=errors, error=first["message"],
                                            error_code=first["code"])
        summary = f"Register data for {', '.join(r['subject']['name'] for r in records)}"
        if errors:
            summary += f" ({len(errors)} unresolved)"
        return CompanyOwnershipResponse(
            success=True,
            query=query,
            providers=providers,
            result_count=len(records),
            records=records,
            errors=errors,
            warnings=warnings,
            summary=summary,
        )

    async def _lookup(
        self,
        item: OwnershipRequest,
        secrets_manager: Any,
        cache: CacheLike | None,
        injected: dict[str, RegisterClient],
    ) -> dict[str, Any]:
        route = COUNTRY_PROVIDERS.get(item.country)
        if route is None:
            supported = ", ".join(COUNTRY_PROVIDERS)
            raise RegisterProviderError(
                "coverage_gap",
                f"No official company register is connected for {item.country}; supported: {supported}.",
            )
        provider_id, _name = route
        key = cache_key(item)
        if cache is not None:
            cached = await cache.get(key)
            if isinstance(cached, dict) and cached.get("subject"):
                return cached
        client = injected.get(provider_id) or await build_client(provider_id, secrets_manager)
        record = await client.lookup(item.query, subject=item.subject, include=list(item.include))
        if cache is not None:
            await cache.set(key, record, ttl=CACHE_TTL_SECONDS)
        return record

    @classmethod
    def resolve_preview_metadata(cls, request: dict[str, Any]) -> dict[str, Any]:
        items = [r for r in request.get("requests") or [] if isinstance(r, dict)]
        countries = [str(r.get("country") or "").upper() for r in items]
        providers = [COUNTRY_PROVIDERS[c][1] for c in dict.fromkeys(countries) if c in COUNTRY_PROVIDERS]
        return {
            "provider": providers[0] if len(providers) == 1 else "Company registers",
            "providers": providers,
            "query": ", ".join(str(r.get("query") or "").strip() for r in items if r.get("query")),
        }


def parse_requests(requests: list[dict[str, Any]] | None) -> list[OwnershipRequest]:
    """Validate the request list; raise ValueError with a model-readable message."""
    if not requests:
        raise ValueError("Company ownership needs at least one request with query and country")
    if len(requests) > MAX_REQUESTS:
        raise ValueError(f"Company ownership supports at most {MAX_REQUESTS} requests per call")
    try:
        return [OwnershipRequest.model_validate(item) for item in requests]
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ()))
        raise ValueError(f"Invalid request: {field}: {first.get('msg')}") from exc


def cache_key(item: OwnershipRequest) -> str:
    raw = "|".join([item.country, item.subject, ",".join(item.include), item.query.casefold()])
    return CACHE_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def build_client(provider_id: str, secrets_manager: Any) -> RegisterClient:
    """Create the register client for one provider, reading its key when it needs one."""
    if provider_id == "recherche_entreprises":
        return RechercheEntreprisesClient()
    api_key = await provider_api_key(provider_id, secrets_manager)
    if not api_key:
        name = COUNTRY_PROVIDERS["DE" if provider_id == "openregister" else "GB"][1]
        raise RegisterProviderError("provider_not_configured", f"{name} is not configured on this server yet.")
    if provider_id == "openregister":
        return OpenRegisterClient(api_key)
    return CompaniesHouseClient(api_key)


def _default_cache() -> CacheLike | None:
    from backend.core.api.app.services.cache import CacheService

    return CacheService()
