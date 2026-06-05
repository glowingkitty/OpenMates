#!/usr/bin/env bash
# =============================================================================
# OpenMates Weekly Deterministic Contract Audits
#
# Runs repo-specific static contract audits, stores JSON artifacts, sends a
# compact admin email when credentials are configured, then starts a read-only
# OpenCode chat that analyzes the JSON and recommends top next steps.
#
# Triggered by system crontab (Monday at 05:15 UTC):
#   15 5 * * 1 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/weekly-contract-audits.sh' >> /path/to/logs/contract-audits.log 2>&1
#
# Manual:
#   ./scripts/weekly-contract-audits.sh
#   ./scripts/weekly-contract-audits.sh --dry-run
#   ./scripts/weekly-contract-audits.sh --skip-review
#
# Env:
#   CONTRACT_AUDIT_EMAIL       optional recipient override
#   ADMIN_NOTIFY_EMAIL         fallback recipient
#   BREVO_API_KEY              preferred email transport
#   INTERNAL_API_SHARED_TOKEN  fallback email transport via internal API
#   CRON_SESSION_EMAILS_DISABLED=true  optional: suppress OpenCode chat email
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

DRY_RUN=false
SKIP_REVIEW=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --skip-review) SKIP_REVIEW=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[contract-audits] Starting weekly deterministic contract audits at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

cmd=(python3 "$SCRIPT_DIR/run_contract_audits.py" --environment development)
if [[ "$DRY_RUN" == "true" ]]; then
  cmd+=(--dry-run)
fi

"${cmd[@]}"

if [[ "$SKIP_REVIEW" == "true" ]]; then
  echo "[contract-audits] Skipping OpenCode recommendation review (--skip-review)."
else
  echo "[contract-audits] Starting OpenCode contract-audit recommendation review at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  review_cmd=(python3 "$SCRIPT_DIR/_contract_audit_review_helper.py" --report "$PROJECT_ROOT/test-results/contract-audits/latest.json")
  if [[ "$DRY_RUN" == "true" ]]; then
    review_cmd+=(--dry-run)
  fi
  "${review_cmd[@]}"
fi

echo "[contract-audits] Weekly deterministic contract audits complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
