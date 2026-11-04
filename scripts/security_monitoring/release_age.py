"""Release-age policy for automated security monitoring.

Routine updates wait 7 days; security fixes use the oldest fixing version and
the 72-hour / emergency / mitigate rules. Spec:
specifications/architecture/security-monitoring/specification.yml
(security-monitoring.release-age.routine and .security-priority).

CLI:
  release_age.py select --ecosystem npm --name zod --current 4.6.2 \
      --fixed 4.6.6 --fixed 4.7.1 --urgent-reachable-exposed false
  release_age.py check-routine --base origin/dev
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_age_artifacts as artifacts  # noqa: E402 - sibling module needs the path insert above

ROUTINE_AGE = timedelta(days=7)
SECURITY_AGE = timedelta(hours=72)
USER_AGENT = "openmates-release-age (security monitoring)"
OSV_QUERY_URL = "https://api.osv.dev/v1/query"
INSTALL_SCRIPTS = ("preinstall", "install", "postinstall")

Mode = Literal["immediate", "emergency", "mitigate"]


class RegistryLookupError(RuntimeError):
    """A registry lookup failed; callers must fail closed."""


@dataclass
class FixVersionDecision:
    version: str | None
    mode: Mode
    reasons: list[str] = field(default_factory=list)


class Lookup(Protocol):
    """Registry facts needed by the policy; injectable for offline tests."""

    def published_at(self, ecosystem: str, name: str, version: str) -> datetime | None: ...
    def is_malicious(self, ecosystem: str, name: str, version: str) -> bool | None: ...
    def previous_version(self, ecosystem: str, name: str, version: str) -> str | None: ...
    def package_meta(self, ecosystem: str, name: str, version: str) -> dict[str, Any] | None: ...
    def content_flags(self, ecosystem: str, name: str, previous: str, version: str) -> list[str] | None: ...


def version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    """Sortable key: numeric release parts, then stable-before-prerelease."""
    core, _, pre = version.lstrip("v").partition("-")
    parts = tuple(int(p) for p in re.findall(r"\d+", core.split("+")[0])[:4])
    return parts, 0 if pre else 1, pre


def _major(version: str) -> int:
    return version_key(version)[0][0] if version_key(version)[0] else -1


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def choose_oldest_fix(current: str, fixed_versions: list[str]) -> str | None:
    """Lowest fixing version above current, preferring the current major line."""
    above = sorted((v for v in fixed_versions if version_key(v) > version_key(current)), key=version_key)
    same_line = [v for v in above if _major(v) == _major(current)]
    chosen = same_line or above
    return chosen[0] if chosen else None


def integrity_reasons(lookup: Lookup, ecosystem: str, name: str, version: str) -> list[str]:
    """Return failure reasons; an empty list means every integrity check passed."""
    reasons: list[str] = []
    malicious = lookup.is_malicious(ecosystem, name, version)
    if malicious is None:
        reasons.append("unverifiable: malicious-package record lookup failed")
    elif malicious:
        reasons.append("malicious-package (MAL-) record exists for this version")
    previous = lookup.previous_version(ecosystem, name, version)
    if previous is None:
        return reasons + ["unverifiable: previous version not found for diff"]
    new_meta = lookup.package_meta(ecosystem, name, version)
    old_meta = lookup.package_meta(ecosystem, name, previous)
    if new_meta is None or old_meta is None:
        return reasons + ["unverifiable: package metadata unavailable"]
    new_pub, old_pub = new_meta.get("publisher"), old_meta.get("publisher")
    if new_pub is None or old_pub is None:
        reasons.append("unverifiable: publisher identity not exposed by registry")
    elif new_pub != old_pub:
        reasons.append(f"publisher changed from {old_pub} to {new_pub}")
    elif old_meta.get("trusted_publisher") and not new_meta.get("trusted_publisher"):
        reasons.append("previous version used trusted-publishing provenance but this version does not")
    new_scripts, old_scripts = new_meta.get("install_scripts"), old_meta.get("install_scripts")
    if new_scripts is None or old_scripts is None:
        reasons.append("unverifiable: install scripts cannot be inspected for this ecosystem")
    elif set(new_scripts) - set(old_scripts):
        reasons.append("new install script(s): " + ", ".join(sorted(set(new_scripts) - set(old_scripts))))
    new_deps, old_deps = new_meta.get("dependencies"), old_meta.get("dependencies")
    if new_deps is None or old_deps is None:
        reasons.append("unverifiable: dependency list unavailable")
    elif set(new_deps) - set(old_deps):
        reasons.append("new dependencies: " + ", ".join(sorted(set(new_deps) - set(old_deps))))
    flags = lookup.content_flags(ecosystem, name, previous, version)
    if flags is None:
        reasons.append("unverifiable: package content diff unavailable")
    else:
        reasons.extend(flags)
    return reasons


def select_fix_version(
    ecosystem: str,
    name: str,
    current_version: str,
    fixed_versions: list[str],
    *,
    urgent_reachable_exposed: bool,
    now: datetime,
    lookup: Lookup | None = None,
) -> FixVersionDecision:
    lookup = lookup or NetworkLookup()
    version = choose_oldest_fix(current_version, fixed_versions)
    if version is None:
        return FixVersionDecision(None, "mitigate", ["no fixing version above the current version"])
    try:
        published = lookup.published_at(ecosystem, name, version)
    except RegistryLookupError as error:
        published = None
        age_note = f"publication time lookup failed: {error}"
    else:
        age_note = "publication time unavailable"
    if published is None:
        return FixVersionDecision(version, "mitigate", [age_note + " (fail closed); bump scheduled once verifiable"])
    age = now - published
    hours = age.total_seconds() / 3600
    if age >= SECURITY_AGE:
        return FixVersionDecision(version, "immediate", [f"oldest fixing version {version} is {hours:.0f}h old (>=72h)"])
    reasons = [f"oldest fixing version {version} is only {hours:.0f}h old (<72h)"]
    if not urgent_reachable_exposed:
        reasons.append("not urgent+reachable+exposed; apply allowlisted mitigation and schedule the bump")
        return FixVersionDecision(version, "mitigate", reasons)
    failures = integrity_reasons(lookup, ecosystem, name, version)
    if failures:
        return FixVersionDecision(version, "mitigate", reasons + failures)
    reasons.append("urgent reachable exposed issue and all integrity checks passed")
    return FixVersionDecision(version, "emergency", reasons)


def _fetch_json(url: str, *, data: dict[str, Any] | None = None) -> Any:
    body = json.dumps(data).encode() if data is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise RegistryLookupError(f"{url}: HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RegistryLookupError(f"{url}: {error}") from error


class NetworkLookup:
    """Live registry lookups (npm first-class; PyPI and crates best effort)."""

    def __init__(self) -> None:
        self._packuments: dict[str, Any] = {}

    def _packument(self, name: str) -> dict[str, Any] | None:
        if name not in self._packuments:
            self._packuments[name] = _fetch_json("https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@"))
        return self._packuments[name]

    def published_at(self, ecosystem: str, name: str, version: str) -> datetime | None:
        if ecosystem == "npm":
            doc = self._packument(name)
            stamp = (doc or {}).get("time", {}).get(version)
        elif ecosystem == "PyPI":
            doc = _fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json")
            times = [u["upload_time_iso_8601"] for u in (doc or {}).get("urls", []) if u.get("upload_time_iso_8601")]
            stamp = min(times) if times else None
        elif ecosystem == "crates.io":
            time.sleep(1.0)  # crates.io API asks for at most one request per second
            doc = _fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}")
            stamp = ((doc or {}).get("version") or {}).get("created_at")
        else:
            raise RegistryLookupError(f"unsupported ecosystem {ecosystem}")
        return parse_time(stamp) if stamp else None

    def is_malicious(self, ecosystem: str, name: str, version: str) -> bool | None:
        try:
            doc = _fetch_json(OSV_QUERY_URL, data={"package": {"name": name, "ecosystem": ecosystem}, "version": version})
        except RegistryLookupError:
            return None
        return any(str(v.get("id", "")).startswith("MAL-") for v in (doc or {}).get("vulns", []))

    def previous_version(self, ecosystem: str, name: str, version: str) -> str | None:
        if ecosystem == "npm":
            doc = self._packument(name) or {}
            older = [v for v in doc.get("versions", {}) if "-" not in v and version_key(v) < version_key(version)]
        elif ecosystem == "PyPI":
            doc = _fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json") or {}
            older = [v for v in doc.get("releases", {}) if version_key(v) < version_key(version)]
        else:
            time.sleep(1.0)
            doc = _fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}") or {}
            older = [v["num"] for v in doc.get("versions", []) if "-" not in v["num"] and version_key(v["num"]) < version_key(version)]
        return max(older, key=version_key) if older else None

    def package_meta(self, ecosystem: str, name: str, version: str) -> dict[str, Any] | None:
        if ecosystem == "npm":
            entry = ((self._packument(name) or {}).get("versions") or {}).get(version)
            if not entry:
                return None
            user = (entry.get("_npmUser") or {}).get("name")
            attested = bool((entry.get("dist") or {}).get("attestations"))
            scripts = entry.get("scripts") or {}
            return {
                "publisher": user,
                "trusted_publisher": attested,
                "install_scripts": [s for s in INSTALL_SCRIPTS if s in scripts],
                "dependencies": sorted((entry.get("dependencies") or {}).keys()),
                "file_count": (entry.get("dist") or {}).get("fileCount"),
                "unpacked_size": (entry.get("dist") or {}).get("unpackedSize"),
                "tarball": (entry.get("dist") or {}).get("tarball"),
            }
        if ecosystem == "PyPI":
            doc = _fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json")
            if not doc:
                return None
            requires = [re.split(r"[ ;<>=!~\[(]", r, 1)[0].lower() for r in (doc.get("info") or {}).get("requires_dist") or []]
            return {"publisher": None, "install_scripts": None, "dependencies": sorted(set(requires))}
        time.sleep(1.0)
        deps = _fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/dependencies")
        if deps is None:
            return None
        names = sorted({d["crate_id"] for d in deps.get("dependencies", []) if d.get("kind") != "dev"})
        return {"publisher": None, "install_scripts": None, "dependencies": names}

    def content_flags(self, ecosystem: str, name: str, previous: str, version: str) -> list[str] | None:
        if ecosystem != "npm":
            return None
        old, new = self.package_meta(ecosystem, name, previous), self.package_meta(ecosystem, name, version)
        if not old or not new or not old.get("tarball") or not new.get("tarball"):
            return None
        flags: list[str] = []
        for key, label in (("file_count", "file count"), ("unpacked_size", "unpacked size")):
            before, after = old.get(key), new.get(key)
            if before and after and after > max(before * 2, before + (50 if key == "file_count" else 500_000)):
                flags.append(f"{label} jumped from {before} to {after}")
        try:
            flags.extend(artifacts.compare_npm_tarballs(old["tarball"], new["tarball"]))
        except (artifacts.ArtifactError, urllib.error.URLError, TimeoutError) as error:
            return None if not flags else flags + [f"unverifiable: tarball comparison failed: {error}"]
        return flags


def _parse_bool(value: str) -> bool:
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select", help="choose a security-fix version")
    select.add_argument("--ecosystem", required=True, choices=["npm", "PyPI", "crates.io"])
    select.add_argument("--name", required=True)
    select.add_argument("--current", required=True)
    select.add_argument("--fixed", action="append", required=True)
    select.add_argument("--urgent-reachable-exposed", type=_parse_bool, required=True)
    check = sub.add_parser("check-routine", help="fail if changed deps/images are younger than 7 days")
    check.add_argument("--base", required=True, help="base git ref to diff against HEAD")
    check.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    if args.command == "select":
        decision = select_fix_version(
            args.ecosystem, args.name, args.current, args.fixed,
            urgent_reachable_exposed=args.urgent_reachable_exposed, now=datetime.now(timezone.utc),
        )
        print(json.dumps(asdict(decision), indent=2))
        return 0
    import release_age_routine as routine  # noqa: PLC0415 - imported lazily, only the check-routine command needs git helpers
    return routine.run(args.base, args.head)


if __name__ == "__main__":
    sys.exit(main())
