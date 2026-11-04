"""Hourly deterministic advisory collection for automated security monitoring.

`collect()` queries every configured source without AI inference and returns
normalized `AdvisoryItem`s plus one `SourceStatus` per source. One source
failing never raises: it is recorded as `ok=False` with a sanitized
`error_code`, so a failure is incomplete coverage rather than a clean result.
Sources that have no machine-readable feed are recorded with
`supported=False` (and `ok=False`) as a known coverage gap. See
specifications/architecture/security-monitoring/specification.yml
(security-monitoring.sources.hourly-deterministic).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Any, Callable
import xml.etree.ElementTree as ElementTree

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from security_monitoring import matcher  # noqa: E402 - package import after path setup
from security_monitoring.models import AdvisoryItem, Inventory  # noqa: E402 - package import after path setup
from security_monitoring.sources import feeds, packages  # noqa: E402 - package import after path setup
from security_monitoring.sources.fetch import FetchError, default_fetch  # noqa: E402 - package import after path setup

Fetch = Callable[[str, "dict[str, Any] | None"], Any]

# Base-image OS trackers need the package list inside each image, which the
# inventory does not have yet; OSV covers language packages for these images.
UNSUPPORTED_TRACKERS = {
    "debian_tracker": "image_package_inventory_unavailable",
    "alpine_secdb": "image_package_inventory_unavailable",
}
# Malformed payloads surface as these; each is recorded as a failed source.
_SOURCE_ERRORS = (FetchError, OSError, ValueError, KeyError, TypeError, AttributeError, ElementTree.ParseError)


@dataclass(frozen=True)
class SourceStatus:
    name: str
    ok: bool
    error_code: str | None
    item_count: int
    supported: bool = True


def _error_code(error: BaseException) -> str:
    if isinstance(error, FetchError):
        return error.code
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ElementTree.ParseError):
        return "invalid_xml"
    if isinstance(error, OSError):
        return "network_error"
    return "malformed"


class _Run:
    def __init__(self) -> None:
        self.items: list[AdvisoryItem] = []
        self.statuses: list[SourceStatus] = []

    def source(self, name: str, reader: Callable[[], Any]) -> Any:
        try:
            result = reader()
        except _SOURCE_ERRORS as error:
            self.statuses.append(SourceStatus(name, False, _error_code(error), 0))
            return None
        items, note = result if isinstance(result, tuple) else (result, None)
        self.items.extend(items)
        self.statuses.append(SourceStatus(name, note is None, note, len(items)))
        return items

    def unsupported(self, name: str, code: str) -> None:
        self.statuses.append(SourceStatus(name, False, code, 0, supported=False))


def _cves(item: AdvisoryItem) -> set[str]:
    return {alias for alias in matcher.item_aliases(item) if alias.startswith("CVE-")}


def collect(*, since: datetime, now: datetime, inventory: Inventory,
            fetch: Fetch | None = None) -> tuple[list[AdvisoryItem], list[SourceStatus]]:
    """Collect normalized advisory items from every source for the `since`..`now` window."""
    fetcher: Fetch = fetch or default_fetch
    run = _Run()
    table = matcher.build_keyword_table(inventory)
    window_start = min(since, now - timedelta(minutes=5))

    run.source("osv", lambda: packages.collect_osv(inventory, fetcher))
    run.source("dependabot", lambda: packages.collect_dependabot(fetcher))
    for repository in sorted(packages.UPSTREAM_REPOSITORIES):
        run.source(f"upstream:{repository}", lambda repository=repository: packages.collect_upstream(repository, fetcher))
    for repository, code in sorted(packages.UNSUPPORTED_UPSTREAM.items()):
        run.unsupported(f"upstream:{repository}", code)
    run.source("ubuntu_usn", lambda: feeds.collect_usn(inventory, window_start, fetcher))

    kev_set: set[str] = set()

    def read_kev() -> tuple[list[AdvisoryItem], str | None]:
        entries, _note = feeds.fetch_kev(fetcher)
        kev_set.update(str(entry["cveID"]).upper() for entry in entries)
        return feeds.kev_items(entries, window_start, table), None

    run.source("cisa_kev", read_kev)
    for name, url in sorted(feeds.NEWS_FEEDS.items()):
        run.source(f"news:{name}", lambda name=name, url=url: feeds.collect_feed(
            f"news:{name}", url, window_start, fetcher, table, kev_set))
    for name, url in sorted(feeds.VENDOR_FEEDS.items()):
        vendor = name.capitalize()
        run.source(f"vendor:{name}", lambda name=name, url=url, vendor=vendor: feeds.collect_feed(
            f"vendor:{name}", url, window_start, fetcher, table, kev_set, vendor_name=vendor))
    for name, code in sorted(feeds.UNSUPPORTED_VENDORS.items()):
        run.unsupported(f"vendor:{name}", code)
    for name, code in sorted(UNSUPPORTED_TRACKERS.items()):
        run.unsupported(name, code)

    items = [replace(item, known_exploited=True) if not item.known_exploited and _cves(item) & kev_set else item
             for item in run.items]

    # EPSS only for CVEs that actually match used inventory assets.
    matched_cves: set[str] = set()
    for observation in matcher.match(items, inventory, {}):
        if observation.disposition != "suppressed_not_used":
            matched_cves |= _cves(observation.advisory)
    scores: dict[str, float] = {}

    def read_epss() -> tuple[list[AdvisoryItem], str | None]:
        scores.update(feeds.fetch_epss(matched_cves, fetcher))
        return [], None

    if matched_cves:
        run.source("epss", read_epss)
        if run.statuses[-1].ok:
            run.statuses[-1] = replace(run.statuses[-1], item_count=len(scores))
    else:
        run.statuses.append(SourceStatus("epss", True, None, 0))
    if scores:
        items = [replace(item, exploit_probability=max(scores[cve] for cve in _cves(item) & scores.keys()))
                 if _cves(item) & scores.keys() else item for item in items]
    return items, run.statuses


__all__ = ["SourceStatus", "collect", "FetchError", "default_fetch"]
