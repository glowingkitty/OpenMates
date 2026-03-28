"""
Kleinanzeigen Scraper Test Script
====================================
Tests HTML scraping of Kleinanzeigen (formerly eBay Kleinanzeigen).
Known as the easiest platform to scrape among German real estate sites.

CSS selectors based on Fredy project (orangecoding/fredy).

Usage:
  python3 backend/apps/home/tests/test_kleinanzeigen.py
"""

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

# --- Constants ---

BASE_URL = "https://www.kleinanzeigen.de"

# Search URL pattern: /s-wohnungen-mieten/berlin/c203l3331
# Category codes: c203 = Mietwohnungen, c196 = Kaufwohnungen, c208 = Häuser mieten, c197 = Häuser kaufen
# Location codes: l3331 = Berlin, l6411 = München, l9409 = Hamburg
SEARCH_URLS = {
    "apartment_rent_berlin": f"{BASE_URL}/s-wohnungen-mieten/berlin/c203l3331",
    "apartment_buy_munich": f"{BASE_URL}/s-eigentumswohnungen/muenchen/c196l6411",
    "house_buy_hamburg": f"{BASE_URL}/s-haeuser-kaufen/hamburg/c208l9409",
}

# CSS selectors from Fredy's kleinanzeigen.js adapter
SELECTORS = {
    "container": "#srchrslt-adtable .ad-listitem",
    "id": ".aditem@data-adid",
    "price": ".aditem-main--middle--price-shipping--price",
    "size": ".aditem-main .text-module-end",
    "title": ".aditem-main .text-module-begin a",
    "link": ".aditem-main .text-module-begin a@href",
    "description": ".aditem-main .aditem-main--middle--description",
    "address": ".aditem-main--top--left",
    "image": "img@src",
}

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
    """Normalized listing extracted from Kleinanzeigen."""
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
    re.compile(r"blocked", re.IGNORECASE),
    re.compile(r"rate.?limit", re.IGNORECASE),
]


def check_bot_detection(html: str, status_code: int) -> bool:
    if status_code in (403, 429):
        return True
    return any(pattern.search(html) for pattern in BOT_PATTERNS)


def parse_listings_from_html(html: str) -> list[Listing]:
    """
    Parse listings from Kleinanzeigen HTML.
    Kleinanzeigen is known for server-side rendering, so data should be in initial HTML.
    """
    listings = []

    # Check for the main listing container
    has_aditems = "ad-listitem" in html

    if not has_aditems:
        return listings

    # Extract data-adid (listing IDs)
    adid_pattern = re.compile(r'data-adid="(\d+)"')

    # Extract titles and links — pattern varies but generally:
    # <a class="ellipsis" href="/s-anzeige/...">Title</a>
    title_pattern = re.compile(
        r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>'
    )

    # Get all ad IDs first
    ad_ids = adid_pattern.findall(html)

    # Get all title+link pairs
    title_matches = title_pattern.findall(html)

    # Combine — Kleinanzeigen typically has a 1:1 mapping
    for i, ad_id in enumerate(ad_ids[:20]):
        title = ""
        link = ""
        if i < len(title_matches):
            link = title_matches[i][0]
            title = title_matches[i][1].strip()

        full_link = link if link.startswith("http") else f"{BASE_URL}{link}"

        listings.append(Listing(
            id=ad_id,
            title=title or f"[listing {ad_id}]",
            link=full_link,
        ))

    return listings


async def test_httpx_fetch(url: str, label: str) -> TestResult:
    """Fetch a Kleinanzeigen search page and check for SSR data."""
    name = f"httpx_fetch({label})"
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
                    details=f"Bot detected! HTTP {resp.status_code}, HTML: {len(html)} bytes",
                    response_time_ms=elapsed, status_code=resp.status_code,
                )

            listings = parse_listings_from_html(html)
            has_adtable = "srchrslt-adtable" in html
            has_aditems = "ad-listitem" in html
            has_data_adid = "data-adid" in html

            return TestResult(
                name=name,
                passed=len(listings) > 0,
                is_ssr=has_data_adid,
                details=(
                    f"HTTP {resp.status_code}, HTML: {len(html)} bytes, "
                    f"adtable: {has_adtable}, ad-listitem: {has_aditems}, "
                    f"data-adid: {has_data_adid}, Listings: {len(listings)}"
                ),
                listings=listings,
                response_time_ms=elapsed, status_code=resp.status_code,
            )
        except Exception as e:
            return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_minimal_headers() -> TestResult:
    """Test with minimal headers to see if Kleinanzeigen is lenient."""
    name = "minimal_headers"
    url = SEARCH_URLS["apartment_rent_berlin"]

    minimal_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Bot/1.0)",
    }
    async with httpx.AsyncClient(headers=minimal_headers, timeout=15, follow_redirects=True) as client:
        start = time.monotonic()
        try:
            resp = await client.get(url)
            elapsed = (time.monotonic() - start) * 1000
            html = resp.text

            bot = check_bot_detection(html, resp.status_code)
            listings = parse_listings_from_html(html)

            return TestResult(
                name=name,
                passed=not bot and len(listings) > 0,
                bot_detected=bot,
                details=(
                    f"HTTP {resp.status_code}, Bot: {bot}, "
                    f"Listings: {len(listings)}, HTML: {len(html)} bytes"
                ),
                listings=listings,
                response_time_ms=elapsed, status_code=resp.status_code,
            )
        except Exception as e:
            return TestResult(name=name, passed=False, details=f"Error: {e}")


async def test_pagination() -> TestResult:
    """Test pagination — Kleinanzeigen uses /seite:N/ in URL."""
    name = "pagination"
    base = SEARCH_URLS["apartment_rent_berlin"]

    results_text = []
    total_listings = 0

    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=15, follow_redirects=True) as client:
        for page in [1, 2]:
            url = f"{base}/seite:{page}/" if page > 1 else base
            try:
                resp = await client.get(url)
                listings = parse_listings_from_html(resp.text)
                total_listings += len(listings)
                results_text.append(f"Page {page}: {len(listings)} listings (HTTP {resp.status_code})")
            except Exception as e:
                results_text.append(f"Page {page}: Error: {e}")

    return TestResult(
        name=name, passed=total_listings > 0,
        details=" | ".join(results_text),
    )


async def test_rate_limiting(num_requests: int = 5) -> TestResult:
    """Quick rate limit test — 5 rapid requests."""
    name = f"rate_limiting({num_requests}_requests)"
    url = SEARCH_URLS["apartment_rent_berlin"]

    results = []
    start_all = time.monotonic()

    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=15, follow_redirects=True) as client:
        for i in range(num_requests):
            try:
                resp = await client.get(url)
                bot = check_bot_detection(resp.text, resp.status_code)
                results.append((resp.status_code, bot))
            except Exception:
                results.append((0, True))

    total_time = (time.monotonic() - start_all) * 1000
    blocked = sum(1 for _, bot in results if bot)
    codes = [r[0] for r in results]

    return TestResult(
        name=name,
        passed=blocked == 0,
        details=(
            f"Total: {total_time:.0f}ms, Status codes: {codes}, "
            f"Bot detected: {blocked}/{num_requests}"
        ),
        response_time_ms=total_time,
    )


def print_result(result: TestResult) -> None:
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
        print(f"  ID:    {listing.id}")
        print(f"  Title: {listing.title}")
        print(f"  Link:  {listing.link}")


async def main() -> None:
    print("=" * 70)
    print("Kleinanzeigen Scraper Test")
    print("=" * 70)

    # Test 1: Apartments for rent in Berlin (SSR check)
    result = await test_httpx_fetch(
        SEARCH_URLS["apartment_rent_berlin"], "apartment_rent_berlin"
    )
    print_result(result)

    # Test 2: Apartments to buy in Munich
    result = await test_httpx_fetch(
        SEARCH_URLS["apartment_buy_munich"], "apartment_buy_munich"
    )
    print_result(result)

    # Test 3: Minimal headers
    result = await test_minimal_headers()
    print_result(result)

    # Test 4: Pagination
    result = await test_pagination()
    print_result(result)

    # Test 5: Rate limiting
    result = await test_rate_limiting(num_requests=5)
    print_result(result)

    print("\n" + "=" * 70)
    print("Test complete.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
