"""Structured package advisory sources: OSV, Dependabot and upstream GitHub advisories.

These describe current state (every advisory affecting what we have now), so
they are not limited to the `since` window; deduplication happens downstream
through aliases and dispatch state. OSV querybatch results are exact-version
confirmations, including MAL- malicious-package records. See
security-monitoring.sources.hourly-deterministic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import re
from typing import Any, Callable, Iterable, Mapping

from security_monitoring.models import AdvisoryItem, Inventory
from security_monitoring.sources.fetch import FetchError

Fetch = Callable[[str, "dict[str, Any] | None"], Any]

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns"
OSV_BATCH_SIZE = 1000
OSV_MAX_DETAILS = 600
OSV_ECOSYSTEMS = {"npm", "PyPI", "crates.io", "SwiftURL"}
REPOSITORY = "glowingkitty/OpenMates"
DEPENDABOT_ECOSYSTEMS = {"pip": "PyPI", "rust": "crates.io", "actions": "GitHub Actions", "swift": "SwiftURL",
                         "npm": "npm", "docker": "docker", "go": "Go"}
# Upstream repositories whose own GitHub security advisories we follow, and how
# their package names map onto inventory assets ("*" maps every package).
UPSTREAM_REPOSITORIES: dict[str, dict[str, tuple[str, str]]] = {
    "anthropics/claude-code": {"@anthropic-ai/claude-code": ("tool", "claude")},
    "openai/codex": {"@openai/codex": ("tool", "codex"), "codex": ("tool", "codex"), "codex-cli": ("tool", "codex")},
    # Only the `directus` package shares the image's version line (@directus/* packages version separately).
    "directus/directus": {"directus": ("docker", "directus/directus")},
    "caddyserver/caddy": {"github.com/caddyserver/caddy/v2": ("docker", "caddy"),
                          "github.com/caddyserver/caddy": ("docker", "caddy")},
    "dragonflydb/dragonfly": {"*": ("docker", "docker.dragonflydb.io/dragonflydb/dragonfly")},
}
UNSUPPORTED_UPSTREAM = {"hashicorp/vault": "no_github_security_advisories"}
_VERSION_TOKEN = re.compile(r"\b\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?")
_SEVERITY = {"critical": "critical", "high": "high", "moderate": "medium", "medium": "medium", "low": "low"}


def normalize_severity(value: object) -> str:
    return _SEVERITY.get(str(value or "").strip().lower(), "unknown")


def _osv_severity(record: Mapping[str, Any]) -> str:
    if str(record.get("id", "")).startswith("MAL-"):
        return "critical"
    severity = normalize_severity((record.get("database_specific") or {}).get("severity"))
    if severity != "unknown":
        return severity
    for affected in record.get("affected") or ():
        if isinstance(affected, dict):
            severity = normalize_severity((affected.get("ecosystem_specific") or {}).get("severity"))
            if severity != "unknown":
                return severity
    return "unknown"


def _osv_queries(inventory: Inventory) -> list[tuple[str, str, str]]:
    queries = {(asset.ecosystem, asset.name, asset.version) for asset in inventory.assets
               if asset.usage == "used" and asset.kind == "package" and asset.version and asset.ecosystem in OSV_ECOSYSTEMS}
    return sorted(queries)  # type: ignore[arg-type]  # version filtered non-empty above


def _osv_item(vuln_id: str, record: Mapping[str, Any] | None, hits: Iterable[tuple[str, str, str]],
              modified: str | None) -> AdvisoryItem:
    exact = tuple({"ecosystem": ecosystem, "name": name, "versions": [version], "origin": "osv_query"}
                  for ecosystem, name, version in sorted(set(hits)))
    if record is None:
        return AdvisoryItem(source="osv", advisory_id=vuln_id, aliases=(), title=vuln_id, severity="unknown",  # type: ignore[arg-type]  # literal
                            published_at=None, modified_at=modified, affected=exact,
                            url=f"https://osv.dev/vulnerability/{vuln_id}")
    affected = []
    for entry in record.get("affected") or ():
        package = entry.get("package") if isinstance(entry, dict) else None
        if isinstance(package, dict) and package.get("name") and package.get("ecosystem"):
            affected.append({"ecosystem": package["ecosystem"], "name": package["name"],
                             "ranges": entry.get("ranges") or [], "versions": entry.get("versions") or []})
    aliases = tuple(sorted({str(alias) for alias in [*(record.get("aliases") or ()), *(record.get("upstream") or ())]}))
    title = str(record.get("summary") or str(record.get("details") or vuln_id)[:160]).strip()
    return AdvisoryItem(
        source="osv", advisory_id=vuln_id, aliases=aliases, title=title, severity=_osv_severity(record),  # type: ignore[arg-type]  # literal
        published_at=record.get("published"), modified_at=record.get("modified") or modified,
        affected=exact + tuple(affected), withdrawn=bool(record.get("withdrawn")),
        url=f"https://osv.dev/vulnerability/{vuln_id}",
    )


def collect_osv(inventory: Inventory, fetch: Fetch) -> tuple[list[AdvisoryItem], str | None]:
    """Query OSV for every versioned package asset; returns (items, partial-error-code)."""
    queries = _osv_queries(inventory)
    hits: dict[str, list[tuple[str, str, str]]] = {}
    modified: dict[str, str | None] = {}
    for start in range(0, len(queries), OSV_BATCH_SIZE):
        batch = queries[start:start + OSV_BATCH_SIZE]
        body = {"queries": [{"package": {"ecosystem": eco, "name": name}, "version": version} for eco, name, version in batch]}
        response = fetch(OSV_BATCH_URL, {"method": "POST", "json": body, "timeout": 90})
        results = response.get("results") if isinstance(response, dict) else None
        if not isinstance(results, list) or len(results) != len(batch):
            raise FetchError("malformed")
        for query, result in zip(batch, results):
            for vuln in (result or {}).get("vulns") or ():
                if isinstance(vuln, dict) and isinstance(vuln.get("id"), str):
                    hits.setdefault(vuln["id"], []).append(query)
                    modified[vuln["id"]] = vuln.get("modified")
    ids = sorted(hits)
    partial = "detail_limit_exceeded" if len(ids) > OSV_MAX_DETAILS else None

    def detail(vuln_id: str) -> Mapping[str, Any] | None:
        try:
            record = fetch(f"{OSV_VULN_URL}/{vuln_id}", {"timeout": 30})
        except FetchError:
            return None
        return record if isinstance(record, dict) else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = dict(zip(ids[:OSV_MAX_DETAILS], pool.map(detail, ids[:OSV_MAX_DETAILS])))
    if any(record is None for record in records.values()):
        partial = partial or "detail_fetch_failed"
    items = [_osv_item(vuln_id, records.get(vuln_id), hits[vuln_id], modified.get(vuln_id)) for vuln_id in ids]
    return items, partial


def _advisory_aliases(advisory: Mapping[str, Any]) -> tuple[str, ...]:
    aliases = {str(advisory.get(key)) for key in ("ghsa_id", "cve_id") if advisory.get(key)}
    for identifier in advisory.get("identifiers") or ():
        if isinstance(identifier, dict) and identifier.get("value"):
            aliases.add(str(identifier["value"]))
    return tuple(sorted(aliases))


def collect_dependabot(fetch: Fetch) -> list[AdvisoryItem]:
    alerts = fetch(f"gh:repos/{REPOSITORY}/dependabot/alerts?state=open&per_page=100", {"paginate": True})
    if not isinstance(alerts, list):
        raise FetchError("malformed")
    items = []
    for alert in alerts:
        advisory = alert.get("security_advisory") or {}
        vulnerability = alert.get("security_vulnerability") or {}
        package = vulnerability.get("package") or (alert.get("dependency") or {}).get("package") or {}
        identifier = advisory.get("ghsa_id") or advisory.get("cve_id")
        if not identifier or not package.get("name"):
            raise FetchError("malformed")
        ecosystem = DEPENDABOT_ECOSYSTEMS.get(str(package.get("ecosystem", "")).lower(), str(package.get("ecosystem", "")))
        fixed = (vulnerability.get("first_patched_version") or {}).get("identifier")
        items.append(AdvisoryItem(
            source="dependabot", advisory_id=str(identifier), aliases=_advisory_aliases(advisory),
            title=str(advisory.get("summary") or identifier),
            severity=normalize_severity(vulnerability.get("severity") or advisory.get("severity")),  # type: ignore[arg-type]  # literal
            published_at=advisory.get("published_at"), modified_at=advisory.get("updated_at"),
            affected=({"ecosystem": ecosystem, "name": package["name"],
                       "range_expr": vulnerability.get("vulnerable_version_range") or "",
                       "fixed": [fixed] if fixed else []},),
            withdrawn=bool(advisory.get("withdrawn_at")),
            url=f"https://github.com/advisories/{advisory.get('ghsa_id')}" if advisory.get("ghsa_id") else None,
        ))
    return items


def collect_upstream(repository: str, fetch: Fetch) -> list[AdvisoryItem]:
    mapping = UPSTREAM_REPOSITORIES[repository]
    advisories = fetch(f"gh:repos/{repository}/security-advisories?per_page=100", {"paginate": True})
    if not isinstance(advisories, list):
        raise FetchError("malformed")
    items = []
    for advisory in advisories:
        if not isinstance(advisory, dict) or not advisory.get("ghsa_id"):
            raise FetchError("malformed")
        affected: list[dict[str, Any]] = []
        for vulnerability in advisory.get("vulnerabilities") or ():
            package = (vulnerability or {}).get("package") or {}
            name = str(package.get("name") or "")
            expression = str(vulnerability.get("vulnerable_version_range") or "")
            patched = _VERSION_TOKEN.findall(str(vulnerability.get("patched_versions") or ""))
            if name:
                affected.append({"ecosystem": str(package.get("ecosystem") or "other"), "name": name,
                                 "range_expr": expression, "patched": patched})
            target = mapping.get(name) or mapping.get("*")
            if target:
                affected.append({"ecosystem": target[0], "name": target[1], "range_expr": expression, "patched": patched})
        items.append(AdvisoryItem(
            source=f"upstream:{repository}", advisory_id=str(advisory["ghsa_id"]), aliases=_advisory_aliases(advisory),
            title=str(advisory.get("summary") or advisory["ghsa_id"]),
            severity=normalize_severity(advisory.get("severity")),  # type: ignore[arg-type]  # literal
            published_at=advisory.get("published_at"), modified_at=advisory.get("updated_at"),
            affected=tuple(affected), withdrawn=bool(advisory.get("withdrawn_at")),
            url=advisory.get("html_url"),
        ))
    return items
