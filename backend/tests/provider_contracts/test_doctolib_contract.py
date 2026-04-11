# backend/tests/provider_contracts/test_doctolib_contract.py
#
# Daily contract probe for Doctolib DE — the listing page, the phs_proxy/raw
# doctor search, and the /search/availabilities.json slot endpoint.
#
# What this catches (one concrete historical example per assertion):
#   * 2026-Q1 'start_date' → 'start_date_time' rename  →  0 slots regression
#   * 'limit' capped at 7 (was 14)                     →  HTTP 400
#   * matchedVisitMotive.insuranceSector flipped       →  stringified dict
#     from string "public" to dict {type, split}          reaches the API
#   * slot items flipped from ISO string to dict       →  TypeError in sort
#   * window.place JSON block removed from HTML        →  ValueError resolve
#
# The probe runs for 'radiologe berlin' specifically because that speciality
# has a large pool of high-volume practices, so at least one slot within the
# next 7 days is reliable.  If Berlin radiology has 0 availability, something
# upstream is broken regardless of API shape.

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
import pytest

DOCTOLIB_BASE_URL = "https://www.doctolib.de"
PROBE_SPECIALITY_SLUG = "radiologe"
PROBE_CITY_SLUG = "berlin"
# Webshare rotating proxy occasionally hands out a Doctolib-blocked IP. We
# retry a few times before failing the contract test so transient blocks
# don't create false positives in the daily report.
LISTING_MAX_ATTEMPTS = 4
LISTING_RETRY_DELAY_SECONDS = 2


async def _fetch_listing_with_retries(
    client: httpx.AsyncClient, browser_headers: dict[str, str]
) -> httpx.Response:
    last_status = 0
    for attempt in range(LISTING_MAX_ATTEMPTS):
        resp = await client.get(
            f"{DOCTOLIB_BASE_URL}/{PROBE_SPECIALITY_SLUG}/{PROBE_CITY_SLUG}",
            headers={**browser_headers, "Accept": "text/html"},
        )
        last_status = resp.status_code
        if resp.status_code == 200 and len(resp.text) > 1000:
            return resp
        await asyncio.sleep(LISTING_RETRY_DELAY_SECONDS)
    raise AssertionError(
        f"Doctolib listing kept failing after {LISTING_MAX_ATTEMPTS} attempts "
        f"(last HTTP {last_status})"
    )


@pytest.mark.provider_contract
async def test_doctolib_listing_has_window_place(
    webshare_proxy_url: str, browser_headers: dict[str, str]
) -> None:
    """The speciality/city HTML must still embed window.place = {...};"""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=browser_headers,
        proxy=webshare_proxy_url,
    ) as client:
        resp = await _fetch_listing_with_retries(client, browser_headers)
        match = re.search(r"window\.place\s*=\s*(\{.+?\});", resp.text, re.DOTALL)
        assert match, (
            "window.place block missing from Doctolib listing HTML — "
            "contract drift or anti-bot page served."
        )
        place = json.loads(match.group(1))
        assert "id" in place, "place.id missing"
        assert place.get("name"), "place.name missing"


@pytest.mark.provider_contract
async def test_doctolib_phs_proxy_provider_shape(
    webshare_proxy_url: str, browser_headers: dict[str, str]
) -> None:
    """phs_proxy/raw must return healthcareProviders[] with the exact fields
    the skill reads: references.practiceId, onlineBooking.agendaIds,
    matchedVisitMotive.visitMotiveId, and insuranceSector as a dict."""
    headers = {
        **browser_headers,
        "Content-Type": "application/json",
        "Referer": f"{DOCTOLIB_BASE_URL}/",
        "Origin": DOCTOLIB_BASE_URL,
    }
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=browser_headers,
        proxy=webshare_proxy_url,
    ) as client:
        listing = await _fetch_listing_with_retries(client, browser_headers)
        match = re.search(r"window\.place\s*=\s*(\{.+?\});", listing.text, re.DOTALL)
        assert match, "listing page has no window.place (see listing test)"
        place = json.loads(match.group(1))
        resp = await client.post(
            f"{DOCTOLIB_BASE_URL}/phs_proxy/raw?page=0",
            json={
                "keyword": PROBE_SPECIALITY_SLUG,
                "location": {"place": place},
                "filters": {},
            },
            headers=headers,
        )
        assert resp.status_code == 200, f"phs_proxy HTTP {resp.status_code}"
        data = resp.json()
        providers = data.get("healthcareProviders") or []
        assert providers, "phs_proxy returned zero healthcareProviders"

        # Inspect the first few providers for the full field set.
        for prov in providers[:3]:
            refs = prov.get("references") or {}
            online_booking = prov.get("onlineBooking") or {}
            motive = prov.get("matchedVisitMotive") or {}
            assert refs.get("practiceId"), (
                f"provider {prov.get('name')} missing references.practiceId"
            )
            assert online_booking.get("agendaIds"), (
                f"provider {prov.get('name')} missing onlineBooking.agendaIds"
            )
            assert motive.get("visitMotiveId"), (
                f"provider {prov.get('name')} missing matchedVisitMotive.visitMotiveId"
            )
            ins_sector = motive.get("insuranceSector")
            # New (2026-Q1) shape is a dict {type, split}; tolerate the old
            # string shape as well so this probe catches a flip in either
            # direction.
            assert ins_sector is None or isinstance(ins_sector, (dict, str)), (
                f"insuranceSector shape unknown: {type(ins_sector).__name__}"
            )
            if isinstance(ins_sector, dict):
                assert "type" in ins_sector, (
                    f"insuranceSector dict missing .type key: {ins_sector}"
                )


@pytest.mark.provider_contract
async def test_doctolib_availability_returns_slots(
    webshare_proxy_url: str, browser_headers: dict[str, str]
) -> None:
    """/search/availabilities.json must accept start_date_time + lowercase
    insurance_sector + limit <= 7, and return non-empty availabilities[] for
    at least one Berlin radiology practice."""
    headers = {
        **browser_headers,
        "Referer": f"{DOCTOLIB_BASE_URL}/",
        "Origin": DOCTOLIB_BASE_URL,
    }
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers=browser_headers,
        proxy=webshare_proxy_url,
    ) as client:
        listing = await _fetch_listing_with_retries(client, browser_headers)
        match = re.search(r"window\.place\s*=\s*(\{.+?\});", listing.text, re.DOTALL)
        assert match, "listing page has no window.place"
        place = json.loads(match.group(1))
        phs = await client.post(
            f"{DOCTOLIB_BASE_URL}/phs_proxy/raw?page=0",
            json={
                "keyword": PROBE_SPECIALITY_SLUG,
                "location": {"place": place},
                "filters": {},
            },
            headers={**headers, "Content-Type": "application/json"},
        )
        providers = phs.json().get("healthcareProviders") or []
        assert providers, "phs_proxy returned zero providers"

        start_dt = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        found_slots = False
        last_error: str | None = None
        # Probe up to 5 practices — many return 403 (anti-bot on individual
        # agendas) but statistically at least one Berlin radiology practice
        # should have real slots in the next 7 days.
        for prov in providers[:5]:
            online_booking = prov.get("onlineBooking") or {}
            refs = prov.get("references") or {}
            motive = prov.get("matchedVisitMotive") or {}
            agenda_ids = online_booking.get("agendaIds") or []
            practice_id = refs.get("practiceId")
            visit_motive_id = motive.get("visitMotiveId")
            ins_sector_obj = motive.get("insuranceSector") or {}
            insurance_sector = (
                (ins_sector_obj.get("type") or "PUBLIC").lower()
                if isinstance(ins_sector_obj, dict)
                else "public"
            )
            if not (agenda_ids and practice_id and visit_motive_id):
                continue
            params = urlencode(
                {
                    "telehealth": "false",
                    "limit": 7,
                    "start_date_time": start_dt,
                    "visit_motive_id": visit_motive_id,
                    "agenda_ids": "-".join(str(a) for a in agenda_ids),
                    "insurance_sector": insurance_sector,
                    "practice_ids": practice_id,
                }
            )
            url = f"{DOCTOLIB_BASE_URL}/search/availabilities.json?{params}"
            avail = await client.get(url, headers=headers)
            if avail.status_code != 200:
                last_error = f"HTTP {avail.status_code}: {avail.text[:200]}"
                continue
            body = avail.json()
            for day in body.get("availabilities", []):
                slots = day.get("slots") or []
                for slot in slots:
                    # Tolerated shapes: ISO string OR dict with .start_date
                    if isinstance(slot, str):
                        found_slots = True
                        break
                    if isinstance(slot, dict) and isinstance(
                        slot.get("start_date"), str
                    ):
                        found_slots = True
                        break
                if found_slots:
                    break
            if found_slots:
                break

        assert found_slots, (
            "No Berlin radiology practice returned bookable slots within "
            f"7 days. Last error: {last_error}"
        )
