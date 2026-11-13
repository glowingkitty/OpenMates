"""Recherche d'entreprises wrapper for the French company directory.

Official documented open-data API by the French State (DINUM), no key:
https://recherche-entreprises.api.gouv.fr/docs/ (7 requests per second).
It lists company directors, not shareholders; the beneficial-owner register is
not public in France. Birth month/year and nationality are dropped.
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
    ownership_record,
    person_subject,
)

PROVIDER_ID = "recherche_entreprises"
PROVIDER_NAME = "Annuaire des Entreprises"
BASE_URL = "https://recherche-entreprises.api.gouv.fr"
PUBLIC_URL = "https://annuaire-entreprises.data.gouv.fr/entreprise"
MAX_CANDIDATES = 5
SIREN_RE = re.compile(r"^\d{9}$")
LEGAL_FORMS = {
    "5710": "SAS",
    "5720": "SASU",
    "5499": "SARL",
    "5498": "EURL",
    "5599": "SA",
    "5505": "SA",
    "6540": "SCI",
    "9220": "Association",
}
LIMITATION = (
    "The French directory lists directors, not shareholders; the beneficial-owner register "
    "is not public in France."
)


class RechercheEntreprisesClient:
    """Look up French companies and their directors, or the companies a person directs."""

    provider_name = PROVIDER_NAME

    def __init__(self, *, http_client: httpx.AsyncClient | None = None, base_url: str = BASE_URL) -> None:
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def lookup(self, query: str, *, subject: str, include: list[str]) -> dict[str, Any]:
        """Return one normalized record for a French company or company director."""
        async with borrowed_or_new(self._client, DEFAULT_TIMEOUT_SECONDS) as client:
            if subject == "person":
                return await self._person(client, query, include)
            return await self._company(client, query, include)

    async def _search(self, client: httpx.AsyncClient, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = await request_json(client, "GET", f"{self._base_url}/search", provider=PROVIDER_NAME,
                                  params={**params, "per_page": MAX_CANDIDATES})
        return (data or {}).get("results") or []

    async def _company(self, client: httpx.AsyncClient, query: str, include: list[str]) -> dict[str, Any]:
        results = await self._search(client, {"q": query.strip()})
        match = pick_company(query, results)
        warnings: list[str] = []
        if "owners" in include:
            warnings.append("Shareholders are not published in France; directors are shown instead.")
        if "holdings" in include:
            warnings.append("The French directory does not list which companies a company holds shares in.")
        officers = normalize_officers(match)
        return ownership_record(
            subject=company_from_result(match),
            provider=PROVIDER_NAME,
            officers=officers,
            warnings=warnings,
            limitation=LIMITATION,
        )

    async def _person(self, client: httpx.AsyncClient, query: str, include: list[str]) -> dict[str, Any]:
        first, last = split_name(query)
        results = await self._search(client, {"nom_personne": last, "prenoms_personne": first})
        if not results and first:
            # Names are often written "LASTNAME First"; retry with the first word as last name.
            parts = query.split()
            last = parts[0]
            results = await self._search(client, {"nom_personne": last, "prenoms_personne": " ".join(parts[1:])})
        if not results:
            raise RegisterProviderError("not_found", f"No French company lists '{query}' as a director")
        warnings: list[str] = []
        if "owners" in include or "holdings" in include:
            warnings.append("Shareholdings are not published in France; director positions are shown instead.")
        rows = person_positions(last, results)
        return ownership_record(
            subject=person_subject(name=query.strip(), country="FR"),
            provider=PROVIDER_NAME,
            holdings=rows,
            warnings=warnings,
            limitation=LIMITATION,
        )


def split_name(query: str) -> tuple[str, str]:
    """Split "First Middle Last" into (first names, last name)."""
    parts = query.strip().split()
    if len(parts) < 2:
        return "", query.strip()
    return " ".join(parts[:-1]), parts[-1]


def company_from_result(result: dict[str, Any]) -> dict[str, Any]:
    siren = str(result.get("siren") or "")
    code = str(result.get("nature_juridique") or "")
    return company_subject(
        name=str(result.get("nom_complet") or result.get("nom_raison_sociale") or ""),
        country="FR",
        register_id=f"SIREN {siren}" if siren else None,
        legal_form=LEGAL_FORMS.get(code, code or None),
        status="active" if result.get("etat_administratif") == "A" else "closed",
        city=((result.get("siege") or {}).get("libelle_commune")),
        source_url=f"{PUBLIC_URL}/{siren}" if siren else None,
    )


def pick_company(query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick by SIREN or exact name; otherwise ambiguous with candidates."""
    if not results:
        raise RegisterProviderError("not_found", f"No French company matches '{query}'")
    needle = query.strip().casefold().replace(" ", "") if SIREN_RE.fullmatch(query.strip().replace(" ", "")) else query.strip().casefold()
    exact = [r for r in results if str(r.get("siren") or "") == needle
             or str(r.get("nom_complet") or "").casefold() == needle
             or str(r.get("nom_raison_sociale") or "").casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(results) == 1:
        return results[0]
    candidates = []
    for r in (exact or results)[:MAX_CANDIDATES]:
        subject = company_from_result(r)
        candidates.append({key: subject[key] for key in ("name", "register_id", "city", "status")})
    raise RegisterProviderError("ambiguous", f"Several French companies match '{query}'", candidates=candidates)


def _person_name(entry: dict[str, Any]) -> str:
    first = str(entry.get("prenoms") or "").split()
    return " ".join([*(first[:1]), str(entry.get("nom") or "")]).strip().title()


def normalize_officers(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Directors with role only; birth month/year and nationality stay behind."""
    officers = []
    for entry in result.get("dirigeants") or []:
        if entry.get("type_dirigeant") == "personne morale":
            officers.append(officer(name=str(entry.get("denomination") or ""), role=entry.get("qualite"),
                                    officer_type="company"))
        else:
            officers.append(officer(name=_person_name(entry), role=entry.get("qualite")))
    return officers


def person_positions(last: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Companies where a director with the given last name holds a position."""
    rows = []
    for result in results:
        subject = company_from_result(result)
        for entry in result.get("dirigeants") or []:
            if str(entry.get("nom") or "").casefold() != last.casefold():
                continue
            rows.append(holding(
                name=subject["name"],
                country="FR",
                register_id=subject["register_id"],
                relation=entry.get("qualite"),
                status=subject["status"],
                source_url=subject["source_url"],
            ))
            break
    return rows
