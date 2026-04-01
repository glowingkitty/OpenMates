#!/usr/bin/env bash
# =============================================================================
# OpenMates Daily EU Vulnerability Source Checker (OPE-224)
#
# Queries EU and international vulnerability databases (OSV, NVD) to detect
# security issues in our npm and pip dependencies that Dependabot may miss.
#
# Data sources:
#   - OSV (api.osv.dev) — primary: aggregates GitHub Advisories, PyPI, npm,
#     Debian, Alpine, and EU-contributed advisories. Batch queries, no auth.
#   - NVD (services.nvd.nist.gov) — secondary: enriches CVE details with
#     CVSS scores and references. Free API key optional (higher rate limit).
#   - EUVD (euvd.enisa.europa.eu) — noted for future: EU Vulnerability
#     Database under NIS2 Directive. No public API yet as of 2026-03.
#
# Processing logic:
#   1. Parse all package.json and requirements.txt files for dependencies
#   2. Query OSV batch API with package name + version + ecosystem
#   3. Filter out vulns already tracked by Dependabot (cross-ref GHSA IDs)
#   4. Enrich with NVD data (CVSS scores, references) where available
#   5. Deduplicate against previous runs (eu-vuln-processed.json)
#   6. Generate summary with: package, old->new version, CVE, relevance,
#      user disclosure needed
#   7. Dispatch claude session to fix new/re-dispatched vulns
#
# Triggered by system crontab (daily at 05:00 UTC, after Dependabot at 04:30):
#   0 5 * * * bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/check-eu-vulns-daily.sh' >> /path/to/logs/eu-vulns.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/check-eu-vulns-daily.sh
#   ./scripts/check-eu-vulns-daily.sh --dry-run   # show findings, no claude
#   ./scripts/check-eu-vulns-daily.sh --summary    # output JSON summary only
#
# Requirements:
#   - python3 with urllib (stdlib — no pip deps)
#   - Dependabot tracking file (scripts/dependabot-processed.json) for dedup
#
# Env vars (optional):
#   NVD_API_KEY — free NVD API key for higher rate limits (50 vs 5 req/30s)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRACKING_FILE="$SCRIPT_DIR/eu-vuln-processed.json"
DEPENDABOT_TRACKING="$SCRIPT_DIR/dependabot-processed.json"
PROMPT_TEMPLATE="$SCRIPT_DIR/prompts/eu-vuln-analysis.md"

# Re-dispatch threshold: re-dispatch if still unresolved after this many days
REDISPATCH_AFTER_DAYS=7

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# --- Parse CLI args ---
DRY_RUN=false
SUMMARY_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --summary) SUMMARY_ONLY=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[eu-vulns] Starting EU vulnerability source check at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export TRACKING_FILE_PATH="$TRACKING_FILE"
export DEPENDABOT_TRACKING_PATH="$DEPENDABOT_TRACKING"
export PROJECT_ROOT
export REDISPATCH_AFTER_DAYS
export DRY_RUN
export SUMMARY_ONLY
export PROMPT_TEMPLATE_PATH="$PROMPT_TEMPLATE"
TODAY_DATE=$(date -u '+%Y-%m-%d')
export TODAY_DATE
# NVD_API_KEY is optional — sourced from .env if available

python3 "$SCRIPT_DIR/_eu_vuln_helper.py" check-vulns

echo "[eu-vulns] EU vulnerability check complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
