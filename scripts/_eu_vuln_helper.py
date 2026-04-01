#!/usr/bin/env python3
"""
scripts/_eu_vuln_helper.py

Python helper for check-eu-vulns-daily.sh (OPE-224).

Queries EU and international vulnerability databases (OSV, NVD) to detect
security issues in our npm and pip dependencies that GitHub Dependabot may
miss. Cross-references findings against the Dependabot tracking file to
avoid duplicate work.

Data sources:
    - OSV (api.osv.dev) — primary. Aggregates GitHub Advisories, PyPI, npm,
      Debian, Alpine, and EU-contributed advisories. Free, no auth, batch API.
    - NVD (services.nvd.nist.gov) — secondary enrichment. CVSS scores and
      detailed references. Free API key optional (higher rate limits).
    - EUVD (euvd.enisa.europa.eu) — EU Vulnerability Database under NIS2
      Directive. No public API yet as of 2026-03 — noted for future.

Commands:
    check-vulns     Main workflow: scan deps, query sources, dispatch if needed

Environment variables (set by the shell script):
    TRACKING_FILE_PATH          — path to eu-vuln-processed.json
    DEPENDABOT_TRACKING_PATH    — path to dependabot-processed.json (for dedup)
    PROJECT_ROOT                — absolute path to the repo root
    REDISPATCH_AFTER_DAYS       — days before re-dispatching unresolved vuln
    DRY_RUN                     — "true" to skip claude invocation
    SUMMARY_ONLY                — "true" to output JSON summary and exit
    PROMPT_TEMPLATE_PATH        — path to prompts/eu-vuln-analysis.md
    TODAY_DATE                  — current date as YYYY-MM-DD
    NVD_API_KEY                 — optional free NVD API key for higher rate limits

Tracking file format (scripts/eu-vuln-processed.json):
{
  "last_run": "2026-03-31T05:00:00Z",
  "processed": [
    {
      "vuln_id": "GHSA-xxxx-yyyy-zzzz",
      "aliases": ["CVE-2026-12345"],
      "severity": "high",
      "package": "lodash",
      "ecosystem": "npm",
      "summary": "Prototype pollution in lodash",
      "fixed_version": "4.17.22",
      "source": "osv",
      "first_seen_at": "2026-03-31T05:00:00Z",
      "last_dispatched_at": "2026-03-31T05:00:00Z",
      "re_dispatch_count": 0,
      "resolved_via_commit": null,
      "user_disclosure_needed": false
    }
  ]
}
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _claude_utils import run_claude_session


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# OSV API endpoints (Google — aggregates EU + international sources)
OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns"

# NVD API endpoint (NIST — CVE detail enrichment)
NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# Severity levels to process (skip "low" and "unknown")
PROCESS_SEVERITIES = {"critical", "high", "medium"}

# Severity sort order for prompt grouping
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}

# Max batch size for OSV (API limit is 1000)
OSV_BATCH_SIZE = 1000

# NVD rate limit: 5 req/30s without key, 50 req/30s with key
NVD_RATE_LIMIT_DELAY = 6.5  # seconds between requests without API key
NVD_RATE_LIMIT_DELAY_WITH_KEY = 0.7

# Max NVD enrichment requests per run (avoid hitting rate limits)
MAX_NVD_ENRICHMENTS = 20

# Packages that affect user data / require disclosure if compromised
# (encryption, auth, data storage, payment)
USER_DISCLOSURE_PACKAGES = {
    "tweetnacl", "cryptography", "pynacl", "argon2-cffi",
    "stripe", "@stripe/stripe-js", "polar-sdk", "@polar-sh/checkout",
    "@revolut/checkout", "webauthn", "pyotp", "dompurify",
    "httpx", "aiohttp", "redis", "boto3",
}

# Dependency file locations relative to project root
DEPENDENCY_FILES = {
    "npm": [
        "frontend/packages/ui/package.json",
        "frontend/apps/web_app/package.json",
    ],
    "PyPI": [
        "backend/core/api/requirements.txt",
        "backend/apps/pdf/requirements.txt",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json_file(path: str, default: Any) -> Any:
    """Load a JSON file, returning default if missing or corrupt."""
    if not os.path.isfile(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"[eu-vulns] WARNING: could not load {path}: {e}", file=sys.stderr)
        return default


def _save_json_file(path: str, data: Any) -> None:
    """Save JSON atomically via temp file."""
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def _http_request(
    url: str,
    method: str = "GET",
    data: Optional[bytes] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> Optional[Dict]:
    """Make an HTTP request and return parsed JSON, or None on failure."""
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[eu-vulns] HTTP {e.code} from {url}: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[eu-vulns] Request failed for {url}: {e}", file=sys.stderr)
        return None


def _check_vuln_in_git(vuln_id: str, project_root: str) -> Optional[str]:
    """Search git log for a commit referencing the vulnerability ID."""
    try:
        result = subprocess.run(
            ["git", "-C", project_root, "log", "--all", "--oneline", f"--grep={vuln_id}"],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if output:
            return output.splitlines()[0].split()[0]
        return None
    except Exception as e:
        print(f"[eu-vulns] WARNING: git search failed for {vuln_id}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Dependency parsing
# ---------------------------------------------------------------------------

def _parse_package_json(filepath: str) -> List[Dict[str, str]]:
    """
    Parse a package.json and return list of {name, version, ecosystem, source_file}.
    Strips semver range prefixes (^, ~, >=) to get the base version.
    """
    deps = []
    try:
        with open(filepath) as f:
            pkg = json.load(f)
    except Exception as e:
        print(f"[eu-vulns] WARNING: could not parse {filepath}: {e}", file=sys.stderr)
        return deps

    for dep_type in ("dependencies", "devDependencies"):
        for name, version_spec in pkg.get(dep_type, {}).items():
            # Skip workspace references
            if version_spec.startswith("workspace:"):
                continue
            # Strip range prefixes to get base version
            version = re.sub(r"^[\^~>=<]+", "", version_spec).strip()
            if version:
                deps.append({
                    "name": name,
                    "version": version,
                    "ecosystem": "npm",
                    "source_file": filepath,
                })

    return deps


def _parse_requirements_txt(filepath: str) -> List[Dict[str, str]]:
    """
    Parse a requirements.txt and return list of {name, version, ecosystem, source_file}.
    Handles pinned (==) and minimum (>=) version specs.
    """
    deps = []
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[eu-vulns] WARNING: could not parse {filepath}: {e}", file=sys.stderr)
        return deps

    for line in lines:
        line = line.strip()
        # Skip comments, empty lines, and flags
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        # Parse name==version or name>=version patterns
        match = re.match(r"^([a-zA-Z0-9_.-]+)\[?[^\]]*\]?[=~<>!]+(.+)$", line)
        if match:
            name = match.group(1).strip()
            version = match.group(2).strip().split(",")[0].strip()
            deps.append({
                "name": name,
                "version": version,
                "ecosystem": "PyPI",
                "source_file": filepath,
            })

    return deps


def _collect_all_dependencies(project_root: str) -> List[Dict[str, str]]:
    """Collect all dependencies from all known dependency files."""
    all_deps = []

    for ecosystem, files in DEPENDENCY_FILES.items():
        for rel_path in files:
            filepath = os.path.join(project_root, rel_path)
            if not os.path.isfile(filepath):
                print(f"[eu-vulns] NOTE: {rel_path} not found, skipping.", file=sys.stderr)
                continue

            if ecosystem == "npm":
                deps = _parse_package_json(filepath)
            elif ecosystem == "PyPI":
                deps = _parse_requirements_txt(filepath)
            else:
                continue

            all_deps.extend(deps)
            print(f"[eu-vulns] Parsed {len(deps)} deps from {rel_path}")

    # Deduplicate by (name, ecosystem) — keep the first occurrence
    seen = set()
    unique_deps = []
    for dep in all_deps:
        key = (dep["name"].lower(), dep["ecosystem"])
        if key not in seen:
            seen.add(key)
            unique_deps.append(dep)

    print(f"[eu-vulns] Total unique dependencies: {len(unique_deps)} "
          f"(npm: {sum(1 for d in unique_deps if d['ecosystem'] == 'npm')}, "
          f"PyPI: {sum(1 for d in unique_deps if d['ecosystem'] == 'PyPI')})")

    return unique_deps


# ---------------------------------------------------------------------------
# OSV API
# ---------------------------------------------------------------------------

def _query_osv_batch(deps: List[Dict[str, str]]) -> List[Dict]:
    """
    Query the OSV batch API for all dependencies.
    Returns list of (dep, vulns) pairs where vulns is non-empty.
    """
    results = []

    # Build batch queries
    queries = []
    for dep in deps:
        queries.append({
            "package": {
                "name": dep["name"],
                "ecosystem": dep["ecosystem"],
            },
            "version": dep["version"],
        })

    # Split into batches of OSV_BATCH_SIZE
    for batch_start in range(0, len(queries), OSV_BATCH_SIZE):
        batch = queries[batch_start:batch_start + OSV_BATCH_SIZE]
        batch_deps = deps[batch_start:batch_start + OSV_BATCH_SIZE]

        print(f"[eu-vulns] Querying OSV batch API ({len(batch)} packages)...")
        payload = json.dumps({"queries": batch}).encode("utf-8")
        response = _http_request(OSV_BATCH_URL, method="POST", data=payload, timeout=60)

        if not response:
            print("[eu-vulns] ERROR: OSV batch query failed.", file=sys.stderr)
            continue

        batch_results = response.get("results", [])
        for i, result in enumerate(batch_results):
            vulns = result.get("vulns", [])
            if vulns and i < len(batch_deps):
                results.append((batch_deps[i], vulns))

    vuln_count = sum(len(vulns) for _, vulns in results)
    pkg_count = len(results)
    print(f"[eu-vulns] OSV: {vuln_count} vulnerability(ies) across {pkg_count} package(s)")

    return results


def _fetch_osv_vuln_detail(vuln_id: str) -> Optional[Dict]:
    """Fetch full vulnerability details from OSV."""
    url = f"{OSV_VULN_URL}/{vuln_id}"
    return _http_request(url, timeout=15)


# ---------------------------------------------------------------------------
# NVD API (enrichment)
# ---------------------------------------------------------------------------

def _enrich_with_nvd(cve_id: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """
    Fetch CVE details from NVD for CVSS score enrichment.
    Returns dict with cvss_score, cvss_vector, references, or None on failure.
    """
    url = f"{NVD_CVE_URL}?cveId={cve_id}"
    headers = {}
    if api_key:
        headers["apiKey"] = api_key

    response = _http_request(url, headers=headers, timeout=15)
    if not response:
        return None

    vulns = response.get("vulnerabilities", [])
    if not vulns:
        return None

    cve_data = vulns[0].get("cve", {})
    metrics = cve_data.get("metrics", {})

    # Try CVSS v3.1 first, then v3.0
    cvss_data = None
    for key in ("cvssMetricV31", "cvssMetricV30"):
        if key in metrics and metrics[key]:
            cvss_data = metrics[key][0].get("cvssData", {})
            break

    result = {
        "cvss_score": None,
        "cvss_vector": None,
        "references": [],
    }

    if cvss_data:
        result["cvss_score"] = cvss_data.get("baseScore")
        result["cvss_vector"] = cvss_data.get("vectorString")

    refs = cve_data.get("references", [])
    result["references"] = [r.get("url", "") for r in refs[:5]]

    return result


# ---------------------------------------------------------------------------
# Dependabot deduplication
# ---------------------------------------------------------------------------

def _load_dependabot_ghsa_ids(dependabot_tracking_path: str) -> set:
    """Load GHSA IDs already tracked by Dependabot to avoid duplicate work."""
    data = _load_json_file(dependabot_tracking_path, {"processed": []})
    ghsa_ids = set()
    for entry in data.get("processed", []):
        ghsa_id = entry.get("ghsa_id", "")
        if ghsa_id:
            ghsa_ids.add(ghsa_id)
    return ghsa_ids


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _extract_severity(vuln: Dict) -> str:
    """Extract severity from an OSV vulnerability record."""
    # Check database_specific severity first
    db_specific = vuln.get("database_specific", {})
    if db_specific.get("severity"):
        return db_specific["severity"].lower()

    # Check CVSS severity in severity array
    for sev in vuln.get("severity", []):
        score_str = sev.get("score", "")
        # Parse CVSS vector string for base score
        if "CVSS:" in score_str:
            # Extract base score from ecosystem_specific or approximate from vector
            pass

    # Check affected[].ecosystem_specific
    for affected in vuln.get("affected", []):
        eco_specific = affected.get("ecosystem_specific", {})
        if eco_specific.get("severity"):
            return eco_specific["severity"].lower()

    # Fallback: derive from CVSS score in severity array
    for sev in vuln.get("severity", []):
        score_str = sev.get("score", "")
        # Try to extract base score from CVSS vector
        match = re.search(r"CVSS:\d+\.\d+/AV:\w+/.*", score_str)
        if match:
            # Use the score type as a rough indicator
            sev_type = sev.get("type", "")
            if sev_type == "CVSS_V3":
                # Try to get numeric score from database_specific
                pass

    return "unknown"


def _extract_fixed_version(vuln: Dict, package_name: str, ecosystem: str) -> Optional[str]:
    """Extract the first patched version from an OSV vulnerability record."""
    for affected in vuln.get("affected", []):
        pkg = affected.get("package", {})
        if (pkg.get("name", "").lower() == package_name.lower()
                and pkg.get("ecosystem", "").lower() == ecosystem.lower()):
            for rng in affected.get("ranges", []):
                for event in rng.get("events", []):
                    if "fixed" in event:
                        return event["fixed"]
    return None


def _process_osv_results(
    osv_results: List[Tuple[Dict, List[Dict]]],
    dependabot_ghsa_ids: set,
    nvd_api_key: Optional[str],
) -> List[Dict]:
    """
    Process OSV results into a flat list of actionable vulnerability findings.
    Deduplicates against Dependabot, enriches with NVD when possible.
    """
    findings = []
    seen_vuln_ids = set()
    nvd_enrichment_count = 0

    nvd_delay = NVD_RATE_LIMIT_DELAY_WITH_KEY if nvd_api_key else NVD_RATE_LIMIT_DELAY

    for dep, vulns in osv_results:
        for vuln in vulns:
            vuln_id = vuln.get("id", "")
            if not vuln_id or vuln_id in seen_vuln_ids:
                continue
            seen_vuln_ids.add(vuln_id)

            # Get aliases (CVE IDs, other GHSA IDs)
            aliases = vuln.get("aliases", [])

            # Skip if already tracked by Dependabot
            all_ids = {vuln_id} | set(aliases)
            if all_ids & dependabot_ghsa_ids:
                continue

            # Extract severity
            severity = _extract_severity(vuln)

            # If severity unknown, try to enrich via NVD
            cve_ids = [a for a in aliases if a.startswith("CVE-")]
            nvd_data = None

            if cve_ids and nvd_enrichment_count < MAX_NVD_ENRICHMENTS:
                nvd_data = _enrich_with_nvd(cve_ids[0], nvd_api_key)
                nvd_enrichment_count += 1
                if nvd_enrichment_count < MAX_NVD_ENRICHMENTS:
                    time.sleep(nvd_delay)

                if nvd_data and nvd_data.get("cvss_score"):
                    score = nvd_data["cvss_score"]
                    if score >= 9.0:
                        severity = "critical"
                    elif score >= 7.0:
                        severity = "high"
                    elif score >= 4.0:
                        severity = "medium"
                    else:
                        severity = "low"

            # Skip low severity and unknown (unless NVD says otherwise)
            if severity not in PROCESS_SEVERITIES:
                continue

            # Extract fixed version
            fixed_version = _extract_fixed_version(vuln, dep["name"], dep["ecosystem"])

            # Check user disclosure need
            user_disclosure = dep["name"].lower() in {p.lower() for p in USER_DISCLOSURE_PACKAGES}

            finding = {
                "vuln_id": vuln_id,
                "aliases": aliases,
                "severity": severity,
                "package": dep["name"],
                "ecosystem": dep["ecosystem"],
                "current_version": dep["version"],
                "fixed_version": fixed_version,
                "summary": vuln.get("summary", vuln.get("details", "")[:200]),
                "source": "osv",
                "source_file": dep["source_file"],
                "user_disclosure_needed": user_disclosure,
                "cvss_score": nvd_data.get("cvss_score") if nvd_data else None,
                "cvss_vector": nvd_data.get("cvss_vector") if nvd_data else None,
                "references": (nvd_data.get("references", []) if nvd_data else [])
                    + vuln.get("references", [])[:3],
            }

            # Flatten references (OSV references are dicts with "url" key)
            flat_refs = []
            for ref in finding["references"]:
                if isinstance(ref, dict):
                    flat_refs.append(ref.get("url", ""))
                elif isinstance(ref, str):
                    flat_refs.append(ref)
            finding["references"] = [r for r in flat_refs if r][:5]

            findings.append(finding)

    return findings


# ---------------------------------------------------------------------------
# Tracking and dispatch
# ---------------------------------------------------------------------------

def _build_alert_summary(findings_to_dispatch: List[Dict]) -> str:
    """Build alert summary for the claude prompt, grouped by severity."""
    by_severity: Dict[str, List[Dict]] = {"critical": [], "high": [], "medium": []}

    for finding in findings_to_dispatch:
        sev = finding["severity"].lower()
        if sev in by_severity:
            by_severity[sev].append(finding)

    lines = []
    for sev in ("critical", "high", "medium"):
        if not by_severity[sev]:
            continue
        prefix = "" if not lines else "\n"
        lines.append(f"{prefix}{sev.upper()}:")
        for f in by_severity[sev]:
            vuln_id = f["vuln_id"]
            pkg = f["package"]
            ecosystem = f["ecosystem"]
            summary = f["summary"]
            current = f["current_version"]
            cve_ids = [a for a in f.get("aliases", []) if a.startswith("CVE-")]
            cve_str = f" ({', '.join(cve_ids)})" if cve_ids else ""

            fixed = f.get("fixed_version")
            fix_str = (f"\n  Fix: upgrade from {current} to >= {fixed}"
                       if fixed
                       else f"\n  Fix: upgrade from {current} to latest patched version")

            cvss = f.get("cvss_score")
            cvss_str = f"\n  CVSS: {cvss}" if cvss else ""

            source_file = f.get("source_file", "")
            file_str = f"\n  Manifest: {source_file}" if source_file else ""

            disclosure = f.get("user_disclosure_needed", False)
            disclosure_str = "\n  USER DISCLOSURE NEEDED: This package handles user data/auth/encryption." if disclosure else ""

            re_dispatch = f.get("re_dispatch_count", 0)
            re_dispatch_str = (f"\n  NOTE: Previously dispatched {re_dispatch} time(s) — still unresolved."
                               if re_dispatch > 0 else "")

            source = f.get("source", "osv")
            source_str = f"\n  Source: {source.upper()}"

            lines.append(
                f"- [{vuln_id}] {pkg} ({ecosystem}) — {summary}{cve_str}"
                f"{fix_str}{cvss_str}{file_str}{source_str}{disclosure_str}{re_dispatch_str}"
            )

    return "\n".join(lines)


def _build_json_summary(findings: List[Dict]) -> str:
    """Build a JSON summary for --summary mode and nightly integration."""
    summary = {
        "date": os.environ.get("TODAY_DATE", ""),
        "source": "eu-vuln-checker",
        "total_findings": len(findings),
        "by_severity": {},
        "findings": [],
    }

    for sev in ("critical", "high", "medium"):
        count = sum(1 for f in findings if f["severity"] == sev)
        if count > 0:
            summary["by_severity"][sev] = count

    for f in findings:
        cve_ids = [a for a in f.get("aliases", []) if a.startswith("CVE-")]
        summary["findings"].append({
            "vuln_id": f["vuln_id"],
            "cve": cve_ids[0] if cve_ids else None,
            "package": f["package"],
            "ecosystem": f["ecosystem"],
            "severity": f["severity"],
            "current_version": f["current_version"],
            "fixed_version": f.get("fixed_version"),
            "summary": f["summary"],
            "user_disclosure_needed": f.get("user_disclosure_needed", False),
            "source": f.get("source", "osv"),
        })

    return json.dumps(summary, indent=2)


def check_vulns() -> None:
    """Main entry point: scan dependencies, query EU/intl sources, dispatch if needed."""
    tracking_file = os.environ.get("TRACKING_FILE_PATH", "")
    dependabot_tracking = os.environ.get("DEPENDABOT_TRACKING_PATH", "")
    project_root = os.environ.get("PROJECT_ROOT", "")
    redispatch_days = int(os.environ.get("REDISPATCH_AFTER_DAYS", "7"))
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    summary_only = os.environ.get("SUMMARY_ONLY", "false").lower() == "true"
    prompt_template_path = os.environ.get("PROMPT_TEMPLATE_PATH", "")
    today_date = os.environ.get("TODAY_DATE", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    nvd_api_key = os.environ.get("NVD_API_KEY", "") or None

    if not project_root:
        print("[eu-vulns] ERROR: PROJECT_ROOT not set.", file=sys.stderr)
        sys.exit(1)

    if not tracking_file:
        print("[eu-vulns] ERROR: TRACKING_FILE_PATH not set.", file=sys.stderr)
        sys.exit(1)

    # Step 1: Collect all dependencies
    all_deps = _collect_all_dependencies(project_root)
    if not all_deps:
        print("[eu-vulns] No dependencies found — done.")
        return

    # Step 2: Load Dependabot state for deduplication
    dependabot_ghsa_ids = _load_dependabot_ghsa_ids(dependabot_tracking) if dependabot_tracking else set()
    print(f"[eu-vulns] Dependabot tracking: {len(dependabot_ghsa_ids)} known GHSA ID(s) to skip")

    # Step 3: Query OSV batch API
    osv_results = _query_osv_batch(all_deps)

    # Step 4: Process results — dedup against Dependabot, enrich via NVD
    findings = _process_osv_results(osv_results, dependabot_ghsa_ids, nvd_api_key)
    print(f"[eu-vulns] Actionable findings (after Dependabot dedup): {len(findings)}")

    if not findings:
        print("[eu-vulns] No new vulnerabilities found beyond Dependabot coverage — done.")
        # Update tracking last_run
        tracking = _load_json_file(tracking_file, {"last_run": "", "processed": []})
        tracking["last_run"] = _now_iso()
        _save_json_file(tracking_file, tracking)
        return

    # Sort by severity
    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))

    # Summary-only mode: output JSON and exit
    if summary_only:
        print(_build_json_summary(findings))
        return

    # Step 5: Load tracking state and determine which to dispatch
    tracking = _load_json_file(tracking_file, {"last_run": "", "processed": []})
    processed_map: Dict[str, Dict] = {e["vuln_id"]: e for e in tracking.get("processed", [])}

    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    to_dispatch: List[Dict] = []
    skip_count = 0
    resolve_count = 0

    for finding in findings:
        vuln_id = finding["vuln_id"]

        # Check if resolved in git (by vuln_id or any CVE alias)
        ids_to_check = [vuln_id] + [a for a in finding.get("aliases", []) if a.startswith("CVE-")]
        commit_sha = None
        for check_id in ids_to_check:
            commit_sha = _check_vuln_in_git(check_id, project_root)
            if commit_sha:
                break

        if commit_sha:
            print(f"[eu-vulns] {vuln_id} resolved via commit {commit_sha}")
            processed_map[vuln_id] = {
                **finding,
                "first_seen_at": processed_map.get(vuln_id, {}).get("first_seen_at", now_iso),
                "last_dispatched_at": processed_map.get(vuln_id, {}).get("last_dispatched_at"),
                "re_dispatch_count": processed_map.get(vuln_id, {}).get("re_dispatch_count", 0),
                "resolved_via_commit": commit_sha,
            }
            resolve_count += 1
            continue

        existing = processed_map.get(vuln_id)

        if existing is None:
            # New finding
            print(f"[eu-vulns] {vuln_id} [{finding['severity']}] {finding['package']} — NEW")
            finding["re_dispatch_count"] = 0
            to_dispatch.append(finding)
            processed_map[vuln_id] = {
                **finding,
                "first_seen_at": now_iso,
                "last_dispatched_at": now_iso,
                "re_dispatch_count": 0,
                "resolved_via_commit": None,
            }
        else:
            # Previously seen — check grace period
            last_dispatched_str = existing.get("last_dispatched_at")
            if not last_dispatched_str:
                print(f"[eu-vulns] {vuln_id} — tracked but never dispatched, dispatching now.")
                finding["re_dispatch_count"] = 0
                to_dispatch.append(finding)
                existing["last_dispatched_at"] = now_iso
            else:
                try:
                    last_dispatched = datetime.fromisoformat(last_dispatched_str.replace("Z", "+00:00"))
                    days_since = (now - last_dispatched).days
                except ValueError:
                    days_since = redispatch_days + 1

                if days_since >= redispatch_days:
                    re_count = existing.get("re_dispatch_count", 0) + 1
                    print(f"[eu-vulns] {vuln_id} [{finding['severity']}] — "
                          f"still unresolved after {days_since} days, RE-DISPATCHING (count={re_count}).")
                    finding["re_dispatch_count"] = re_count
                    to_dispatch.append(finding)
                    existing["re_dispatch_count"] = re_count
                    existing["last_dispatched_at"] = now_iso
                else:
                    remaining = redispatch_days - days_since
                    print(f"[eu-vulns] {vuln_id} [{finding['severity']}] — "
                          f"within grace period ({remaining} day(s) remaining), skipping.")
                    skip_count += 1

    print(f"[eu-vulns] Dispatch summary: {len(to_dispatch)} to dispatch, "
          f"{skip_count} skipped (grace period), {resolve_count} resolved in git.")

    # Update tracking
    tracking["last_run"] = now_iso
    tracking["processed"] = list(processed_map.values())
    _save_json_file(tracking_file, tracking)
    print(f"[eu-vulns] Tracking file updated: {tracking_file}")

    if not to_dispatch:
        print("[eu-vulns] Nothing to dispatch — done.")
        return

    # Sort for prompt
    to_dispatch.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))

    # Step 6: Build prompt and dispatch claude
    if not prompt_template_path or not os.path.isfile(prompt_template_path):
        print(f"[eu-vulns] ERROR: Prompt template not found at {prompt_template_path}", file=sys.stderr)
        sys.exit(1)

    with open(prompt_template_path) as f:
        prompt_template = f.read()

    alert_summary = _build_alert_summary(to_dispatch)

    # Build disclosure summary
    disclosure_pkgs = [f for f in to_dispatch if f.get("user_disclosure_needed")]
    disclosure_section = "(none)" if not disclosure_pkgs else "\n".join(
        f"- {f['package']} ({f['vuln_id']}): handles {_disclosure_reason(f['package'])}"
        for f in disclosure_pkgs
    )

    prompt = (
        prompt_template
        .replace("{{DATE}}", today_date)
        .replace("{{ALERT_SUMMARY}}", alert_summary)
        .replace("{{DISCLOSURE_SUMMARY}}", disclosure_section)
        .replace("{{TOTAL_FINDINGS}}", str(len(to_dispatch)))
    )

    if dry_run:
        print("[eu-vulns] DRY RUN — would run claude with the following prompt:")
        print("-" * 60)
        print(prompt[:3000])
        if len(prompt) > 3000:
            print(f"... ({len(prompt)} chars total)")
        print("-" * 60)
        print()
        print("[eu-vulns] JSON summary:")
        print(_build_json_summary(to_dispatch))
        return

    session_title = f"security: eu-vulns {today_date}"
    print(f"[eu-vulns] Starting claude session for {len(to_dispatch)} finding(s)...")

    run_claude_session(
        prompt=prompt,
        session_title=session_title,
        project_root=project_root,
        log_prefix="[eu-vulns]",
        agent=None,  # build mode — fix the vulns
        timeout=1800,
        job_type="eu-vulns",
        context_summary=f"{len(to_dispatch)} EU-source vulnerability(ies) dispatched for fix",
        kill_on_exit=True,
    )


def _disclosure_reason(package_name: str) -> str:
    """Return human-readable reason why a package needs user disclosure."""
    reasons = {
        "tweetnacl": "client-side encryption",
        "cryptography": "server-side encryption",
        "pynacl": "server-side NaCl crypto",
        "argon2-cffi": "password hashing",
        "stripe": "payment processing (server)",
        "@stripe/stripe-js": "payment processing (client)",
        "polar-sdk": "payment processing (Polar)",
        "@polar-sh/checkout": "payment checkout (Polar)",
        "@revolut/checkout": "payment checkout (Revolut)",
        "webauthn": "WebAuthn/Passkey authentication",
        "pyotp": "TOTP 2FA",
        "dompurify": "HTML sanitization (XSS prevention)",
        "httpx": "HTTP client (API requests with auth tokens)",
        "aiohttp": "async HTTP client",
        "redis": "cache/session storage",
        "boto3": "S3 file storage",
    }
    return reasons.get(package_name, "user data handling")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <check-vulns>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    if command == "check-vulns":
        check_vulns()
    else:
        print(f"[eu-vulns] Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
