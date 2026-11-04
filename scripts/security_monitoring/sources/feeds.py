"""Feed-style sources: Ubuntu notices, CISA KEV, EPSS, vendor status and news.

Unstructured and time-ordered feeds respect the `since` window. News and
vendor items carry only keywords (canonical inventory names found on word
boundaries), never raw article text. Feed URLs were verified as
machine-readable; vendors without such a feed are reported as unsupported
instead of scraping HTML. See security-monitoring.sources.hourly-deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
import re
from typing import Any, Callable, Iterable, Mapping
import xml.etree.ElementTree as ElementTree

from security_monitoring.matcher import KeywordTable
from security_monitoring.models import AdvisoryItem, Inventory
from security_monitoring.sources.fetch import FetchError

Fetch = Callable[[str, "dict[str, Any] | None"], Any]

USN_URL = "https://ubuntu.com/security/notices.json"
USN_PAGE_SIZE = 20  # the notices API rejects larger pages
USN_MAX_PAGES = 10
KEV_URLS = (
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    # Official CISA-maintained mirror; the primary URL rejects some automated clients.
    "https://raw.githubusercontent.com/cisagov/kev-data/main/known_exploited_vulnerabilities.json",
)
EPSS_URL = "https://api.first.org/data/v1/epss"
EPSS_BATCH = 50
EPSS_MAX_CVES = 200
NEWS_FEEDS = {
    "cert-eu": "https://cert.europa.eu/publications/security-advisories-rss",
    "bleepingcomputer": "https://www.bleepingcomputer.com/feed/",
    "thehackernews": "https://feeds.feedburner.com/TheHackersNews",
}
VENDOR_FEEDS = {"hetzner": "https://status.hetzner.com/en.atom"}
# Vendors without a machine-readable security bulletin feed (verified 2026-11-04).
UNSUPPORTED_VENDORS = {"vercel": "no_machine_readable_bulletin_feed"}
MAX_FEED_ITEMS = 100
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_PUBLIC_EXPLOIT_RE = re.compile(r"proof[- ]of[- ]concept|\bPoC\b|exploit (?:code|released|published|is public)", re.IGNORECASE)
_CRITICAL_RE = re.compile(r"\bcritical\b", re.IGNORECASE)
_HIGH_RE = re.compile(r"\bhigh[- ]severity\b", re.IGNORECASE)
_VENDOR_SECURITY_RE = re.compile(
    r"security|vulnerab|phishing|breach|compromis|unauthori[sz]ed|ddos|malware|exploit|leak|incident", re.IGNORECASE)


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


# -- Ubuntu notices ------------------------------------------------------------------

def ubuntu_releases(inventory: Inventory) -> set[str]:
    return {str(asset.version) for asset in inventory.assets
            if asset.kind == "runtime" and asset.ecosystem == "os" and asset.name == "ubuntu" and asset.version}


def _usn_item(notice: Mapping[str, Any], releases: set[str]) -> AdvisoryItem | None:
    codenames = {str(release.get("codename")): str(release.get("version"))
                 for release in notice.get("releases") or () if isinstance(release, dict)}
    affected = []
    for codename, packages in (notice.get("release_packages") or {}).items():
        version = codenames.get(codename)
        if version not in releases:
            continue
        for package in packages or ():
            if isinstance(package, dict) and package.get("name") and package.get("version"):
                affected.append({"ecosystem": "ubuntu", "release": version, "name": package["name"],
                                 "fixed": [package["version"]]})
    if not affected:
        return None
    cves = tuple(sorted({str(cve).upper() for cve in notice.get("cves_ids") or () if cve}))
    published = parse_time(notice.get("published"))
    return AdvisoryItem(
        source="ubuntu_usn", advisory_id=str(notice["id"]), aliases=cves, title=str(notice.get("title") or notice["id"]),
        severity="unknown", published_at=_iso(published), modified_at=_iso(published), affected=tuple(affected),
        url=f"https://ubuntu.com/security/notices/{notice['id']}",
    )


def collect_usn(inventory: Inventory, since: datetime, fetch: Fetch) -> list[AdvisoryItem]:
    releases = ubuntu_releases(inventory)
    items: list[AdvisoryItem] = []
    for page in range(USN_MAX_PAGES):
        payload = fetch(f"{USN_URL}?limit={USN_PAGE_SIZE}&offset={page * USN_PAGE_SIZE}", {"timeout": 45})
        notices = payload.get("notices") if isinstance(payload, dict) else None
        if not isinstance(notices, list):
            raise FetchError("malformed")
        reached_window_start = False
        for notice in notices:
            if not isinstance(notice, dict) or not notice.get("id"):
                raise FetchError("malformed")
            published = parse_time(notice.get("published"))
            if published is not None and published < since:
                reached_window_start = True
                continue
            item = _usn_item(notice, releases)
            if item is not None:
                items.append(item)
        if reached_window_start or len(notices) < USN_PAGE_SIZE:
            break
    return items


# -- CISA KEV and EPSS -----------------------------------------------------------------

def fetch_kev(fetch: Fetch) -> tuple[list[dict[str, Any]], str | None]:
    """Return (catalog entries, note) trying the primary URL, then the official mirror."""
    last_error = "network_error"
    for position, url in enumerate(KEV_URLS):
        try:
            payload = fetch(url, {"timeout": 60})
        except FetchError as error:
            last_error = error.code
            continue
        entries = payload.get("vulnerabilities") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            last_error = "malformed"
            continue
        return [entry for entry in entries if isinstance(entry, dict) and entry.get("cveID")], \
            ("mirror_used" if position else None)
    raise FetchError(last_error)


def kev_items(entries: Iterable[Mapping[str, Any]], since: datetime, table: KeywordTable) -> list[AdvisoryItem]:
    items = []
    for entry in entries:
        added = parse_time(entry.get("dateAdded"))
        if added is None or added.date() < since.date():
            continue
        product = str(entry.get("product") or "")
        phrase = f"{entry.get('vendorProject') or ''} {product}"
        names = set(table.names_in(product))
        # Vendor-only mentions ("Google" for a Chromium entry) do not name the affected product.
        for _term, assets in table.find(phrase):
            names.update(asset.name for asset in assets if asset.kind not in {"vendor", "skill_provider"})
        cve = str(entry["cveID"]).upper()
        items.append(AdvisoryItem(
            source="cisa_kev", advisory_id=cve, aliases=(), title=f"{phrase.strip()}: {entry.get('vulnerabilityName') or cve}",
            severity="unknown", published_at=_iso(added), modified_at=_iso(added), keywords=tuple(sorted(names)),
            known_exploited=True, url=f"https://nvd.nist.gov/vuln/detail/{cve}",
        ))
    return items


def fetch_epss(cves: Iterable[str], fetch: Fetch) -> dict[str, float]:
    ordered = sorted(set(cves))[:EPSS_MAX_CVES]
    scores: dict[str, float] = {}
    for start in range(0, len(ordered), EPSS_BATCH):
        batch = ordered[start:start + EPSS_BATCH]
        payload = fetch(f"{EPSS_URL}?cve={','.join(batch)}", {"timeout": 30})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise FetchError("malformed")
        for row in data:
            if isinstance(row, dict) and row.get("cve") and row.get("epss") is not None:
                scores[str(row["cve"]).upper()] = float(row["epss"])
    return scores


# -- RSS / Atom ------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ElementTree.Element, *names: str) -> str:
    for child in node:
        if _local(child.tag) in names:
            if _local(child.tag) == "link" and child.get("href"):
                return child.get("href", "")
            return "".join(child.itertext()).strip()
    return ""


def parse_feed(text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 or Atom into [{title, link, summary, published}]."""
    root = ElementTree.fromstring(text)
    entries = [node for node in root.iter() if _local(node.tag) in {"item", "entry"}]
    parsed = []
    for node in entries[:MAX_FEED_ITEMS]:
        summary = _child_text(node, "description", "summary", "content")
        parsed.append({
            "title": html.unescape(_TAG_RE.sub(" ", _child_text(node, "title"))).strip(),
            "link": _child_text(node, "link", "guid", "id").strip(),
            "summary": " ".join(html.unescape(_TAG_RE.sub(" ", html.unescape(summary))).split())[:2000],
            "published": _child_text(node, "pubdate", "published", "updated", "date"),
        })
    return parsed


def _text_item(source: str, entry: Mapping[str, str], table: KeywordTable, kev: set[str],
               extra_keywords: tuple[str, ...] = ()) -> AdvisoryItem:
    title, summary = entry["title"], entry["summary"]
    text = f"{title} {summary[:600]}"
    cves = sorted({match.upper() for match in _CVE_RE.findall(f"{title} {summary}")})
    published = parse_time(entry.get("published"))
    digest = hashlib.sha256((entry.get("link") or title).encode("utf-8")).hexdigest()[:16]
    severity = "critical" if _CRITICAL_RE.search(title) else "high" if _HIGH_RE.search(title) else "unknown"
    return AdvisoryItem(
        source=source, advisory_id=f"{source.upper()}-{digest}",
        # A single CVE identifies the article's subject; several CVEs (patch round-ups) would merge unrelated advisories.
        aliases=tuple(cves) if len(cves) == 1 else (),
        title=title[:300], severity=severity,  # type: ignore[arg-type]  # literal
        published_at=_iso(published), modified_at=_iso(published),
        keywords=tuple(sorted(set(table.names_in(text)) | set(extra_keywords))),
        known_exploited=any(cve in kev for cve in cves),
        public_exploit=bool(_PUBLIC_EXPLOIT_RE.search(text)),
        url=entry.get("link") or None,
    )


def collect_feed(source: str, url: str, since: datetime, fetch: Fetch, table: KeywordTable, kev: set[str],
                 *, vendor_name: str | None = None) -> list[AdvisoryItem]:
    text = fetch(url, {"format": "text", "timeout": 30})
    if not isinstance(text, str):
        raise FetchError("malformed")
    items = []
    for entry in parse_feed(text):
        published = parse_time(entry.get("published"))
        if published is None or published < since or not entry["title"]:
            continue
        if vendor_name and not _VENDOR_SECURITY_RE.search(f"{entry['title']} {entry['summary'][:600]}"):
            continue  # status pages also announce maintenance and outages
        items.append(_text_item(source, entry, table, kev, (vendor_name,) if vendor_name else ()))
    return items
