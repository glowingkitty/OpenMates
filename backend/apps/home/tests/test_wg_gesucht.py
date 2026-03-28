"""
WG-Gesucht API Test Script
=============================
Tests the undocumented WG-Gesucht REST API discovered via reverse engineering.

Approach:
  1. Fetch sitemap (offer_details_DE.xml.gz) → extract listing IDs by city
  2. Call /api/offers/{id} for each → rich HAL+JSON detail (100+ fields)

Both steps work from plain httpx — no browser, no auth, no Cloudflare issues.

Usage:
  python3 backend/apps/home/tests/test_wg_gesucht.py
"""

import asyncio
import gzip
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# --- Constants ---

BASE_URL = "https://www.wg-gesucht.de"
SITEMAP_URL = f"{BASE_URL}/sitemaps/offer_detail_views/offer_details_DE.xml.gz"
DETAIL_API_URL = f"{BASE_URL}/api/offers"

# City patterns in sitemap URLs: "in-Berlin", "in-Muenchen", etc.
CITY_PATTERNS = {
    "berlin": "in-Berlin",
    "munich": "in-Muenchen",
    "hamburg": "in-Hamburg",
    "cologne": "in-Koeln",
    "frankfurt": "in-Frankfurt",
}

# WG-Gesucht categories
CATEGORIES = {
    "0": "wg_room",       # WG-Zimmer
    "1": "1_room_flat",   # 1-Zimmer-Wohnung
    "2": "apartment",     # Wohnung
    "3": "house",         # Haus
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.5",
}


@dataclass
class Listing:
    """Normalized listing extracted from WG-Gesucht API."""
    id: str
    title: str
    price_cold: Optional[str] = None
    price_warm: Optional[str] = None
    utility_costs: Optional[str] = None
    deposit: Optional[str] = None
    size_sqm: Optional[str] = None
    rooms: Optional[str] = None
    address: str = ""
    postcode: Optional[str] = None
    district: Optional[str] = None
    available_from: Optional[str] = None
    available_to: Optional[str] = None
    category: Optional[str] = None
    furnished: bool = False
    balcony: bool = False
    elevator: bool = False
    floor: Optional[str] = None
    link: str = ""


@dataclass
class TestResult:
    name: str
    passed: bool
    details: str = ""
    listings: list = field(default_factory=list)
    response_time_ms: float = 0
    count: int = 0


def parse_api_listing(data: dict) -> Listing:
    """Parse a WG-Gesucht API response into a normalized Listing."""
    offer_id = data.get("offer_id", "")
    category = data.get("category", "")
    data.get("city_id", "")

    # Build link from category and ID
    category_slugs = {"0": "wg-zimmer", "1": "1-zimmer-wohnungen", "2": "wohnungen", "3": "haeuser"}
    slug = category_slugs.get(category, "wg-zimmer")
    district = data.get("district_custom", "").replace(" ", "-").replace("/", "-")
    link = f"{BASE_URL}/{slug}-in-{district}.{offer_id}.html" if district else f"{BASE_URL}/{offer_id}.html"

    return Listing(
        id=offer_id,
        title=data.get("offer_title", ""),
        price_cold=data.get("rent_costs"),
        price_warm=data.get("total_costs"),
        utility_costs=data.get("utility_costs"),
        deposit=data.get("bond_costs"),
        size_sqm=data.get("property_size"),
        rooms=data.get("number_of_rooms"),
        address=f"{data.get('street', '')}, {data.get('postcode', '')}",
        postcode=data.get("postcode"),
        district=data.get("district_custom"),
        available_from=data.get("available_from_date"),
        available_to=data.get("available_to_date"),
        category=CATEGORIES.get(category, category),
        furnished=data.get("furnished") == "1",
        balcony=data.get("balcony") == "1",
        elevator=data.get("elevator") == "1",
        floor=data.get("floor_level"),
        link=link,
    )


async def test_sitemap_fetch(client: httpx.AsyncClient, city: str = "berlin") -> TestResult:
    """Test 1: Fetch sitemap and extract listing IDs for a city."""
    name = f"sitemap_fetch({city})"
    pattern = CITY_PATTERNS.get(city, f"in-{city.title()}")

    start = time.monotonic()
    try:
        resp = await client.get(SITEMAP_URL)
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            return TestResult(name=name, passed=False, details=f"HTTP {resp.status_code}", response_time_ms=elapsed)

        content = gzip.decompress(resp.content).decode("utf-8")

        # Extract all listing URLs for the target city
        url_pattern = re.compile(
            rf'<loc>(https://www\.wg-gesucht\.de/[^<]*{re.escape(pattern)}[^<]*\.(\d+)\.html)</loc>'
        )
        matches = url_pattern.findall(content)

        # Deduplicate IDs (same ID may appear with different lastmod entries)
        ids = list(dict.fromkeys([m[1] for m in matches]))

        # Count total DE listings
        all_ids = re.findall(r'<loc>https://www\.wg-gesucht\.de/[^<]*\.(\d+)\.html</loc>', content)
        total_de = len(set(all_ids))

        return TestResult(
            name=name, passed=len(ids) > 0,
            details=f"Sitemap: {len(resp.content)} bytes compressed, {len(content)} decompressed. "
                    f"Total DE: {total_de}, {city.title()}: {len(ids)} listings",
            count=len(ids),
            response_time_ms=elapsed,
        )
    except Exception as e:
        return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_detail_api(client: httpx.AsyncClient, offer_id: str) -> TestResult:
    """Test 2: Fetch a single listing detail via API."""
    name = f"detail_api({offer_id})"
    start = time.monotonic()
    try:
        resp = await client.get(f"{DETAIL_API_URL}/{offer_id}")
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            listing = parse_api_listing(data)
            field_count = sum(1 for v in data.values() if v is not None and v != "" and v != "0")
            return TestResult(
                name=name, passed=True,
                details=f"Fields populated: {field_count}/{len(data)}",
                listings=[listing],
                response_time_ms=elapsed,
            )
        else:
            return TestResult(
                name=name, passed=False,
                details=f"HTTP {resp.status_code}: {resp.text[:200]}",
                response_time_ms=elapsed,
            )
    except Exception as e:
        return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_full_pipeline(client: httpx.AsyncClient, city: str = "berlin", sample_size: int = 5) -> TestResult:
    """Test 3: Full pipeline — sitemap → IDs → detail API for N listings."""
    name = f"full_pipeline({city}, n={sample_size})"
    start = time.monotonic()

    try:
        # Step 1: Get IDs from sitemap
        resp = await client.get(SITEMAP_URL)
        content = gzip.decompress(resp.content).decode("utf-8")
        pattern = CITY_PATTERNS.get(city, f"in-{city.title()}")
        url_pattern = re.compile(
            rf'<loc>https://www\.wg-gesucht\.de/[^<]*{re.escape(pattern)}[^<]*\.(\d+)\.html</loc>'
        )
        ids = list(dict.fromkeys(url_pattern.findall(content)))

        # Step 2: Fetch details for sample
        listings = []
        errors = 0
        for offer_id in ids[:sample_size]:
            detail_resp = await client.get(f"{DETAIL_API_URL}/{offer_id}")
            if detail_resp.status_code == 200:
                listings.append(parse_api_listing(detail_resp.json()))
            else:
                errors += 1

        elapsed = (time.monotonic() - start) * 1000

        return TestResult(
            name=name, passed=len(listings) > 0,
            details=f"IDs found: {len(ids)}, Fetched: {len(listings)}/{sample_size}, Errors: {errors}",
            listings=listings,
            response_time_ms=elapsed,
        )
    except Exception as e:
        return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_rate_limiting(client: httpx.AsyncClient, num_requests: int = 10) -> TestResult:
    """Test 4: Rapid detail API requests to detect rate limiting."""
    name = f"rate_limiting({num_requests}_requests)"

    # Use a known valid ID
    offer_id = "11359346"
    results = []
    start_all = time.monotonic()

    for i in range(num_requests):
        start = time.monotonic()
        try:
            resp = await client.get(f"{DETAIL_API_URL}/{offer_id}")
            elapsed_ms = (time.monotonic() - start) * 1000
            results.append((resp.status_code, elapsed_ms))
        except Exception:
            results.append((0, 0))

    total_time = (time.monotonic() - start_all) * 1000
    status_codes = [r[0] for r in results]
    avg_time = sum(r[1] for r in results) / len(results) if results else 0
    blocked = sum(1 for code in status_codes if code in (403, 429))

    return TestResult(
        name=name,
        passed=blocked == 0,
        details=f"Total: {total_time:.0f}ms, Avg: {avg_time:.0f}ms/req, "
                f"Status codes: {status_codes}, Blocked: {blocked}/{num_requests}",
        response_time_ms=total_time,
    )


def print_result(result: TestResult) -> None:
    """Pretty-print a test result."""
    icon = "PASS" if result.passed else "FAIL"
    print(f"\n[{icon}] {result.name}")
    print(f"  {result.details}")
    if result.response_time_ms:
        print(f"  Response time: {result.response_time_ms:.0f}ms")

    for listing in result.listings[:3]:
        print("  ---")
        print(f"  ID:        {listing.id}")
        print(f"  Title:     {listing.title}")
        print(f"  Kalt:      {listing.price_cold}€")
        print(f"  Warm:      {listing.price_warm}€")
        print(f"  Size:      {listing.size_sqm}m²")
        print(f"  Address:   {listing.address}")
        print(f"  District:  {listing.district}")
        print(f"  Available: {listing.available_from}")
        print(f"  Category:  {listing.category}")
        print(f"  Furnished: {listing.furnished}, Balcony: {listing.balcony}")
        print(f"  Link:      {listing.link}")


async def main() -> None:
    print("=" * 70)
    print("WG-Gesucht API Test (Sitemap + Detail API)")
    print("=" * 70)

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:

        # Test 1: Sitemap fetch and ID extraction
        result = await test_sitemap_fetch(client, "berlin")
        print_result(result)

        # Test 2: Single listing detail
        result = await test_detail_api(client, "11359346")
        print_result(result)

        # Test 3: Full pipeline (sitemap → API for 5 listings)
        result = await test_full_pipeline(client, "berlin", sample_size=5)
        print_result(result)

        # Test 4: Rate limiting
        result = await test_rate_limiting(client, num_requests=10)
        print_result(result)

    print("\n" + "=" * 70)
    print("Test complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
