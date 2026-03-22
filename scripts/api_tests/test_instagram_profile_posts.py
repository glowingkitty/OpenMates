#!/usr/bin/env python3
"""
Purpose: Scrape recent public Instagram posts/reels for one or more accounts.
Architecture: Standalone reverse-engineering helper script for API feasibility checks.
Architecture Doc: docs/architecture/README.md
Tests: N/A (manual CLI verification script)

This script uses Playwright + a rotating Webshare proxy to render profile pages,
extract latest media links, open each media URL, and parse caption text.
"""

import argparse
from datetime import datetime
import html
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Optional
from urllib.parse import urljoin

from playwright.sync_api import Browser, Page, sync_playwright


INSTAGRAM_BASE_URL = "https://www.instagram.com"
PROFILE_LOAD_WAIT_MS = 5_000
MEDIA_LOAD_WAIT_MS = 1_800
DEFAULT_LIMIT = 3
DEFAULT_PROFILE_ATTEMPTS = 6
DEFAULT_ACCOUNT_ATTEMPTS = 3
DEFAULT_MEDIA_FETCH_ATTEMPTS = 3

DEFAULT_PROXY_HOST = "p.webshare.io"
DEFAULT_PROXY_PORT = 80

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class MediaPost:
    account: str
    media_type: str
    shortcode: str
    media_url: str
    owner: str
    published_label: str
    caption: str
    raw_description: str


@dataclass
class ProfileMediaLink:
    href: str
    pinned: bool


def published_label_to_sort_key(published_label: str) -> tuple[int, str]:
    """
    Return sortable key where larger is newer.

    Known format from Instagram og:description: 'February 28, 2026'.
    Unknown formats are sent to the end while preserving deterministic ordering.
    """
    try:
        parsed_date = datetime.strptime(published_label, "%B %d, %Y")
        return int(parsed_date.timestamp()), published_label
    except Exception:
        return -1, published_label


def build_proxy_config(proxy_username: str, proxy_password: str) -> dict:
    return {
        "server": f"http://{DEFAULT_PROXY_HOST}:{DEFAULT_PROXY_PORT}",
        "username": proxy_username,
        "password": proxy_password,
    }


def parse_og_description(description: str) -> tuple[str, str, str]:
    """Return (owner, published_label, caption) from og:description content."""
    decoded = html.unescape(description or "")
    owner_match = re.search(r" - ([A-Za-z0-9._]+) on ", decoded)
    published_match = re.search(r" on ([^:]+): ", decoded)
    caption_match = re.search(r":\s*\"(.*)\"\.?\s*$", decoded, flags=re.DOTALL)

    owner = owner_match.group(1).lower() if owner_match else ""
    published_label = published_match.group(1).strip() if published_match else ""
    caption = caption_match.group(1).strip() if caption_match else decoded.strip()
    return owner, published_label, caption


def extract_shortcode(media_href: str, account: str) -> tuple[str, str]:
    match = re.search(rf"/{re.escape(account)}/(p|reel)/([A-Za-z0-9_-]+)/", media_href)
    if not match:
        raise ValueError(f"Could not parse media href: {media_href}")
    return match.group(1), match.group(2)


def collect_profile_media_hrefs(page: Page, account: str) -> list[ProfileMediaLink]:
    selector = f'a[href*="/{account}/p/"], a[href*="/{account}/reel/"]'
    entries = page.eval_on_selector_all(
        selector,
        (
            "elements => elements.map(element => ({"
            "href: element.getAttribute('href'), "
            "ariaLabel: element.getAttribute('aria-label') || ''"
            "}))"
        ),
    )

    unique_links: list[ProfileMediaLink] = []
    seen: set[str] = set()
    pattern = re.compile(rf"/{re.escape(account)}/(p|reel)/[A-Za-z0-9_-]+/")

    for entry in entries:
        href = entry.get("href")
        if not href:
            continue
        if not pattern.search(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        aria_label = (entry.get("ariaLabel") or "").lower()
        unique_links.append(ProfileMediaLink(href=href, pinned="pinned" in aria_label))

    non_pinned_links = [link for link in unique_links if not link.pinned]
    pinned_links = [link for link in unique_links if link.pinned]
    return non_pinned_links + pinned_links


def load_profile_hrefs_with_retry(
    browser: Browser,
    account: str,
    profile_attempts: int,
) -> list[ProfileMediaLink]:
    profile_url = f"{INSTAGRAM_BASE_URL}/{account}/"
    attempts = max(1, profile_attempts)

    for attempt in range(1, attempts + 1):
        page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
        try:
            page.goto(profile_url, wait_until="domcontentloaded", timeout=70_000)
            page.wait_for_timeout(PROFILE_LOAD_WAIT_MS)
            links = collect_profile_media_hrefs(page, account)
            if links:
                return links
            print(f"[{account}] attempt {attempt}/{attempts}: no media links yet")
        finally:
            page.close()

    raise RuntimeError(
        f"Could not load profile media links for '{account}' after {attempts} attempts"
    )


def fetch_media_post(page: Page, account: str, media_href: str) -> Optional[MediaPost]:
    media_type, shortcode = extract_shortcode(media_href, account)
    media_url = urljoin(INSTAGRAM_BASE_URL, media_href)

    page.goto(media_url, wait_until="domcontentloaded", timeout=70_000)
    page.wait_for_timeout(MEDIA_LOAD_WAIT_MS)
    document_html = page.content()

    description_match = re.search(
        r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"',
        document_html,
    )
    if not description_match:
        return None

    raw_description = description_match.group(1)
    owner, published_label, caption = parse_og_description(raw_description)

    # Keep only posts authored by the requested account (skip tagged/external media).
    if owner and owner != account.lower():
        return None

    return MediaPost(
        account=account,
        media_type=media_type,
        shortcode=shortcode,
        media_url=media_url,
        owner=owner or account.lower(),
        published_label=published_label,
        caption=caption,
        raw_description=html.unescape(raw_description),
    )


def scrape_account_posts(
    browser: Browser,
    account: str,
    limit: int,
    profile_attempts: int,
) -> list[MediaPost]:
    links = load_profile_hrefs_with_retry(browser, account, profile_attempts)
    print(f"[{account}] found {len(links)} profile media links")

    account_posts: list[MediaPost] = []
    page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
    try:
        for media_link in links:
            if len(account_posts) >= limit:
                break

            post: Optional[MediaPost] = None
            for media_attempt in range(1, DEFAULT_MEDIA_FETCH_ATTEMPTS + 1):
                try:
                    post = fetch_media_post(page, account, media_link.href)
                    break
                except Exception as exc:
                    print(
                        f"[{account}] media attempt {media_attempt}/"
                        f"{DEFAULT_MEDIA_FETCH_ATTEMPTS} failed for {media_link.href} ({exc})"
                    )
                    if media_attempt < DEFAULT_MEDIA_FETCH_ATTEMPTS:
                        time.sleep(0.8)

            if post is None:
                continue

            account_posts.append(post)
    finally:
        page.close()

    account_posts.sort(
        key=lambda post: published_label_to_sort_key(post.published_label),
        reverse=True,
    )
    return account_posts[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch latest public Instagram captions for account(s)"
    )
    parser.add_argument(
        "--accounts",
        nargs="+",
        required=True,
        help="Instagram handles (without @), e.g. openai anthropic manus_ai",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"How many latest items to return per account (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--profile-attempts",
        type=int,
        default=DEFAULT_PROFILE_ATTEMPTS,
        help=(
            "How many times to retry loading profile links "
            f"(default: {DEFAULT_PROFILE_ATTEMPTS})"
        ),
    )
    parser.add_argument(
        "--account-attempts",
        type=int,
        default=DEFAULT_ACCOUNT_ATTEMPTS,
        help=(
            "How many times to retry an account scrape after network errors "
            f"(default: {DEFAULT_ACCOUNT_ATTEMPTS})"
        ),
    )
    parser.add_argument(
        "--proxy-username",
        default="",
        help="Proxy username (default: env WEBSHARE_PROXY_USERNAME)",
    )
    parser.add_argument(
        "--proxy-password",
        default="",
        help="Proxy password (default: env WEBSHARE_PROXY_PASSWORD)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    return parser.parse_args()


def resolve_proxy_credentials(args: argparse.Namespace) -> tuple[str, str]:
    proxy_username = args.proxy_username or ""
    proxy_password = args.proxy_password or ""

    if not proxy_username:
        proxy_username = (os.environ.get("WEBSHARE_PROXY_USERNAME") or "").strip()
    if not proxy_password:
        proxy_password = (os.environ.get("WEBSHARE_PROXY_PASSWORD") or "").strip()

    if not proxy_username or not proxy_password:
        raise ValueError(
            "Missing proxy credentials. Provide --proxy-username/--proxy-password "
            "or set WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD."
        )

    return proxy_username, proxy_password


def main() -> None:
    args = parse_args()
    limit = max(1, args.limit)

    try:
        proxy_username, proxy_password = resolve_proxy_credentials(args)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    proxy_config = build_proxy_config(proxy_username, proxy_password)
    started_at = time.time()

    results: dict[str, list[MediaPost]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, proxy=proxy_config)
        try:
            for account in args.accounts:
                normalized_account = account.strip().lstrip("@").lower()
                if not normalized_account:
                    continue
                account_attempts = max(1, args.account_attempts)
                posts: list[MediaPost] = []
                for attempt in range(1, account_attempts + 1):
                    try:
                        posts = scrape_account_posts(
                            browser=browser,
                            account=normalized_account,
                            limit=limit,
                            profile_attempts=args.profile_attempts,
                        )
                        break
                    except Exception as exc:
                        print(
                            f"[{normalized_account}] account attempt "
                            f"{attempt}/{account_attempts} failed: {exc}"
                        )
                        if attempt < account_attempts:
                            time.sleep(1.5)

                results[normalized_account] = posts
        finally:
            browser.close()

    duration_seconds = time.time() - started_at

    if args.json:
        output = {
            "duration_seconds": round(duration_seconds, 2),
            "accounts": {
                account: [asdict(post) for post in posts]
                for account, posts in results.items()
            },
        }
        print(json.dumps(output, ensure_ascii=True, indent=2))
        return

    print(f"Completed in {duration_seconds:.2f}s")
    for account, posts in results.items():
        print("\n" + "=" * 72)
        print(f"@{account} - latest {len(posts)} post(s)")
        print("=" * 72)
        if not posts:
            print("No posts captured.")
            continue

        for index, post in enumerate(posts, start=1):
            print(f"[{index}] {post.media_url}")
            print(f"    type: {post.media_type}")
            if post.published_label:
                print(f"    published: {post.published_label}")
            print(f"    text: {post.caption}")


if __name__ == "__main__":
    main()
