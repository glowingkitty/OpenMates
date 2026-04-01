"""
Immowelt Scraper Test Script
==============================
Tests HTML scraping of Immowelt (Germany's #2 real estate platform).
Immowelt absorbed Immonet in Feb 2026 — both now operate under Immowelt brand.

Strategy:
  1. Try httpx first (check if listings are in SSR HTML)
  2. If JS-rendered, fall back to Playwright with stealth headers
  3. Check for bot detection (403/429, "verify you are human")

CSS selectors based on Fredy project (orangecoding/fredy).

Usage:
  python3 backend/apps/home/tests/test_immowelt.py
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# --- Constants ---

BASE_URL = "https://www.immowelt.de"

# Example search URLs
SEARCH_URLS = {
    "apartment_rent_berlin": f"{BASE_URL}/liste/berlin/wohnungen/mieten",
    "house_buy_munich": f"{BASE_URL}/liste/muenchen/haeuser/kaufen",
    "apartment_rent_hamburg": f"{BASE_URL}/liste/hamburg/wohnungen/mieten",
}

# CSS selectors from Fredy's immowelt.js adapter
SELECTORS = {
    "container": 'div[data-testid="serp-core-classified-card-testid"]',
    "wait_for": 'div[data-testid="serp-gridcontainer-testid"]',
    "price": 'div[data-testid="cardmfe-price-testid"]',
    "size": 'div[data-testid="cardmfe-keyfacts-testid"]',
    "title": 'div[data-testid="cardmfe-description-box-text-test-id"] > div:nth-of-type(2)',
    "address": 'div[data-testid="cardmfe-description-box-address"]',
    "image": 'div[data-testid="cardmfe-picture-box-opacity-layer-test-id"] img',
    "link": "a",
}

# Realistic browser headers
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class Listing:
    """Normalized listing extracted from Immowelt."""
    id: str
    title: str
    price: Optional[str] = None
    size: Optional[str] = None
    address: Optional[str] = None
    image_url: Optional[str] = None
    link: str = ""
    description: Optional[str] = None


@dataclass
class TestResult:
    name: str
    passed: bool
    details: str = ""
    listings: list = field(default_factory=list)
    response_time_ms: float = 0
    status_code: int = 0
    bot_detected: bool = False
    is_ssr: bool = False


BOT_PATTERNS = [
    re.compile(r"verify you are human", re.IGNORECASE),
    re.compile(r"access denied", re.IGNORECASE),
    re.compile(r"captcha", re.IGNORECASE),
    re.compile(r"x-amz-cf-id", re.IGNORECASE),
    re.compile(r"blocked", re.IGNORECASE),
]


def check_bot_detection(html: str, status_code: int) -> bool:
    """Check if the response indicates bot detection."""
    if status_code in (403, 429):
        return True
    return any(pattern.search(html) for pattern in BOT_PATTERNS)


def parse_listings_from_html(html: str) -> list[Listing]:
    """
    Attempt to parse listings from raw HTML using regex.
    This is a lightweight check — if data is SSR, we can extract without a browser.
    For full parsing, we'd use BeautifulSoup or Playwright.
    """
    listings = []

    # Check if the key data-testid selectors exist in HTML (indicates SSR)
    has_containers = 'data-testid="serp-core-classified-card-testid"' in html

    if not has_containers:
        return listings

    # Try to extract basic listing data via regex (rough but tells us if data is present)
    # Look for expose links which contain listing IDs
    link_pattern = re.compile(r'href="(/expose/[^"]+)"')
    links_found = link_pattern.findall(html)

    for i, link_path in enumerate(links_found[:20]):
        listing_id = link_path.split("/")[-1].split("?")[0]
        listings.append(Listing(
            id=listing_id,
            title=f"[SSR listing #{i+1}]",
            link=f"{BASE_URL}{link_path}",
        ))

    return listings


async def test_httpx_ssr(url: str, label: str) -> TestResult:
    """Test if Immowelt returns listing data in SSR HTML (no JS needed)."""
    name = f"httpx_ssr({label})"
    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=15, follow_redirects=True) as client:
        start = time.monotonic()
        try:
            resp = await client.get(url)
            elapsed = (time.monotonic() - start) * 1000
            html = resp.text

            bot = check_bot_detection(html, resp.status_code)
            if bot:
                return TestResult(
                    name=name, passed=False, bot_detected=True,
                    details=f"Bot detected! HTTP {resp.status_code}, HTML length: {len(html)}",
                    response_time_ms=elapsed, status_code=resp.status_code,
                )

            listings = parse_listings_from_html(html)
            has_data_testids = 'data-testid="serp-core-classified-card-testid"' in html
            has_prices = 'data-testid="cardmfe-price-testid"' in html

            return TestResult(
                name=name,
                passed=len(listings) > 0,
                is_ssr=has_data_testids,
                details=(
                    f"HTTP {resp.status_code}, HTML: {len(html)} bytes, "
                    f"SSR data-testids: {has_data_testids}, Prices in HTML: {has_prices}, "
                    f"Listings extracted: {len(listings)}"
                ),
                listings=listings,
                response_time_ms=elapsed, status_code=resp.status_code,
            )
        except Exception as e:
            return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_httpx_headers_variation() -> TestResult:
    """Test with minimal headers vs full browser headers."""
    name = "headers_variation"
    url = SEARCH_URLS["apartment_rent_berlin"]

    # Minimal headers (just User-Agent)
    minimal_headers = {"User-Agent": BROWSER_HEADERS["User-Agent"]}

    results_text = []
    for label, headers in [("minimal", minimal_headers), ("full_browser", BROWSER_HEADERS)]:
        async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                bot = check_bot_detection(resp.text, resp.status_code)
                results_text.append(f"{label}: HTTP {resp.status_code}, bot={bot}, size={len(resp.text)}")
            except Exception as e:
                results_text.append(f"{label}: Error: {e}")

    return TestResult(
        name=name, passed=True,
        details=" | ".join(results_text),
    )


async def test_json_api_search() -> TestResult:
    """Check if Immowelt has a JSON API endpoint (some SPAs expose one)."""
    name = "json_api_probe"
    # Common patterns for SPA backends
    api_urls = [
        f"{BASE_URL}/api/search?type=wohnungen&city=berlin&transaction=mieten",
        f"{BASE_URL}/api/v1/listings?city=berlin&type=rent",
        "https://api.immowelt.de/search?city=berlin&type=wohnungen",
    ]

    results_text = []
    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=10, follow_redirects=True) as client:
        for url in api_urls:
            try:
                resp = await client.get(url)
                is_json = "application/json" in resp.headers.get("content-type", "")
                results_text.append(f"{url}: HTTP {resp.status_code}, JSON={is_json}")
            except Exception as e:
                results_text.append(f"{url}: {e}")

    return TestResult(
        name=name, passed=False,
        details=" | ".join(results_text),
    )


def print_result(result: TestResult) -> None:
    """Pretty-print a test result."""
    icon = "PASS" if result.passed else "FAIL"
    if result.bot_detected:
        icon = "BOT!"
    print(f"\n[{icon}] {result.name}")
    print(f"  {result.details}")
    if result.response_time_ms:
        print(f"  Response time: {result.response_time_ms:.0f}ms")
    if result.is_ssr:
        print("  SSR: Yes (data in initial HTML)")

    for listing in result.listings[:3]:
        print("  ---")
        print(f"  ID:   {listing.id}")
        print(f"  Link: {listing.link}")


async def main() -> None:
    print("=" * 70)
    print("Immowelt Scraper Test")
    print("=" * 70)

    # Test 1: SSR check — apartments for rent in Berlin
    result = await test_httpx_ssr(
        SEARCH_URLS["apartment_rent_berlin"], "apartment_rent_berlin"
    )
    print_result(result)

    # Test 2: SSR check — houses for sale in Munich
    result = await test_httpx_ssr(
        SEARCH_URLS["house_buy_munich"], "house_buy_munich"
    )
    print_result(result)

    # Test 3: Headers variation
    result = await test_httpx_headers_variation()
    print_result(result)

    # Test 4: JSON API probe
    result = await test_json_api_search()
    print_result(result)

    print("\n" + "=" * 70)
    print("Test complete.")
    print()
    print("NEXT STEPS:")
    print("  If SSR=No and listings=0, Immowelt is JS-rendered.")
    print("  In that case, Playwright with stealth headers is required.")
    print("  Run: python3 backend/apps/home/tests/test_immowelt_playwright.py")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
