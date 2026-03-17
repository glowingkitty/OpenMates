#!/usr/bin/env bash
# =============================================================================
# OpenMates Daily Dependabot Security Alert Checker
#
# Fetches open Dependabot security alerts from GitHub, deduplicates by GHSA ID,
# checks git history for matching commits, and starts an opencode session to fix
# any unresolved alerts.
#
# Processing logic:
#   1. Fetch all open Dependabot alerts via gh API (severity: critical, high, medium)
#   2. Deduplicate by GHSA ID (same vuln across multiple manifests = one entry)
#   3. Load scripts/dependabot-processed.json for state tracking
#   4. For each unique GHSA:
#      a. If commit referencing the GHSA ID exists in git → mark resolved, skip
#      b. If never processed → dispatch now
#      c. If previously dispatched → re-dispatch if last dispatch was >7 days ago
#         (increment re_dispatch_count); skip if within 7-day grace period
#   5. Build consolidated prompt for all new/re-dispatched alerts
#   6. Run opencode to fix the alerts
#   7. Update dependabot-processed.json
#
# Triggered by system crontab:
#   0 4 * * * bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/check-dependabot-daily.sh' >> /path/to/logs/dependabot-alerts.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/check-dependabot-daily.sh
#   ./scripts/check-dependabot-daily.sh --dry-run   # show what would be dispatched, no opencode
#
# Requirements:
#   - gh CLI installed and authenticated (gh auth status)
#   - GITHUB_REPO env var set to "owner/repo" (e.g. "glowingkitty/OpenMates"), OR
#     auto-detected from git remote
#
# Env vars (sourced from .env):
#   GITHUB_REPO   — GitHub repo in "owner/repo" format (optional, auto-detected if not set)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TRACKING_FILE="$SCRIPT_DIR/dependabot-processed.json"
PROMPT_TEMPLATE="$SCRIPT_DIR/prompts/dependabot-analysis.md"

# Re-dispatch threshold: re-open an opencode session if still unresolved after this many days
REDISPATCH_AFTER_DAYS=7

# Minimum severity to process (critical, high, medium — skip low)
PROCESS_SEVERITIES=("critical" "high" "medium")

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

# --- Parse CLI args ---
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h)
      sed -n '2,/^# =====/p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "[dependabot] Starting Dependabot alert check at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# --- Auto-detect GitHub repo if not set ---
if [[ -z "${GITHUB_REPO:-}" ]]; then
  GITHUB_REPO=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null \
    | sed -E 's|.*github\.com[:/]([^/]+/[^/.]+)(\.git)?$|\1|' || true)
  if [[ -z "$GITHUB_REPO" ]]; then
    echo "[dependabot] ERROR: GITHUB_REPO not set and could not auto-detect from git remote."
    exit 1
  fi
  echo "[dependabot] Auto-detected GitHub repo: $GITHUB_REPO"
fi

# --- Check gh CLI is available ---
if ! command -v gh &>/dev/null; then
  echo "[dependabot] ERROR: gh CLI not found. Install it or add it to PATH."
  exit 1
fi

# --- Check gh is authenticated ---
if ! gh auth status &>/dev/null; then
  echo "[dependabot] ERROR: gh CLI is not authenticated. Run: gh auth login"
  exit 1
fi

# --- Fetch all open Dependabot alerts ---
echo "[dependabot] Fetching open Dependabot alerts for $GITHUB_REPO..."
ALERTS_JSON=$(gh api "repos/$GITHUB_REPO/dependabot/alerts?state=open&per_page=100" 2>&1) || {
  echo "[dependabot] ERROR: Failed to fetch Dependabot alerts: $ALERTS_JSON"
  exit 1
}

ALERT_COUNT=$(echo "$ALERTS_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "0")
echo "[dependabot] Fetched $ALERT_COUNT open alert(s)."

if [[ "$ALERT_COUNT" -eq 0 ]]; then
  echo "[dependabot] No open Dependabot alerts — done."
  # Update last_run in tracking file
  python3 - <<'PYEOF'
import json, os, sys
from datetime import datetime, timezone

tracking_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dependabot-processed.json")
tracking_file = tracking_file.replace("/scripts/../scripts", "/scripts")

# Use the path from env since this heredoc doesn't have access to bash vars
import sys
tracking_file_path = os.environ.get("TRACKING_FILE_PATH", tracking_file)

data = {"last_run": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "processed": []}
if os.path.isfile(tracking_file_path):
    try:
        with open(tracking_file_path) as f:
            existing = json.load(f)
        existing["last_run"] = data["last_run"]
        data = existing
    except Exception:
        pass

with open(tracking_file_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("[dependabot] Updated last_run in tracking file.")
PYEOF
  exit 0
fi

# --- Process alerts using Python for the complex dedup/tracking logic ---
export TRACKING_FILE_PATH="$TRACKING_FILE"
export ALERTS_JSON_B64
ALERTS_JSON_B64=$(echo "$ALERTS_JSON" | base64 -w 0)
export PROJECT_ROOT
export REDISPATCH_AFTER_DAYS
export DRY_RUN
export PROMPT_TEMPLATE_PATH="$PROMPT_TEMPLATE"
TODAY_DATE=$(date -u '+%Y-%m-%d')
export TODAY_DATE

python3 "$SCRIPT_DIR/_dependabot_helper.py" process-alerts

echo "[dependabot] Dependabot check complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
