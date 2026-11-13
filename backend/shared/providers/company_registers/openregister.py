"""OpenRegister wrapper for the German commercial register (Handelsregister).

Official documented API: https://docs.openregister.de (Bearer API key).
Credits are scarce on the free plan, so each lookup makes only the calls the
requested ``include`` values need: company search costs 1 credit, owners,
holdings, company details, person search and person details cost 10 each.
Birth dates and private addresses are never copied into the result.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.shared.providers.company_registers.http import DEFAULT_TIMEOUT_SECONDS, borrowed_or_new, request_json
from backend.shared.providers.company_registers.models import (
    RegisterProviderError,
    company_subject,
    holding,
    officer,
    owner,
    ownership_record,
    person_subject,
    to_float,
)

PROVIDER_ID = "openregister"
PROVIDER_NAME = "OpenRegister"
BASE_URL = "https://api.openregister.de"
MAX_CANDIDATES = 5
LIMITATION = (
    "Shareholder data comes from documents filed with the German commercial register; "
    "it can lag behind recent transfers. Stock corporations (AG, SE) list shareholders only when filed."
)


class OpenRegisterClient:
    """Look up German companies, their shareholders, holdings and officers."""

    provider_name = PROVIDER_NAME

    def __init__(self, api_key: str, *, http_client: httpx.AsyncClient | None = None, base_url: str = BASE_URL) -> None:
        if not api_key:
            raise RegisterProviderError("provider_not_configured", "OpenRegister has no API key configured")
        self._api_key = api_key
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def lookup(self, query: str, *, subject: str, include: list[str]) -> dict[str, Any]:
        """Return one normalized ownership record for a German company or person."""
        async with borrowed_or_new(self._client, DEFAULT_TIMEOUT_SECONDS) as client:
            if subject == "person":
                return await self._person(client, query, include)
            return await self._company(client, query, include)

    async def _get(self, client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
        return await request_json(client, "GET", f"{self._base_url}{path}", provider=PROVIDER_NAME,
                                  headers={"Authorization": f"Bearer {self._api_key}"}, **kwargs)

    async def _company(self, client: httpx.AsyncClient, query: str, include: list[str]) -> dict[str, Any]:
        data = await self._get(client, "/v1/autocomplete/company", params={"query": query})
        match = pick_company(query, (data or {}).get("results") or [])
        company_id = match["company_id"]
        owners: list[dict[str, Any]] = []
        holdings: list[dict[str, Any]] = []
        officers: list[dict[str, Any]] = []
        warnings: list[str] = []
        if "owners" in include:
            owner_data = await self._get(client, f"/v1/company/{company_id}/owners",
                                         params={"best_available": "true"}, not_found_ok=True)
            if owner_data is None:
                warnings.append("The register has no shareholder list for this company.")
            else:
                owners = normalize_owners(owner_data)
        if "holdings" in include:
            holdings = normalize_company_holdings(await self._get(client, f"/v1/company/{company_id}/holdings") or {})
        if "officers" in include:
            officers = normalize_officers(await self._get(client, f"/v1/company/{company_id}") or {})
        return ownership_record(
            subject=company_subject(
                name=str(match.get("name") or query),
                country="DE",
                register_id=_register_id(match),
                legal_form=match.get("legal_form"),
                status="active" if match.get("active") else "inactive",
                city=((match.get("address") or {}).get("city")),
                source_url=None,
            ),
            provider=PROVIDER_NAME,
            owners=owners,
            holdings=holdings,
            officers=officers,
            warnings=warnings,
            limitation=LIMITATION,
        )

    async def _person(self, client: httpx.AsyncClient, query: str, include: list[str]) -> dict[str, Any]:
        body = {"query": {"value": query}, "pagination": {"page": 1, "per_page": MAX_CANDIDATES}}
        data = await request_json(client, "POST", f"{self._base_url}/v1/search/person", provider=PROVIDER_NAME,
                                  headers={"Authorization": f"Bearer {self._api_key}"}, json=body)
        match = pick_person(query, (data or {}).get("results") or [])
        person_id = match["id"]
        warnings: list[str] = []
        if "owners" in include:
            warnings.append("Owners apply to companies; for a person the register lists holdings and positions.")
        holdings: list[dict[str, Any]] = []
        appointments: list[dict[str, Any]] = []
        if "holdings" in include or "owners" in include:
            holdings = normalize_company_holdings(await self._get(client, f"/v1/person/{person_id}/holdings") or {})
        if "officers" in include:
            appointments = normalize_positions(await self._get(client, f"/v1/person/{person_id}") or {})
        return ownership_record(
            subject=person_subject(name=str(match.get("name") or query), country="DE", city=match.get("city")),
            provider=PROVIDER_NAME,
            holdings=holdings + appointments,
            warnings=warnings,
            limitation=LIMITATION,
        )


def _register_id(entry: dict[str, Any]) -> str | None:
    number = entry.get("register_number")
    kind = entry.get("register_type")
    court = entry.get("register_court")
    if not number:
        return entry.get("company_id")
    label = f"{kind} {number}" if kind else str(number)
    return f"{label}, {court}" if court else label


def pick_company(query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose the one company the query names, or raise not_found / ambiguous."""
    if not results:
        raise RegisterProviderError("not_found", f"No German company matches '{query}'")
    needle = query.strip().casefold()
    exact = [r for r in results if str(r.get("name") or "").casefold() == needle
             or str(r.get("register_number") or "").casefold() == needle
             or str(r.get("company_id") or "").casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(results) == 1:
        return results[0]
    candidates = [
        {"name": r.get("name"), "register_id": _register_id(r), "city": (r.get("address") or {}).get("city"),
         "status": "active" if r.get("active") else "inactive"}
        for r in (exact or results)[:MAX_CANDIDATES]
    ]
    raise RegisterProviderError("ambiguous", f"Several German companies match '{query}'", candidates=candidates)


def pick_person(query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose one person by exact name; candidates carry name and city only."""
    if not results:
        raise RegisterProviderError("not_found", f"No person named '{query}' appears in the German register")
    needle = query.strip().casefold()
    exact = [r for r in results if str(r.get("name") or "").casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(results) == 1:
        return results[0]
    candidates = [{"name": r.get("name"), "city": r.get("city")} for r in (exact or results)[:MAX_CANDIDATES]]
    raise RegisterProviderError("ambiguous", f"Several people named '{query}' appear in the German register",
                                candidates=candidates)


def normalize_owners(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map OpenRegister owners to normalized owners, dropping birth data and residence."""
    owners = []
    for item in data.get("owners") or []:
        is_person = item.get("type") == "natural_person"
        natural = item.get("natural_person") or {}
        name = item.get("name") or natural.get("full_name") or (item.get("legal_person") or {}).get("name") or ""
        owners.append(owner(
            name=str(name),
            owner_type="person" if is_person else "company",
            relation=item.get("relation_type"),
            share_percent=to_float(item.get("percentage_share")),
            nominal_amount=to_float(item.get("nominal_share")),
            currency="EUR" if item.get("nominal_share") is not None else None,
            since=item.get("start"),
            register_id=None if is_person else item.get("id"),
        ))
    return owners


def normalize_company_holdings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map company or person holdings; ended holdings keep their end date."""
    return [
        holding(
            name=str(item.get("name") or ""),
            country="DE",
            register_id=item.get("company_id"),
            relation=item.get("relation_type"),
            share_percent=to_float(item.get("percentage_share")),
            since=item.get("start"),
            until=item.get("end"),
            status="ended" if item.get("end") else "current",
        )
        for item in data.get("holdings") or []
    ]


def normalize_positions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a person's management positions to holding-style appointment rows."""
    rows = []
    for item in data.get("management_positions") or []:
        detail = item.get("role_detail") or {}
        rows.append(holding(
            name=str(item.get("company_name") or ""),
            country="DE",
            register_id=item.get("register_id"),
            relation=detail.get("label_en") or item.get("role"),
            since=item.get("start_date"),
            until=item.get("end_date"),
            status="ended" if item.get("end_date") else "current",
        ))
    return rows


def normalize_officers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Current representatives only; natural-person details stay behind."""
    officers = []
    for item in data.get("representation") or []:
        if item.get("end_date"):
            continue
        detail = item.get("role_detail") or {}
        officers.append(officer(
            name=str(item.get("name") or ""),
            role=detail.get("label_en") or item.get("role"),
            since=item.get("start_date"),
            officer_type="person" if item.get("type") == "natural_person" else "company",
        ))
    return officers
