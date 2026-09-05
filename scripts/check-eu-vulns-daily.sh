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
#   7. Dispatch OpenCode chat to fix new/re-dispatched vulns
#
# Triggered hourly by the managed schedule in scripts/dependency_security_schedule.py.
#
# Can also be invoked manually:
#   ./scripts/check-eu-vulns-daily.sh
#   ./scripts/check-eu-vulns-daily.sh --dry-run   # show findings, no OpenCode
#   ./scripts/check-eu-vulns-daily.sh --summary    # output JSON summary only
#
# Requirements:
#   - python3 with urllib (stdlib — no pip deps)
#   - Dependabot runtime tracking in logs/, with the checked-in seed as fallback
#
# Env vars (optional):
#   NVD_API_KEY — free NVD API key for higher rate limits (50 vs 5 req/30s)
# The script intentionally does not load .env; callers may provide only the
# optional NVD key when enrichment is required.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRACKING_SEED="$SCRIPT_DIR/eu-vuln-processed.json"
TRACKING_FILE="$PROJECT_ROOT/logs/eu-vuln-processed.json"
DEPENDABOT_TRACKING_SEED="$SCRIPT_DIR/dependabot-processed.json"
DEPENDABOT_TRACKING_RUNTIME="$PROJECT_ROOT/logs/dependabot-processed.json"
DEPENDABOT_TRACKING="$DEPENDABOT_TRACKING_SEED"
LOCK_FILE="$PROJECT_ROOT/logs/eu-vuln-scanner.lock"
PROMPT_TEMPLATE="$SCRIPT_DIR/prompts/eu-vuln-analysis.md"

# Re-dispatch threshold: re-dispatch if still unresolved after this many days
REDISPATCH_AFTER_DAYS=7

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

if [[ "$DRY_RUN" != "true" && "$SUMMARY_ONLY" != "true" ]]; then
  # One persistent scanner instance owns its runtime state at a time.
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 200>"$LOCK_FILE"
  if ! flock -n 200; then
    echo "[eu-vulns] Another instance is already running. Exiting."
    exit 0
  fi
  if [[ ! -f "$TRACKING_FILE" ]]; then
    if [[ -f "$TRACKING_SEED" ]]; then
      cp "$TRACKING_SEED" "$TRACKING_FILE"
    else
      printf '{"last_run":"","processed":[]}\n' > "$TRACKING_FILE"
    fi
  fi
elif [[ ! -f "$TRACKING_FILE" ]]; then
  TRACKING_FILE="$TRACKING_SEED"
fi

if [[ -f "$DEPENDABOT_TRACKING_RUNTIME" ]]; then
  DEPENDABOT_TRACKING="$DEPENDABOT_TRACKING_RUNTIME"
fi

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
# NVD_API_KEY is optional and inherited only when explicitly exported by the caller.

python3 "$SCRIPT_DIR/_eu_vuln_helper.py" check-vulns

echo "[eu-vulns] EU vulnerability check complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
