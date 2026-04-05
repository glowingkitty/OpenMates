#!/usr/bin/env bash
# =============================================================================
# OpenMates Deep Security Audit (Agent-Based)
#
# Spawns one Claude session per folder. Each session spawns haiku subagents
# (one per file) that trace security issues across the full codebase.
# All work happens in a temporary git worktree — dev branch is untouched.
# Results are written as YAML to security-audit/findings/.
# A final merge step deduplicates and produces a consolidated report.
#
# Triggered by system crontab (nightly at 04:00 UTC):
#   0 4 * * 1-5 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/security-deep-audit.sh' >> /path/to/logs/security-deep-audit.log 2>&1
#
# Manual:
#   ./scripts/security-deep-audit.sh
#   ./scripts/security-deep-audit.sh --dry-run       # list folders, don't run
#   ./scripts/security-deep-audit.sh --folder <path>  # single folder only
#   ./scripts/security-deep-audit.sh --priority high  # only high+ priority folders
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# --- Parse CLI args ---
DRY_RUN=false
SINGLE_FOLDER=""
PRIORITY_FILTER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --folder) SINGLE_FOLDER="$2"; shift 2 ;;
    --priority) PRIORITY_FILTER="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[deep-audit] Starting deep security audit at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

export DRY_RUN
export PROJECT_ROOT
export SINGLE_FOLDER
export PRIORITY_FILTER

python3 "$SCRIPT_DIR/_security_deep_audit_helper.py"

echo "[deep-audit] Deep security audit complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
