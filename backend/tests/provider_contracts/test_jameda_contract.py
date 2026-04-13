# backend/tests/provider_contracts/test_jameda_contract.py
#
# Daily contract probe for Jameda (DocPlanner) — Algolia full-text index,
# v3 anonymous token endpoint, doctor addresses, and doctor slots.
#
# What this catches:
#   * Algolia index rename / public key rotation
#   * /token endpoint returning a non-bearer token shape
#   * addresses[] losing has_slots / calendar_active fields
#   * /slots endpoint no longer accepting the start/end ISO window
#   * doctor objectID format flip (currently "doctor-12345")

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

JAMEDA_BASE_URL = "https://www.jameda.de"
ALGOLIA_URL = "https://docplanner-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_APP_ID = "docplanner"
ALGOLIA_PUBLIC_KEY = "189da7b805744e97ef09dea8dbe7e35f"
ALGOLIA_INDEX = "de_autocomplete_doctor"

PROBE_SPECIALITY = "zahnarzt"
PROBE_CITY = "berlin"


@pytest.mark.provider_contract
async def test_jameda_algolia_search_returns_calendar_hits(
    browser_headers: dict[str, str],
) -> None:
    """Algolia index must still exist, still accept the public key, and at
    least a handful of Berlin dentists must have calendar=True."""
    async with httpx.AsyncClient(timeout=30.0, headers=browser_headers) as client:
        resp = await client.post(
            ALGOLIA_URL,
            json={
                "requests": [
                    {
                        "indexName": ALGOLIA_INDEX,
                        "params": (
                            f"query={PROBE_SPECIALITY} {PROBE_CITY}"
                            "&hitsPerPage=10"
                            "&attributesToRetrieve=objectID,fullname_formatted,"
                            "specializations,cities,calendar,stars,opinionCount"
                        ),
                    }
                ],
            },
            headers={
                "x-algolia-api-key": ALGOLIA_PUBLIC_KEY,
                "x-algolia-application-id": ALGOLIA_APP_ID,
                "Content-Type": "application/json",
                "Referer": f"{JAMEDA_BASE_URL}/",
                "Origin": JAMEDA_BASE_URL,
            },
        )
        assert resp.status_code == 200, f"Algolia HTTP {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        hits = (data.get("results") or [{}])[0].get("hits") or []
        assert hits, "Algolia returned zero hits for zahnarzt berlin"
        with_calendar = [h for h in hits if h.get("calendar")]
        assert with_calendar, "No Berlin dentist in the top 10 has calendar=True"
        first = with_calendar[0]
        assert first.get("objectID", "").startswith("doctor-"), (
            f"objectID prefix changed: {first.get('objectID')}"
        )
        assert first.get("fullname_formatted"), "fullname_formatted missing"


@pytest.mark.provider_contract
async def test_jameda_anonymous_token_and_addresses(
    browser_headers: dict[str, str],
) -> None:
    """GET /token must return access_token, and
    /api/v3/doctors/{id}/addresses must return at least one address
    with has_slots=True."""
    async with httpx.AsyncClient(timeout=30.0, headers=browser_headers) as client:
        # Find a doctor via Algolia first.
        algo = await client.post(
            ALGOLIA_URL,
            json={
                "requests": [
                    {
                        "indexName": ALGOLIA_INDEX,
                        "params": (
                            f"query={PROBE_SPECIALITY} {PROBE_CITY}"
                            "&hitsPerPage=5"
                            "&attributesToRetrieve=objectID,calendar"
                        ),
                    }
                ],
            },
            headers={
                "x-algolia-api-key": ALGOLIA_PUBLIC_KEY,
                "x-algolia-application-id": ALGOLIA_APP_ID,
                "Content-Type": "application/json",
                "Referer": f"{JAMEDA_BASE_URL}/",
            },
        )
        hits = (algo.json().get("results") or [{}])[0].get("hits") or []
        doctor_ids = [
            h["objectID"].removeprefix("doctor-")
            for h in hits
            if h.get("calendar") and str(h.get("objectID", "")).startswith("doctor-")
        ]
        assert doctor_ids, "No calendar-enabled doctor_ids from Algolia"

        token_resp = await client.get(
            f"{JAMEDA_BASE_URL}/token", headers={"Accept": "application/json"}
        )
        assert token_resp.status_code == 200, f"/token HTTP {token_resp.status_code}"
        token_body = token_resp.json()
        access_token = token_body.get("access_token")
        assert access_token, f"/token response missing access_token: {token_body}"

        api_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            **browser_headers,
            "Referer": f"{JAMEDA_BASE_URL}/",
        }

        found_bookable = False
        last_error: str | None = None
        for doctor_id in doctor_ids[:5]:
            addr_resp = await client.get(
                f"{JAMEDA_BASE_URL}/api/v3/doctors/{doctor_id}/addresses",
                headers=api_headers,
            )
            if addr_resp.status_code != 200:
                last_error = f"addresses HTTP {addr_resp.status_code}"
                continue
            addresses = addr_resp.json().get("_items") or []
            bookable = [
                a
                for a in addresses
                if a.get("has_slots") and a.get("calendar_active", True)
            ]
            if not bookable:
                continue
            address_id = bookable[0].get("id")
            assert address_id, "address.id missing"
            start = date.today()
            end = start + timedelta(days=7)
            slots_resp = await client.get(
                f"{JAMEDA_BASE_URL}/api/v3/doctors/{doctor_id}"
                f"/addresses/{address_id}/slots"
                f"?start={start.isoformat()}T00:00:00%2B01:00"
                f"&end={end.isoformat()}T23:59:59%2B01:00",
                headers=api_headers,
            )
            if slots_resp.status_code != 200:
                last_error = f"slots HTTP {slots_resp.status_code}"
                continue
            slots = slots_resp.json().get("_items") or []
            if slots:
                first = slots[0]
                assert first.get("start"), f"slot.start missing: {first}"
                found_bookable = True
                break

        assert found_bookable, (
            f"No Berlin dentist returned bookable slots. Last error: {last_error}"
        )
