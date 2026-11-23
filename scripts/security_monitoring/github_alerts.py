"""GitHub Dependabot and secret scanning alerts in the daily security report.

Dependabot alerts are already an advisory source (sources/packages.py), but alerts whose
observation has a recorded not_affected verdict are suppressed and never reached the email.
This module lists every open GitHub alert once per (advisory, package), next to what our own
pipeline concluded, so the report accounts for all of them:

- Dependabot: severity, package, manifests where it is used (with scope), the fixed version, the
  GitHub alert numbers, and our state: open finding, not affected (with the triage reachability
  reason), or not yet triaged. Deduplicated against our scans through the observation identity
  ``<advisory>|<ecosystem>:<package>`` (CVE or GHSA alias).
- Secret scanning: type, GitHub validity, locations (paths only), and an operator classification
  from the private file ``<state_dir>/secret-scanning-verdicts.json``
  (``{"<alert number>": {"verdict": "false_positive"|"real_revoked"|"real_live", "reason": "..."}}``).
  The secret value is never read into the snapshot. An alert GitHub reports as ``active`` or
  classified ``real_live`` raises an immediate health incident (email at once).

The snapshot lives in the private state database (meta ``github_alerts:last``) and goes only to
the private email; nothing about individual alerts is written to the repository.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from security_monitoring.sources.fetch import FetchError, default_fetch
from security_monitoring.sources.packages import DEPENDABOT_ECOSYSTEMS, REPOSITORY

if TYPE_CHECKING:  # pragma: no cover
    from security_monitoring.dispatch import Dispatcher

META_KEY = "github_alerts:last"
VERDICTS_FILE = "secret-scanning-verdicts.json"
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "moderate": 2, "low": 3}
SECRET_VERDICTS = {"false_positive", "real_revoked", "real_live"}
Fetch = Callable[..., Any]


def _identity_candidates(alert: Mapping[str, Any]) -> list[str]:
    advisory = alert.get("security_advisory") or {}
    package = (alert.get("security_vulnerability") or {}).get("package") or (alert.get("dependency") or {}).get("package") or {}
    ecosystem = DEPENDABOT_ECOSYSTEMS.get(str(package.get("ecosystem", "")).lower(), str(package.get("ecosystem", "")))
    ids = [advisory.get("cve_id"), advisory.get("ghsa_id")]
    ids += [item.get("value") for item in advisory.get("identifiers") or () if isinstance(item, dict)]
    seen: list[str] = []
    for identifier in ids:
        key = f"{identifier}|{ecosystem}:{package.get('name')}"
        if identifier and key not in seen:
            seen.append(key)
    return seen


def _our_state(store: Any, candidates: list[str]) -> dict[str, Any]:
    """What our own pipeline concluded for this advisory and package."""
    open_keys = {item["incident_key"]: item for item in store.unresolved_incidents("advisory")}
    for identity in candidates:
        verdict = store.latest_verdict(identity)
        observation = store.observation(identity)
        if verdict is None and observation is None:
            continue
        body = (verdict or {}).get("verdict") or {}
        finding_open = any(key.startswith(f"advisory:{identity}:") for key in open_keys)
        if verdict is None:
            state = "seen by our scan, not yet triaged"
        elif verdict["outcome"] == "not_affected":
            state = f"not affected ({verdict.get('reason') or body.get('not_affected_reason') or 'no reason'})"
        else:
            state = verdict["outcome"].replace("_", " ")
        return {"identity": identity, "state": state, "finding_open": finding_open,
                "reachability": str(body.get("reachability") or ""), "triaged_at": (verdict or {}).get("recorded_at")}
    return {"identity": candidates[0] if candidates else "", "state": "not in our scans yet", "finding_open": False,
            "reachability": "", "triaged_at": None}


def dependabot_rows(alerts: list[Mapping[str, Any]], store: Any) -> list[dict[str, Any]]:
    """One row per (advisory, package), all manifests and alert numbers merged, most severe first."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for alert in alerts:
        advisory = alert.get("security_advisory") or {}
        vulnerability = alert.get("security_vulnerability") or {}
        dependency = alert.get("dependency") or {}
        package = vulnerability.get("package") or dependency.get("package") or {}
        advisory_id = str(advisory.get("cve_id") or advisory.get("ghsa_id") or "unknown")
        key = (advisory_id, f"{package.get('ecosystem')}:{package.get('name')}")
        row = groups.setdefault(key, {
            "advisory": advisory_id, "package": key[1], "severity": str(vulnerability.get("severity") or advisory.get("severity") or "unknown"),
            "fixed": (vulnerability.get("first_patched_version") or {}).get("identifier") or "none",
            "summary": str(advisory.get("summary") or ""), "numbers": [], "where": set(),
            "candidates": _identity_candidates(alert),
        })
        row["numbers"].append(int(alert.get("number") or 0))
        row["where"].add(f"{dependency.get('manifest_path') or '?'} ({dependency.get('scope') or 'unknown scope'})")
    rows = []
    for row in groups.values():
        ours = _our_state(store, row.pop("candidates"))
        rows.append({**row, **ours, "numbers": sorted(row["numbers"]), "where": sorted(row["where"])})
    return sorted(rows, key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["package"], item["advisory"]))


def _load_verdicts(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must map alert numbers to {{verdict, reason}}")
    for number, entry in data.items():
        if not isinstance(entry, dict) or entry.get("verdict") not in SECRET_VERDICTS:
            raise ValueError(f"{path}: alert {number} needs verdict in {sorted(SECRET_VERDICTS)}")
    return data


def secret_rows(alerts: list[Mapping[str, Any]], locations: Callable[[int], list[str]],
                verdicts: Mapping[str, Mapping[str, str]]) -> list[dict[str, Any]]:
    """Secret alert metadata only; the alert's ``secret`` field is never copied."""
    rows = []
    for alert in alerts:
        number = int(alert.get("number") or 0)
        verdict = verdicts.get(str(number)) or {}
        rows.append({
            "number": number, "type": str(alert.get("secret_type_display_name") or alert.get("secret_type") or "unknown"),
            "validity": str(alert.get("validity") or "unknown"), "created_at": str(alert.get("created_at") or ""),
            "publicly_leaked": bool(alert.get("publicly_leaked")), "locations": locations(number),
            "verdict": verdict.get("verdict", "unclassified"), "reason": verdict.get("reason", ""),
        })
    return sorted(rows, key=lambda item: item["number"])


def _locations(fetch: Fetch) -> Callable[[int], list[str]]:
    def lookup(number: int) -> list[str]:
        items = fetch(f"gh:repos/{REPOSITORY}/secret-scanning/alerts/{number}/locations?per_page=100", {"paginate": True})
        paths = set()
        for item in items if isinstance(items, list) else ():
            details = item.get("details") or {}
            paths.add(f"{details.get('path') or item.get('type')}:{details.get('start_line') or ''}".rstrip(":"))
        return sorted(paths)
    return lookup


def collect(store: Any, state_dir: Path, fetch: Fetch = default_fetch) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"dependabot": [], "secrets": [], "errors": []}
    try:
        alerts = fetch(f"gh:repos/{REPOSITORY}/dependabot/alerts?state=open&per_page=100", {"paginate": True})
        snapshot["dependabot_total"] = len(alerts)
        snapshot["dependabot"] = dependabot_rows(alerts, store)
    except FetchError as error:
        snapshot["errors"].append(f"Dependabot alerts unavailable ({error})")
    try:
        secrets = fetch(f"gh:repos/{REPOSITORY}/secret-scanning/alerts?state=open&per_page=100", {"paginate": True})
        snapshot["secrets"] = secret_rows(secrets, _locations(fetch), _load_verdicts(state_dir / VERDICTS_FILE))
    except FetchError as error:
        snapshot["errors"].append(f"secret scanning alerts unavailable ({error})")
    return snapshot


def run(dispatcher: "Dispatcher", fetch: Fetch = default_fetch) -> dict[str, Any]:
    """Refresh the snapshot; a possibly live secret raises an immediate health incident."""
    settings, store = dispatcher.settings, dispatcher.store
    snapshot = collect(store, settings.state_dir, fetch)
    snapshot["at"] = dispatcher.now.isoformat()
    if settings.dry_run:
        dispatcher.plan(f"would record {len(snapshot['dependabot'])} Dependabot and {len(snapshot['secrets'])} secret scanning rows")
        return snapshot
    store.set_meta(META_KEY, json.dumps(snapshot, sort_keys=True))
    for row in snapshot["secrets"]:
        if row["validity"] == "active" or row["verdict"] == "real_live":
            dispatcher.raise_health(
                f"secret_alert:{row['number']}", "secret_alert_active",
                f"GitHub secret scanning alert {row['number']} ({row['type']}) may be a live secret: "
                f"validity {row['validity']}, classification {row['verdict']}.",
                checklist=["Rotate the secret at its provider now", "Close the GitHub alert as revoked",
                           f"Record the verdict in {VERDICTS_FILE}"])
    return snapshot


def last_snapshot(store: Any) -> Mapping[str, Any] | None:
    raw = store.get_meta(META_KEY)
    return json.loads(raw) if raw else None


def digest_lines(snapshot: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Email lines: every Dependabot alert group, then every secret scanning alert."""
    dependabot, secrets = list(snapshot.get("dependabot") or ()), list(snapshot.get("secrets") or ())
    counts: dict[str, int] = defaultdict(int)
    for row in dependabot:
        counts[row["severity"]] += len(row["numbers"])
    summary = ", ".join(f"{name} {counts[name]}" for name in sorted(counts, key=lambda s: SEVERITY_ORDER.get(s, 9)))
    lines = [("GITHUB ALERTS", f"Dependabot {snapshot.get('dependabot_total', 0)} open ({summary or 'none'}) in {len(dependabot)} "
                               f"advisories; secret scanning {len(secrets)} open; checked {str(snapshot.get('at', '?'))[:16]}")]
    for row in dependabot:
        reach = f" Why: {row['reachability']}" if row.get("reachability") else ""
        lines.append(("Dependabot", f"[{row['severity'].upper()}] {row['package']} {row['advisory']} (fixed in {row['fixed']}; "
                                    f"alerts {', '.join(f'#{n}' for n in row['numbers'])}). Used in: {'; '.join(row['where'])}. "
                                    f"Ours: {row['state']}{' (open finding above)' if row.get('finding_open') else ''}.{reach}"))
    for row in secrets:
        lines.append(("Secret alert", f"#{row['number']} {row['type']}, GitHub validity {row['validity']}: "
                                      f"{row['verdict'].replace('_', ' ')}{' - ' + row['reason'].rstrip('.') if row['reason'] else ''}. "
                                      f"Found in {len(row['locations'])} place(s): {', '.join(row['locations'][:4])}"))
    for text in snapshot.get("errors") or ():
        lines.append(("Not checked", text))
    return lines
