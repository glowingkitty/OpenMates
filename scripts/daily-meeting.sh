#!/usr/bin/env bash
# =============================================================================
# OpenMates Daily Standup Meeting
#
# Orchestrates the daily meeting with Claude Code:
# 1. Gathers data from 11 sources (nightly reports, git, tests, health, etc.)
# 2. Starts the main meeting session with all data injected into the prompt
# 3. Sends email with resume link (claude resume --dangerous <session-id>)
# 4. Spawns auto-confirm timer (70 min) for priority confirmation
#
# No subagents — the meeting session reads all data directly, avoiding
# unnecessary summarization layers that add latency and failure risk.
#
# Can be invoked manually or via /daily-meeting skill:
#   ./scripts/daily-meeting.sh                    # run full meeting
#   DRY_RUN=true ./scripts/daily-meeting.sh       # print prompt, skip claude
#   MEETING_DATE=2026-03-26 ./scripts/daily-meeting.sh  # review specific date
#
# Env vars (sourced from .env automatically):
#   INTERNAL_API_URL                  — base URL for internal API (default: http://localhost:8000)
#   SECRET__ADMIN__DEBUG_CLI__API_KEY — admin API key for issue fetching
#   INTERNAL_API_SHARED_TOKEN         — for email dispatch
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCKFILE="/tmp/openmates-daily-meeting.lock"

# Ensure npm-global bin is on PATH (cron runs with minimal PATH)
export PATH="/home/superdev/.local/bin:/home/superdev/.npm-global/bin:$PATH"

# Source .env if present
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

echo "[daily-meeting] Starting at $(date '+%Y-%m-%d %H:%M:%S %Z')"

# Prevent double-runs
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "[daily-meeting] Another instance is already running (lockfile: $LOCKFILE). Exiting."
  exit 0
fi

# Run the meeting
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  python3 "$SCRIPT_DIR/_daily_meeting_helper.py" dry-run
else
  python3 "$SCRIPT_DIR/_daily_meeting_helper.py" run-meeting

  # Spawn auto-confirm timer in background (70 minutes)
  # This will apply priorities to Linear if the user doesn't join and confirm manually
  AUTO_CONFIRM_DELAY=$((70 * 60))
  (
    sleep "$AUTO_CONFIRM_DELAY"
    echo "[daily-meeting] Auto-confirm timer expired. Checking if priorities need confirmation..."
    python3 "$SCRIPT_DIR/_daily_meeting_helper.py" auto-confirm
  ) &
  AUTO_CONFIRM_PID=$!
  echo "[daily-meeting] Auto-confirm timer started (PID $AUTO_CONFIRM_PID, ${AUTO_CONFIRM_DELAY}s delay)"
fi

echo "[daily-meeting] Complete at $(date '+%Y-%m-%d %H:%M:%S %Z')"
