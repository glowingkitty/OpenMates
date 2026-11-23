"""Daily running-image report (images.running-digests, owner decision 21 Nov, 6a).

Scans the image digests that actually run (image_scan) and reads each image's
runtimes directly, then:
- opens an urgent advisory incident (its own email) for every finding whose CVE
  is in the CISA known-exploited catalog,
- opens a fix-soon incident when an image's Node runtime is older than the
  newest Node security release of the same major line (image scanners do not
  package Node, so they miss it),
- stores a per-image summary that the daily email shows under "Running images",
  with every image or server that could not be checked as incomplete coverage.
Incidents of this report resolve once a complete scan no longer shows them.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from security_monitoring import image_scan, release_age

if TYPE_CHECKING:  # pragma: no cover - typing only
    from security_monitoring.dispatch import Dispatcher

META_KEY = "image_scan:last"
INCIDENT_PREFIX = "advisory:image:"
NODE_INDEX_URL = "https://nodejs.org/dist/index.json"
ROLES = ("dev", "core", "upload", "preview")


def node_security_gap(version: str, index: Iterable[Mapping[str, Any]]) -> str | None:
    """Newest Node security release on `version`'s major line that is newer than it, if any."""
    current = release_age.version_key(version)
    if not current[0]:
        return None
    newer = [str(item["version"]).lstrip("v") for item in index
             if item.get("security") and release_age.version_key(str(item["version"]))[0][:1] == current[0][:1]
             and release_age.version_key(str(item["version"])) > current]
    return max(newer, key=release_age.version_key) if newer else None


def default_node_index() -> list[dict[str, Any]]:
    return list(release_age._fetch_json(NODE_INDEX_URL) or [])


def _short(digest: str) -> str:
    return digest.split(":", 1)[-1][:12]


def _advisory_details(advisory: str, package: str, version: str, environments: Iterable[str], outcome: str, evidence: str, action: str) -> dict[str, Any]:
    envs = sorted(set(environments))
    return {
        "advisory_ids": [advisory], "assets": [{"name": package, "version": version, "environments": envs}],
        "environments": envs, "outcome": outcome, "dispatch_reason": "running image scan",
        "evidence_summary": evidence, "reachability": "present in a running image", "exploitability": "see advisory",
        "blast_radius": "the containers running this image", "host_roles": [], "manual_actions": [action],
        "automatic_actions": {"summary": "no automatic fix possible (image rebuild or base image update)"},
    }


def build_report(images: list[Any], gaps: list[str], results: list[Any], runtimes: list[Any],
                 kev: set[str], node_index: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """(summary for the daily email, {incident key: (outcome, details)}) from one scan."""
    incidents: dict[str, dict[str, Any]] = {}
    exploited: dict[tuple[str, str], dict[str, set[str]]] = {}
    lines: list[str] = []
    incomplete = list(gaps)
    for result in sorted(results, key=lambda r: r.image):
        if result.incomplete:
            incomplete.append(f"{result.image}: {result.incomplete}")
            continue
        counts = {sev: sum(1 for f in result.findings if f.severity == sev) for sev in ("critical", "high")}
        fixable = sum(1 for f in result.findings if f.severity in ("critical", "high") and f.fixed_version)
        lines.append(f"{result.image}@{_short(result.digest)} ({', '.join(result.environments)}): "
                     f"{counts['critical']} critical, {counts['high']} high, {fixable} of them fixable")
        for finding in result.findings:
            if finding.vuln_id.upper() not in kev:
                continue
            where = f" at {finding.pkg_path}" if finding.pkg_path else ""
            entry = exploited.setdefault((finding.vuln_id, finding.package), {"versions": set(), "fixed": set(), "images": set(), "envs": set()})
            entry["versions"].add(finding.installed_version)
            entry["fixed"].update([finding.fixed_version] if finding.fixed_version else [])
            entry["images"].add(f"{result.image}@{_short(result.digest)}{where}")
            entry["envs"].update(result.environments)
    for (vuln_id, package), entry in sorted(exploited.items()):
        images_text = "; ".join(sorted(entry["images"])[:6]) + (f" and {len(entry['images']) - 6} more" if len(entry["images"]) > 6 else "")
        fixed = ", ".join(sorted(entry["fixed"])) or "no fixed version yet"
        incidents[f"{INCIDENT_PREFIX}{vuln_id}:{package}"] = {"outcome": "urgent", "details": _advisory_details(
            vuln_id, package, ", ".join(sorted(entry["versions"])), entry["envs"], "urgent",
            f"Actively exploited (CISA KEV) and present in {len(entry['images'])} running image(s): {images_text}.",
            f"Rebuild or update the listed images with {package} {fixed} and redeploy them")}
    runtime_lines: list[str] = []
    for runtime in runtimes:
        if runtime.incomplete:
            incomplete.append(f"{runtime.image} runtimes: {runtime.incomplete}")
            continue
        found = {asset.name: asset.version for asset in runtime.assets}
        if found:
            runtime_lines.append(f"{runtime.image}: " + ", ".join(f"{k} {v}" for k, v in sorted(found.items())))
        if "node" in found and (fix := node_security_gap(found["node"], node_index)):
            key = f"{INCIDENT_PREFIX}node-{fix}:{runtime.image}:{_short(runtime.digest)}"
            incidents[key] = {"outcome": "affected_fix_soon", "details": _advisory_details(
                f"node-security-release-{fix}", "node", found["node"], runtime.environments, "affected_fix_soon",
                f"Node {found['node']} in {runtime.image} is older than Node security release {fix}.",
                f"Update the Node base image of {runtime.image} to {fix} or newer")}
    summary = {"images": len(images), "lines": lines, "runtimes": sorted(set(runtime_lines)), "incomplete": incomplete,
               "kev_findings": sum(1 for item in incidents.values() if item["outcome"] == "urgent")}
    return summary, incidents


def run_report(dispatcher: "Dispatcher", *, runner: image_scan.Runner = image_scan.subprocess_runner,
               kev: Callable[[], set[str]] = release_age.kev_cves,
               node_index: Callable[[], list[dict[str, Any]]] = default_node_index) -> dict[str, Any]:
    settings, store, now = dispatcher.settings, dispatcher.store, dispatcher.now
    images, gaps = image_scan.running_images(runner, hosts_dir=settings.hosts_dir, roles=ROLES)
    results = image_scan.scan_all(images, runner)
    runtimes = [image_scan.runtime_versions(image, runner) for image in images]
    try:
        catalog = kev()
    except release_age.RegistryLookupError as error:
        catalog, gaps = set(), [*gaps, f"CISA KEV catalog unavailable ({error})"]
    try:
        index = node_index()
    except release_age.RegistryLookupError as error:
        index, gaps = [], [*gaps, f"Node release index unavailable ({error})"]
    summary, incidents = build_report(images, gaps, results, runtimes, catalog, index)
    summary["at"] = now.isoformat()
    if settings.dry_run:
        dispatcher.plan(f"would record {len(incidents)} running-image incident(s) and the image summary")
        return summary
    store.set_meta(META_KEY, json.dumps(summary, sort_keys=True))
    for key, item in incidents.items():
        incident_id, _created = store.open_incident("advisory", key, item["outcome"], item["details"], now)
        dispatcher._notify(incident_id)
    if not summary["incomplete"]:
        store.resolve_incidents_with_prefix(INCIDENT_PREFIX, set(incidents), now)
    return summary


def last_report(store: Any) -> Mapping[str, Any] | None:
    raw = store.get_meta(META_KEY)
    return json.loads(raw) if raw else None
