"""Companies House wrapper for the UK company register.

Official documented API: https://developer.company-information.service.gov.uk
(free API key used as the HTTP basic-auth user name, 600 requests per 5 minutes).
People with significant control are reported in bands (25-50, 50-75, 75-100 %).
Birth dates, addresses, nationality, residence and occupation are dropped.
"""

from __future__ import annotations

import re
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
)

PROVIDER_ID = "companies_house"
PROVIDER_NAME = "Companies House"
BASE_URL = "https://api.company-information.service.gov.uk"
PUBLIC_URL = "https://find-and-update.company-information.service.gov.uk"
MAX_CANDIDATES = 5
COMPANY_NUMBER_RE = re.compile(r"^(?:[A-Z]{2}\d{6}|\d{8})$")
SHARE_BAND_RE = re.compile(r"ownership-of-shares-(\d+)-to-(\d+)-percent")
LIMITATION = (
    "UK registers list people with significant control (over 25 %) in ownership bands, "
    "not exact shareholdings; smaller shareholders are not shown."
)


class CompaniesHouseClient:
    """Look up UK companies, people with significant control, officers and appointments."""

    provider_name = PROVIDER_NAME

    def __init__(self, api_key: str, *, http_client: httpx.AsyncClient | None = None, base_url: str = BASE_URL) -> None:
        if not api_key:
            raise RegisterProviderError("provider_not_configured", "Companies House has no API key configured")
        self._auth = httpx.BasicAuth(api_key, "")
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def lookup(self, query: str, *, subject: str, include: list[str]) -> dict[str, Any]:
        """Return one normalized ownership record for a UK company or officer."""
        async with borrowed_or_new(self._client, DEFAULT_TIMEOUT_SECONDS) as client:
            if subject == "person":
                return await self._person(client, query, include)
            return await self._company(client, query, include)

    async def _get(self, client: httpx.AsyncClient, path: str, **kwargs: Any) -> Any:
        return await request_json(client, "GET", f"{self._base_url}{path}", provider=PROVIDER_NAME,
                                  auth=self._auth, **kwargs)

    async def _company(self, client: httpx.AsyncClient, query: str, include: list[str]) -> dict[str, Any]:
        number = query.strip().upper()
        if COMPANY_NUMBER_RE.fullmatch(number):
            profile = await self._get(client, f"/company/{number}")
            match = {"company_number": number, "title": profile.get("company_name"),
                     "company_status": profile.get("company_status"), "company_type": profile.get("type"),
                     "address": profile.get("registered_office_address") or {}}
        else:
            data = await self._get(client, "/search/companies", params={"q": query, "items_per_page": MAX_CANDIDATES})
            match = pick_company(query, (data or {}).get("items") or [])
            number = match["company_number"]
        warnings: list[str] = []
        owners: list[dict[str, Any]] = []
        officers: list[dict[str, Any]] = []
        if "owners" in include:
            psc = await self._get(client, f"/company/{number}/persons-with-significant-control", not_found_ok=True)
            owners = normalize_psc(psc or {})
            if not owners:
                warnings.append("No current person with significant control is registered.")
        if "holdings" in include:
            warnings.append("The UK register does not list which companies a company holds shares in.")
        if "officers" in include:
            officers = normalize_officers(await self._get(client, f"/company/{number}/officers", not_found_ok=True) or {})
        return ownership_record(
            subject=company_subject(
                name=str(match.get("title") or query),
                country="GB",
                register_id=number,
                legal_form=match.get("company_type"),
                status=match.get("company_status"),
                city=(match.get("address") or {}).get("locality"),
                source_url=f"{PUBLIC_URL}/company/{number}",
            ),
            provider=PROVIDER_NAME,
            owners=owners,
            officers=officers,
            warnings=warnings,
            limitation=LIMITATION,
        )

    async def _person(self, client: httpx.AsyncClient, query: str, include: list[str]) -> dict[str, Any]:
        data = await self._get(client, "/search/officers", params={"q": query, "items_per_page": MAX_CANDIDATES})
        match = pick_officer(query, (data or {}).get("items") or [])
        path = ((match.get("links") or {}).get("self") or "").strip()
        if not path.startswith("/officers/"):
            raise RegisterProviderError("provider_error", "Companies House returned an officer without an appointments link")
        warnings: list[str] = []
        if "owners" in include or "holdings" in include:
            warnings.append("The UK register lists a person's appointments, not their shareholdings.")
        appointments = normalize_appointments(await self._get(client, path) or {})
        return ownership_record(
            subject=person_subject(name=str(match.get("title") or query), country="GB",
                                   source_url=f"{PUBLIC_URL}{path}"),
            provider=PROVIDER_NAME,
            holdings=appointments,
            warnings=warnings,
            limitation=LIMITATION,
        )


def pick_company(query: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the exact-name company or raise not_found / ambiguous."""
    if not items:
        raise RegisterProviderError("not_found", f"No UK company matches '{query}'")
    needle = query.strip().casefold()
    exact = [i for i in items if str(i.get("title") or "").casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(items) == 1:
        return items[0]
    candidates = [
        {"name": i.get("title"), "register_id": i.get("company_number"),
         "city": (i.get("address") or {}).get("locality"), "status": i.get("company_status")}
        for i in (exact or items)[:MAX_CANDIDATES]
    ]
    raise RegisterProviderError("ambiguous", f"Several UK companies match '{query}'", candidates=candidates)


def pick_officer(query: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick one officer by exact name; candidates carry the name only (no address or birth data)."""
    if not items:
        raise RegisterProviderError("not_found", f"No UK officer named '{query}'")
    needle = query.strip().casefold()
    exact = [i for i in items if str(i.get("title") or "").casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(items) == 1:
        return items[0]
    candidates = [{"name": i.get("title"), "appointment_count": i.get("appointment_count")}
                  for i in (exact or items)[:MAX_CANDIDATES]]
    raise RegisterProviderError("ambiguous", f"Several UK officers are named '{query}'", candidates=candidates)


def _share_band(natures: list[str]) -> str | None:
    for nature in natures:
        found = SHARE_BAND_RE.search(nature)
        if found:
            return f"{found.group(1)}-{found.group(2)}%"
    return None


def normalize_psc(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Current people with significant control as banded owners."""
    owners = []
    for item in data.get("items") or []:
        if item.get("ceased_on") or item.get("ceased"):
            continue
        kind = str(item.get("kind") or "")
        is_person = kind.startswith("individual")
        identification = item.get("identification") or {}
        owners.append(owner(
            name=str(item.get("name") or ""),
            owner_type="person" if is_person else "company",
            relation="significant control",
            share_band=_share_band(item.get("natures_of_control") or []),
            since=item.get("notified_on"),
            register_id=None if is_person else identification.get("registration_number"),
        ))
    return owners


def normalize_officers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Current officers with role and appointment date only."""
    return [
        officer(
            name=str(item.get("name") or ""),
            role=item.get("officer_role"),
            since=item.get("appointed_on"),
            officer_type="company" if "corporate" in str(item.get("officer_role") or "") else "person",
        )
        for item in data.get("items") or []
        if not item.get("resigned_on")
    ]


def normalize_appointments(data: dict[str, Any]) -> list[dict[str, Any]]:
    """A person's appointments as holding-style rows with role in ``relation``."""
    rows = []
    for item in data.get("items") or []:
        company = item.get("appointed_to") or {}
        number = company.get("company_number")
        rows.append(holding(
            name=str(company.get("company_name") or ""),
            country="GB",
            register_id=number,
            relation=item.get("officer_role"),
            since=item.get("appointed_on"),
            until=item.get("resigned_on"),
            status="ended" if item.get("resigned_on") else (company.get("company_status") or "current"),
            source_url=f"{PUBLIC_URL}/company/{number}" if number else None,
        ))
    return rows
