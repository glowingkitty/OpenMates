"""
ImmoScout24 Mobile API Test Script
===================================
Tests the reverse-engineered ImmoScout24 mobile API (discovered by Fredy project).
This API requires no authentication — only a specific User-Agent header.

Endpoints:
  - GET  /search/total?{params}  — result count
  - POST /search/list?{params}   — listing search
  - GET  /expose/{id}            — listing detail

Usage:
  python3 backend/apps/home/tests/test_immoscout24.py
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# --- Constants ---

BASE_URL = "https://api.mobile.immobilienscout24.de"
USER_AGENT = "ImmoScout_27.12_26.2_._"

# Real estate type mapping (from Fredy's immoscout-web-translator.js)
REAL_ESTATE_TYPES = {
    "apartment_rent": "apartmentrent",
    "apartment_buy": "apartmentbuy",
    "house_rent": "houserent",
    "house_buy": "housebuy",
}

# Geocode mapping for major German cities
GEOCODES = {
    "berlin": "/de/berlin/berlin",
    "munich": "/de/bayern/muenchen",
    "hamburg": "/de/hamburg/hamburg",
    "cologne": "/de/nordrhein-westfalen/koeln",
    "frankfurt": "/de/hessen/frankfurt-am-main",
    "duesseldorf": "/de/nordrhein-westfalen/duesseldorf",
}


@dataclass
class Listing:
    """Normalized listing extracted from ImmoScout24 mobile API response."""
    id: str
    title: str
    price: Optional[str] = None
    size: Optional[str] = None
    address: Optional[str] = None
    image_url: Optional[str] = None
    link: str = ""


@dataclass
class TestResult:
    """Result of a single test case."""
    name: str
    passed: bool
    details: str = ""
    listings: list = field(default_factory=list)
    response_time_ms: float = 0
    status_code: int = 0


def parse_listings(response_json: dict) -> list[Listing]:
    """Parse listings from ImmoScout24 mobile API response."""
    listings = []
    items = response_json.get("resultListItems", [])

    for item_wrapper in items:
        if item_wrapper.get("type") != "EXPOSE_RESULT":
            continue

        item = item_wrapper.get("item", {})
        item_id = str(item.get("id", ""))
        attributes = item.get("attributes", [])

        # First attribute is typically price, second is size
        price = attributes[0].get("value") if len(attributes) > 0 else None
        size = attributes[1].get("value") if len(attributes) > 1 else None

        # Image: titlePicture.full or titlePicture.preview
        title_pic = item.get("titlePicture", {})
        image_url = title_pic.get("full") or title_pic.get("preview")

        address_obj = item.get("address", {})
        address = address_obj.get("line") if address_obj else None

        listings.append(Listing(
            id=item_id,
            title=item.get("title", ""),
            price=price,
            size=size,
            address=address,
            image_url=image_url,
            link=f"https://www.immobilienscout24.de/expose/{item_id}",
        ))

    return listings


async def test_search_total(client: httpx.AsyncClient, realestatetype: str, geocodes: str) -> TestResult:
    """Test 1: GET /search/total — check result count endpoint."""
    name = f"search_total({realestatetype}, {geocodes})"
    params = {
        "searchType": "region",
        "realestatetype": realestatetype,
        "geocodes": geocodes,
    }
    start = time.monotonic()
    try:
        resp = await client.get(f"{BASE_URL}/search/total", params=params)
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", data.get("count", "unknown"))
            return TestResult(
                name=name, passed=True,
                details=f"Total results: {total}",
                response_time_ms=elapsed, status_code=resp.status_code,
            )
        else:
            return TestResult(
                name=name, passed=False,
                details=f"HTTP {resp.status_code}: {resp.text[:200]}",
                response_time_ms=elapsed, status_code=resp.status_code,
            )
    except Exception as e:
        return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_search_list(client: httpx.AsyncClient, realestatetype: str, geocodes: str) -> TestResult:
    """Test 2: POST /search/list — fetch actual listings."""
    name = f"search_list({realestatetype}, {geocodes})"
    params = {
        "searchType": "region",
        "realestatetype": realestatetype,
        "geocodes": geocodes,
    }
    body = {
        "supportedResultListTypes": [],
        "userData": {},
    }
    start = time.monotonic()
    try:
        resp = await client.post(f"{BASE_URL}/search/list", params=params, json=body)
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            listings = parse_listings(data)
            return TestResult(
                name=name, passed=len(listings) > 0,
                details=f"Found {len(listings)} listings",
                listings=listings,
                response_time_ms=elapsed, status_code=resp.status_code,
            )
        else:
            return TestResult(
                name=name, passed=False,
                details=f"HTTP {resp.status_code}: {resp.text[:500]}",
                response_time_ms=elapsed, status_code=resp.status_code,
            )
    except Exception as e:
        return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_expose_detail(client: httpx.AsyncClient, expose_id: str) -> TestResult:
    """Test 3: GET /expose/{id} — fetch listing detail."""
    name = f"expose_detail({expose_id})"
    start = time.monotonic()
    try:
        resp = await client.get(f"{BASE_URL}/expose/{expose_id}")
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            # Extract key detail fields
            fields_found = list(data.keys())[:10]
            return TestResult(
                name=name, passed=True,
                details=f"Detail fields: {fields_found}",
                response_time_ms=elapsed, status_code=resp.status_code,
            )
        else:
            return TestResult(
                name=name, passed=False,
                details=f"HTTP {resp.status_code}: {resp.text[:500]}",
                response_time_ms=elapsed, status_code=resp.status_code,
            )
    except Exception as e:
        return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_without_user_agent() -> TestResult:
    """Test 4: Request without the mobile User-Agent — expect failure or different behavior."""
    name = "without_user_agent"
    async with httpx.AsyncClient(timeout=15) as client:
        params = {
            "searchType": "region",
            "realestatetype": "apartmentrent",
            "geocodes": "/de/berlin/berlin",
        }
        body = {"supportedResultListTypes": [], "userData": {}}
        start = time.monotonic()
        try:
            resp = await client.post(f"{BASE_URL}/search/list", params=params, json=body)
            elapsed = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                data = resp.json()
                listings = parse_listings(data)
                return TestResult(
                    name=name, passed=True,
                    details=f"API works WITHOUT User-Agent too! ({len(listings)} listings, HTTP {resp.status_code})",
                    response_time_ms=elapsed, status_code=resp.status_code,
                )
            else:
                return TestResult(
                    name=name, passed=True,
                    details=f"Correctly rejected without User-Agent: HTTP {resp.status_code}",
                    response_time_ms=elapsed, status_code=resp.status_code,
                )
        except Exception as e:
            return TestResult(name=name, passed=True, details=f"Rejected without User-Agent: {e}")


async def test_rate_limiting(client: httpx.AsyncClient, num_requests: int = 10) -> TestResult:
    """Test 5: Rapid sequential requests to detect rate limiting."""
    name = f"rate_limiting({num_requests}_requests)"
    params = {
        "searchType": "region",
        "realestatetype": "apartmentrent",
        "geocodes": "/de/berlin/berlin",
    }
    body = {"supportedResultListTypes": [], "userData": {}}

    results = []
    start_all = time.monotonic()

    for i in range(num_requests):
        start = time.monotonic()
        try:
            resp = await client.post(f"{BASE_URL}/search/list", params=params, json=body)
            elapsed = (time.monotonic() - start) * 1000
            results.append((resp.status_code, elapsed))
        except Exception:
            results.append((0, 0))

    total_time = (time.monotonic() - start_all) * 1000

    status_codes = [r[0] for r in results]
    avg_time = sum(r[1] for r in results) / len(results) if results else 0
    blocked = sum(1 for code in status_codes if code in (403, 429))

    return TestResult(
        name=name,
        passed=blocked == 0,
        details=(
            f"Total: {total_time:.0f}ms, Avg: {avg_time:.0f}ms/req, "
            f"Status codes: {status_codes}, Blocked: {blocked}/{num_requests}"
        ),
        response_time_ms=total_time,
    )


def print_result(result: TestResult) -> None:
    """Pretty-print a test result."""
    icon = "PASS" if result.passed else "FAIL"
    print(f"\n[{icon}] {result.name}")
    print(f"  {result.details}")
    if result.response_time_ms:
        print(f"  Response time: {result.response_time_ms:.0f}ms")

    # Print first 3 listings as sample
    for listing in result.listings[:3]:
        print("  ---")
        print(f"  ID:      {listing.id}")
        print(f"  Title:   {listing.title}")
        print(f"  Price:   {listing.price}")
        print(f"  Size:    {listing.size}")
        print(f"  Address: {listing.address}")
        print(f"  Image:   {listing.image_url}")
        print(f"  Link:    {listing.link}")


async def main() -> None:
    print("=" * 70)
    print("ImmoScout24 Mobile API Test")
    print("=" * 70)

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers, timeout=15) as client:

        # Test 1: Search total — apartments for rent in Berlin
        result = await test_search_total(
            client, REAL_ESTATE_TYPES["apartment_rent"], GEOCODES["berlin"]
        )
        print_result(result)

        # Test 2a: Search list — apartments for rent in Berlin
        result_berlin = await test_search_list(
            client, REAL_ESTATE_TYPES["apartment_rent"], GEOCODES["berlin"]
        )
        print_result(result_berlin)

        # Test 2b: Search list — houses for sale in Munich
        result_munich = await test_search_list(
            client, REAL_ESTATE_TYPES["house_buy"], GEOCODES["munich"]
        )
        print_result(result_munich)

        # Test 3: Expose detail — use first listing ID from Berlin search
        if result_berlin.listings:
            first_id = result_berlin.listings[0].id
            result_detail = await test_expose_detail(client, first_id)
            print_result(result_detail)
        else:
            print("\n[SKIP] expose_detail — no listings from search to test with")

    # Test 4: Without User-Agent
    result_no_ua = await test_without_user_agent()
    print_result(result_no_ua)

    # Test 5: Rate limiting (use client with User-Agent)
    async with httpx.AsyncClient(headers=headers, timeout=15) as client:
        result_rate = await test_rate_limiting(client, num_requests=10)
        print_result(result_rate)

    print("\n" + "=" * 70)
    print("Test complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
