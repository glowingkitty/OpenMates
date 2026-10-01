"""Grouped, bounded Gandi domain checks and discovery."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.gandi import GandiClient, SUPPORTED_CURRENCIES
from backend.shared.python_utils.search_relevance import (
    normalize_relevance_criteria,
    rank_search_candidates,
)

logger = logging.getLogger(__name__)

MAX_CHECKED = 40
GROUP_DEADLINE_SECONDS = 40
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_ISO_COUNTRIES = frozenset((
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL "
    "BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU "
    "CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA "
    "GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID "
    "IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB "
    "LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT "
    "MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL "
    "PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN "
    "SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG "
    "UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
).split())


def _domain(value: str) -> tuple[str, str]:
    """Validate a complete DNS name locally, including Unicode/IDNA labels."""
    if not isinstance(value, str) or not value or len(value) > 253 or value != value.strip():
        raise ValueError("Invalid domain name")
    raw = value.rstrip(".").lower()
    if "." not in raw:
        raise ValueError("A full domain name is required")
    try:
        ascii_name = raw.encode("idna").decode("ascii")
        if len(ascii_name) > 253 or any(not _LABEL.fullmatch(label) for label in ascii_name.split(".")):
            raise ValueError("Invalid domain name")
        return ascii_name, ascii_name.encode("ascii").decode("idna")
    except UnicodeError as exc:
        raise ValueError("Invalid domain name") from exc


def _short_name(value: str) -> str:
    try:
        ascii_name = value.lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid domain name") from exc
    if not _LABEL.fullmatch(ascii_name):
        raise ValueError("Invalid domain name")
    return ascii_name


def _tld(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid TLD")
    raw = value.strip().lstrip(".").lower()
    if not raw or len(raw) > 100:
        raise ValueError("Invalid TLD")
    ascii_name, _ = _domain("test." + raw)
    suffix = ascii_name[5:]
    if not all(_LABEL.fullmatch(label) for label in suffix.split(".")):
        raise ValueError("Invalid TLD")
    return suffix


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("Invalid provider result")


def _finite(value: Any) -> Any:
    """Do not leak non-JSON numeric sentinels from malformed provider output."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_finite(child) for child in value]
    return value


def _safe_child(value: Any, *, country: str, currency: str) -> dict[str, Any]:
    """Expose only checked identity, status and supplied quote facts."""
    item = _finite(_plain(value))
    ascii_name, unicode_name = _domain(item.get("domain_ascii", ""))
    if item.get("currency") not in (None, currency) or item.get("country") not in (None, country):
        raise ValueError("Provider quote context does not match request")
    status = item.get("availability")
    if status not in ("available", "unavailable", "unknown"):
        status = "unknown"
    registration = item.get("registration") if isinstance(item.get("registration"), list) else []
    renewal = item.get("renewal") if isinstance(item.get("renewal"), list) else []
    registration = [_plain(product) for product in registration]
    renewal = [_plain(product) for product in renewal]

    def tiers(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for product in products:
            for tier in product.get("tiers", []):
                if not isinstance(tier, dict):
                    continue
                output.append({
                    **tier,
                    "unit": tier.get("duration_unit"),
                    "duration_range": {
                        "minimum": tier.get("min_duration"),
                        "maximum": tier.get("max_duration"),
                    },
                    "minimum_term": (
                        f"{tier['min_duration']} {tier['duration_unit']}"
                        if tier.get("min_duration") and tier.get("duration_unit") else None
                    ),
                    "price_excluding_tax": tier.get("price_before_taxes"),
                    "price_including_tax": tier.get("price_after_taxes"),
                    "normal_price": tier.get("normal_price_after_taxes"),
                    "product_name": product.get("name"),
                    "product_status": product.get("status"),
                    "product_taxes": product.get("taxes", []),
                    "product_phases": product.get("phases", []),
                })
        return output

    restriction = item.get("restriction")
    url = "https://shop.gandi.net/en/domain/suggest?" + urlencode({"search": ascii_name})
    return {
        "type": "domain_result",
        "domain_ascii": ascii_name,
        "domain_unicode": unicode_name,
        "availability": status,
        "provider": "Gandi",
        "provider_status": item.get("provider_status"),
        "premium": item.get("premium"),
        "reserved": item.get("reserved"),
        "corporate": item.get("corporate"),
        "restrictions": [restriction] if isinstance(restriction, str) and restriction else [],
        "registration_phase": item.get("phase"),
        "registration_tiers": tiers(registration),
        "renewal_tiers": tiers(renewal),
        "registration": registration,
        "renewal": renewal,
        "taxes": item.get("taxes") if isinstance(item.get("taxes"), list) else [],
        "pricing_status": item.get("pricing_status"),
        "pricing_error": "Price unavailable" if item.get("pricing_error") else None,
        "currency": currency,
        "country": country,
        "checked_at": item.get("checked_at") or None,
        "provider_url": url,
        "url": url,
        "check_error": "Domain check unavailable" if item.get("error") else None,
    }


class DomainSearchRequestItem(BaseModel):
    """One independent exact check or bounded discovery request."""

    model_config = ConfigDict(extra="forbid")

    id: str | int | None = None
    query: str
    tlds: list[str] | None = Field(default=None, max_length=5)
    country: str = "DE"
    currency: str = "EUR"
    max_results: int = Field(default=10, ge=1, le=20, strict=True)
    availability: Literal["prefer_available", "available_only", "all"] = "prefer_available"
    relevance_criteria: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def valid_id(cls, value: str | int | None) -> str | int | None:
        if isinstance(value, bool):
            raise ValueError("Invalid request ID")
        return value

    @field_validator("query")
    @classmethod
    def valid_query(cls, value: str) -> str:
        query = value.strip()
        if not query or any(ord(char) < 32 for char in query):
            raise ValueError("Invalid search query")
        if "." in query:
            if len(query) > 253:
                raise ValueError("Invalid domain name")
            _domain(query)
        else:
            if len(query) > 100:
                raise ValueError("Invalid search query")
            if " " not in query:
                _short_name(query)
        return query

    @field_validator("tlds")
    @classmethod
    def valid_tlds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(_tld(item) for item in value))

    @field_validator("country")
    @classmethod
    def valid_country(cls, value: str) -> str:
        value = value.upper()
        if not _COUNTRY.fullmatch(value) or value not in _ISO_COUNTRIES:
            raise ValueError("Invalid country code")
        return value

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        value = value.upper()
        if value not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported currency")
        return value

    @field_validator("relevance_criteria")
    @classmethod
    def valid_criteria(cls, value: str | None) -> str | None:
        return normalize_relevance_criteria(value)


class DomainSearchRequest(BaseModel):
    """Grouped requests; raw children permit independent validation errors."""

    requests: list[Any] = Field(min_length=1, max_length=5)


class DomainSearchResponse(BaseModel):
    """Groups preserve selection, checked evidence, and safe failure status."""

    success: bool = False
    app_id: str = "hosting"
    skill_id: str = "search_domains"
    provider: str = "Gandi"
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class SearchDomainsSkill(BaseSkill):
    """Search domain availability without purchasing or reserving names."""

    async def execute(
        self,
        request: DomainSearchRequest | dict[str, Any] | None = None,
        requests: list[Any] | None = None,
        secrets_manager: Any = None,
        provider_client: GandiClient | None = None,
        **kwargs: Any,
    ) -> DomainSearchResponse:
        try:
            raw = requests if requests is not None else (
                request.requests if isinstance(request, DomainSearchRequest)
                else request.get("requests") if isinstance(request, dict) else None
            )
            if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
                raise ValueError("requests must contain one to five groups")
        except ValueError as exc:
            return DomainSearchResponse(error=str(exc))

        seen_ids: set[str | int] = set()
        for index, raw_item in enumerate(raw, 1):
            raw_item = raw_item.model_dump() if hasattr(raw_item, "model_dump") else raw_item
            if not isinstance(raw_item, dict):
                continue
            explicit_id = raw_item.get("id")
            if explicit_id is not None and (isinstance(explicit_id, bool) or not isinstance(explicit_id, (str, int))):
                continue  # The affected group reports its own validation error.
            group_id = explicit_id if explicit_id is not None else index
            if group_id in seen_ids:
                return DomainSearchResponse(error="Duplicate request IDs")
            seen_ids.add(group_id)

        client = provider_client or GandiClient(secrets_manager)
        semaphore = asyncio.Semaphore(2)
        groups = await asyncio.gather(*(
            self._group(raw_item, index, client, semaphore, secrets_manager)
            for index, raw_item in enumerate(raw, 1)
        ))
        return DomainSearchResponse(
            success=any(group["error"] is None for group in groups),
            results=groups,
            error=(
                "Invalid domain search request"
                if all(group["error"] == "Invalid domain search request" for group in groups)
                else "Domain provider unavailable"
                if all(group["error"] for group in groups)
                else None
            ),
        )

    async def _group(
        self,
        raw: Any,
        index: int,
        client: GandiClient,
        semaphore: asyncio.Semaphore,
        secrets_manager: Any,
    ) -> dict[str, Any]:
        raw = raw.model_dump() if hasattr(raw, "model_dump") else raw
        raw_id = raw.get("id") if isinstance(raw, dict) else None
        group_id = raw_id if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else index
        query = raw.get("query", "") if isinstance(raw, dict) else ""
        group: dict[str, Any] = {
            "id": group_id, "query": query if isinstance(query, str) else "",
            "provider": "Gandi", "country": "DE", "currency": "EUR",
            "checked_at": None, "partial": False, "warnings": [],
            "results": [], "checked_results": [], "error": None,
            "relevance_applied": False,
        }
        try:
            item = DomainSearchRequestItem.model_validate(raw)
        except (ValidationError, ValueError):
            group["error"] = "Invalid domain search request"
            return group
        group.update(query=item.query, country=item.country, currency=item.currency)
        try:
            return await asyncio.wait_for(
                self._run_group(group, item, client, semaphore, secrets_manager),
                timeout=GROUP_DEADLINE_SECONDS,
            )
        except asyncio.TimeoutError:
            group.update(partial=True, error="Domain provider deadline exceeded")
            group["warnings"].append("Some domain checks exceeded the deadline")
            self._select_results(group, item)
        except Exception:
            logger.exception("hosting.search_domains group failed")
            group.update(partial=True, error="Domain provider unavailable")
        return group

    async def _run_group(
        self,
        group: dict[str, Any],
        item: DomainSearchRequestItem,
        client: GandiClient,
        semaphore: asyncio.Semaphore,
        secrets_manager: Any,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + GROUP_DEADLINE_SECONDS * 0.99

        async def lookup(domain: str) -> Any:
            async with semaphore:
                return await client.lookup(domain, currency=item.currency, country=item.country, lang="en")

        async def search(tld: str | None) -> Any:
            async with semaphore:
                return await client.search(
                    item.query, max_results=MAX_CHECKED, currency=item.currency,
                    country=item.country, lang="en", tld=tld,
                )

        async def collect(operations: list[Any]) -> list[Any]:
            tasks = [asyncio.create_task(operation) for operation in operations]
            try:
                done, pending = await asyncio.wait(
                    tasks, timeout=max(0.0, deadline - time.monotonic()),
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                return [
                    asyncio.TimeoutError() if task not in done or task.cancelled()
                    else task.exception() if task.exception() else task.result()
                    for task in tasks
                ]
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()

        exact = "." in item.query
        short_with_tlds = not exact and " " not in item.query and bool(item.tlds)
        if exact:
            operations = [lookup(_domain(item.query)[0])]
        elif short_with_tlds:
            domains = [_domain(f"{item.query}.{tld}")[0] for tld in item.tlds or []]
            operations = [lookup(domain) for domain in dict.fromkeys(domains)]
        else:
            operations = [search(tld) for tld in (item.tlds or [None])]

        outcomes = await collect(operations)
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        failures = 0
        malformed_children = 0
        partial = False
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                failures += 1
                partial = True
                logger.warning("hosting.search_domains provider operation failed: %s", type(outcome).__name__)
                continue
            provider_result = _plain(outcome)
            if "results" in provider_result:
                children = provider_result.get("results") or []
                if provider_result.get("partial") or provider_result.get("error"):
                    partial = True
                if provider_result.get("error") and not children:
                    failures += 1
            else:
                children = [outcome]
                if provider_result.get("error") or provider_result.get("availability") == "unknown":
                    partial = True
            group["checked_at"] = group["checked_at"] or provider_result.get("checked_at")
            for child in children:
                try:
                    normalized = _safe_child(child, country=item.country, currency=item.currency)
                except ValueError:
                    partial = True
                    malformed_children += 1
                    continue
                name = normalized["domain_ascii"]
                if name in seen:
                    continue
                if item.tlds and not exact and not any(name.endswith("." + suffix) for suffix in item.tlds):
                    continue
                if exact and name != _domain(item.query)[0]:
                    continue
                seen.add(name)
                candidates.append(normalized)
                group["checked_results"] = candidates[:MAX_CHECKED]
                if len(candidates) >= MAX_CHECKED:
                    break
            if len(candidates) >= MAX_CHECKED:
                break
        # Exact requested names are checked first. Suggestions may then fill the
        # remaining bounded pool for a short name, but never replace those checks.
        if short_with_tlds and len(candidates) < MAX_CHECKED and sum(
            child["availability"] == "available" for child in candidates
        ) < item.max_results:
            suggestion_outcomes = await collect([search(tld) for tld in item.tlds or []])
            outcomes.extend(suggestion_outcomes)
            for outcome in suggestion_outcomes:
                if isinstance(outcome, BaseException):
                    failures += 1
                    partial = True
                    continue
                payload = _plain(outcome)
                if payload.get("partial") or payload.get("error"):
                    partial = True
                if payload.get("error") and not payload.get("results"):
                    failures += 1
                for child in payload.get("results") or []:
                    try:
                        normalized = _safe_child(child, country=item.country, currency=item.currency)
                    except ValueError:
                        partial = True
                        malformed_children += 1
                        continue
                    name = normalized["domain_ascii"]
                    if name in seen or not any(name.endswith("." + suffix) for suffix in item.tlds or []):
                        continue
                    seen.add(name)
                    candidates.append(normalized)
                    group["checked_results"] = candidates[:MAX_CHECKED]
                    if len(candidates) >= MAX_CHECKED:
                        break
                if len(candidates) >= MAX_CHECKED:
                    break
        group["checked_at"] = group["checked_at"] or _utc_now()
        group["partial"] = partial
        if failures:
            group["warnings"].append("Some domain checks were unavailable")
        if malformed_children:
            group["warnings"].append("Some domain results could not be verified")
        if any(candidate["availability"] == "unknown" for candidate in candidates):
            group["warnings"].append("Some domain availability checks were inconclusive")
            group["partial"] = True
        if any(
            candidate["availability"] == "available" and (
                candidate["pricing_status"] in ("missing", "unknown")
                or not candidate["registration_tiers"]
            ) for candidate in candidates
        ):
            group["warnings"].append("Some registration prices were unavailable")
            group["partial"] = True
        if group["partial"] and not group["warnings"]:
            group["warnings"].append("Some domain checks were incomplete")

        eligible = [candidate for candidate in candidates if (
            candidate["availability"] == "available" if item.availability == "available_only"
            else candidate["availability"] != "unknown"
        )]
        eligible_before_ranking = {candidate["domain_ascii"] for candidate in eligible}
        if item.relevance_criteria and eligible:
            projections = [self._projection(candidate) for candidate in eligible]
            try:
                ranking = await asyncio.wait_for(rank_search_candidates(
                    candidates=eligible,
                    candidate_projections=projections,
                    relevance_criteria=item.relevance_criteria,
                    search_parameters={
                        "query": item.query, "tlds": item.tlds,
                        "currency": item.currency, "country": item.country,
                        "availability": item.availability,
                    },
                    profile="hosting_domains",
                    secrets_manager=secrets_manager,
                ), timeout=max(0.0, deadline - time.monotonic()))
                eligible = ranking.candidates
                group["relevance_applied"] = bool(ranking.applied)
                if ranking.applied and len(ranking.scores) == len(eligible):
                    eligible = [candidate for candidate, score in zip(eligible, ranking.scores) if score >= 1]
                if not ranking.applied:
                    group["warnings"].append("Requirements could not be evaluated; showing provider matches")
            except Exception:
                logger.exception("hosting.search_domains relevance ranking failed")
                group["warnings"].append("Requirements could not be evaluated; showing provider matches")
        elif item.relevance_criteria:
            group["warnings"].append("Requirements could not be evaluated; showing provider matches")

        group["checked_results"] = eligible + [
            candidate for candidate in candidates
            if candidate["domain_ascii"] not in eligible_before_ranking
        ]
        self._select_results(group, item)
        if not candidates and (failures or malformed_children):
            group["error"] = "Domain provider unavailable"
        elif exact and candidates and all(candidate["availability"] == "unknown" for candidate in candidates):
            group["error"] = "Domain availability could not be checked"
        return group

    @staticmethod
    def _select_results(group: dict[str, Any], item: DomainSearchRequestItem) -> None:
        candidates = group["checked_results"]
        eligible = [candidate for candidate in candidates if (
            candidate["availability"] == "available" if item.availability == "available_only"
            else candidate["availability"] != "unknown"
        )]
        if item.availability == "all":
            selected = eligible
        elif item.availability == "available_only":
            selected = eligible
        else:
            available = [candidate for candidate in eligible if candidate["availability"] == "available"]
            unavailable = [candidate for candidate in eligible if candidate["availability"] == "unavailable"]
            selected = available + unavailable
        group["results"] = selected[:item.max_results]
        if "." in item.query and item.availability == "available_only" and any(
            candidate["availability"] == "unavailable" for candidate in candidates
        ):
            if "The checked domain is unavailable" not in group["warnings"]:
                group["warnings"].append("The checked domain is unavailable")

    @staticmethod
    def _projection(candidate: dict[str, Any]) -> dict[str, Any]:
        # Keep both quote kinds inside the shared projection budget. Full provider
        # products, options and repeated aliases would truncate the renewal facts.
        def quotes(field: str, prefix: str) -> dict[str, dict[str, Any]]:
            fields = (
                "unit", "price_excluding_tax",
                "price_including_tax", "normal_price", "discount",
            )
            # The shared sanitizer retains only two nested levels. Keep each
            # quote directly on the projection so its numeric facts survive.
            return {
                f"{prefix}_{index + 1}": {
                    **{key: tier.get(key) for key in fields},
                    "minimum_term": tier.get("duration_range", {}).get("minimum"),
                    "maximum_term": tier.get("duration_range", {}).get("maximum"),
                }
                for index, tier in enumerate(candidate[field][:2])
            }

        return {
            "domain": candidate["domain_ascii"],
            "availability": candidate["availability"],
            "premium": candidate["premium"],
            "restrictions": [text[:200] for text in candidate["restrictions"][:1]],
            **quotes("registration_tiers", "registration_quote"),
            **quotes("renewal_tiers", "renewal_quote"),
            "currency": candidate["currency"],
            "country": candidate["country"],
        }
