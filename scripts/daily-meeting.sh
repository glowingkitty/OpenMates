#!/usr/bin/env bash
# =============================================================================
# OpenMates Daily Standup Meeting
#
# Starts the weekday daily meeting as a persisted OpenCode chat:
# 1. Creates a new OpenCode session titled daily-meeting YYYY-MM-DD
# 2. Lets the daily-meeting skill gather data inside that chat
# 3. Sends an email with the OpenCode web deep link
#
# No Claude launcher and no Zellij session are involved. OpenCode CLI-created
# chats are stored in the same project session store used by the web app.
#
# Can be invoked manually or via /daily-meeting skill:
#   ./scripts/daily-meeting.sh                    # run full meeting
#
# Env vars (sourced from .env automatically):
#   DAILY_MEETING_NOTIFY_EMAIL — recipient for the meeting-ready email
#   OPENCODE_WEB_BASE_URL      — public OpenCode web base URL for deep links
#   INTERNAL_API_SHARED_TOKEN  — for email dispatch
#   INTERNAL_API_URL           — base URL for internal API (default: http://localhost:8000)
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

# Run the meeting. Weekday-only behavior is enforced in the Python helper too,
# so a misconfigured cron entry does not create weekend chats.
python3 "$SCRIPT_DIR/_opencode_daily_meeting.py"

echo "[daily-meeting] Complete at $(date '+%Y-%m-%d %H:%M:%S %Z')"
