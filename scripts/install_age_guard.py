#!/usr/bin/env python3
"""Release-age gate for package installs (owner decision, 21 Nov).

A version may be installed only once it has been public for 7 days, unless it
fixes an actively exploited flaw (the CVE is in the CISA KEV catalog and is
passed with --kev). Fails closed: any lookup error refuses.

    python3 scripts/install_age_guard.py check --ecosystem npm --name left-pad \
        [--version 1.3.0] [--kev CVE-2026-0001]

Prints one JSON line. Exit 0 = allowed, 1 = refused, 2 = lookup error (refused).
Reuses the registry helpers of scripts/security_monitoring/release_age.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_monitoring import release_age as ra  # noqa: E402 - path insert above
from security_monitoring.sources.fetch import FetchError  # noqa: E402 - path insert above

MIN_AGE = ra.ROUTINE_AGE
ECOSYSTEMS = ("npm", "PyPI", "crates.io")
_PRERELEASE = re.compile(r"(-|\d)(a|b|rc|alpha|beta|dev|pre|canary|next)\d*|-", re.I)


def _is_prerelease(version: str) -> bool:
    return bool(_PRERELEASE.search(version.lstrip("v")))


def registry_versions(ecosystem: str, name: str) -> tuple[str | None, dict[str, datetime]]:
    """Return (latest stable version, {version: first publication time}). Raises RegistryLookupError."""
    quoted = urllib.parse.quote(name, safe="@")
    if ecosystem == "npm":
        doc = ra._fetch_json("https://registry.npmjs.org/" + quoted) or {}
        known = doc.get("versions") or {}
        times = {v: ra.parse_time(t) for v, t in (doc.get("time") or {}).items() if v in known}
        return (doc.get("dist-tags") or {}).get("latest"), times
    if ecosystem == "PyPI":
        doc = ra._fetch_json(f"https://pypi.org/pypi/{quoted}/json") or {}
        times = {}
        for version, files in (doc.get("releases") or {}).items():
            stamps = [f["upload_time_iso_8601"] for f in files if f.get("upload_time_iso_8601") and not f.get("yanked")]
            if stamps:
                times[version] = ra.parse_time(min(stamps))
        return (doc.get("info") or {}).get("version"), times
    if ecosystem == "crates.io":
        doc = ra._fetch_json(f"https://crates.io/api/v1/crates/{quoted}") or {}
        times = {v["num"]: ra.parse_time(v["created_at"]) for v in doc.get("versions") or [] if not v.get("yanked")}
        return (doc.get("crate") or {}).get("max_stable_version"), times
    raise ra.RegistryLookupError(f"unsupported ecosystem {ecosystem}")


def kev_cves() -> set[str]:
    """CVE ids of the CISA Known Exploited Vulnerabilities catalog (shared with the release-age check)."""
    return ra.kev_cves()


def decide(ecosystem: str, name: str, version: str | None = None, kev: str | None = None,
           now: datetime | None = None) -> dict[str, Any]:
    """Return the decision record; `allowed` is True only when the policy is met."""
    now = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {"ecosystem": ecosystem, "name": name, "version": version, "allowed": False}
    try:
        latest, times = registry_versions(ecosystem, name)
        version = version or latest
        result["version"] = version
        if not version or version not in times:
            result["reason"] = f"version {version or '(latest)'} not found in the {ecosystem} registry"
            return result
        age = now - times[version]
        result["published_at"] = times[version].isoformat()
        result["age_days"] = round(age.total_seconds() / 86400, 2)
        if age >= MIN_AGE:
            result.update(allowed=True, reason="published at least 7 days ago")
            return result
        if kev:
            cve = kev.upper()
            if cve in kev_cves():
                result.update(allowed=True, reason=f"{cve} is in the CISA KEV catalog (actively exploited)")
                return result
            result["reason"] = f"{cve} is not in the CISA KEV catalog; version is younger than 7 days"
        else:
            result["reason"] = "version is younger than 7 days"
        older = [v for v, t in times.items() if now - t >= MIN_AGE and not _is_prerelease(v)]
        if older:
            result["suggested_version"] = max(older, key=ra.version_key)
    except (ra.RegistryLookupError, FetchError, ValueError, KeyError, TypeError) as error:
        result.update(error=True, reason=f"lookup failed, refusing: {error}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="exit 0 only if the version is old enough")
    check.add_argument("--ecosystem", required=True, choices=ECOSYSTEMS)
    check.add_argument("--name", required=True)
    check.add_argument("--version")
    check.add_argument("--kev", help="CVE id that this version fixes and that is in CISA KEV")
    args = parser.parse_args(argv)
    result = decide(args.ecosystem, args.name, args.version, args.kev)
    print(json.dumps(result))
    if result["allowed"]:
        return 0
    return 2 if result.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
