#!/usr/bin/env bash
# =============================================================================
# OpenMates Release Intelligence Cron Entrypoint
#
# Generates LLM-backed daily, weekly, and monthly release intelligence artifacts
# for PR, release, newsletter, and social planning. Intended for host cron on the
# dev server with .env sourced for Gemini and Discord credentials.
#
# Schedules:
#   daily   00:20 UTC every day
#   weekly  00:45 UTC every Monday, posts Discord summary
#   monthly 01:10 UTC on the first day of each month
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-daily}"

cd "$PROJECT_ROOT"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_ROOT/.env"
  set +a
fi

mkdir -p "$PROJECT_ROOT/docs/releases/daily" "$PROJECT_ROOT/docs/releases/weekly" "$PROJECT_ROOT/docs/releases/monthly" "$PROJECT_ROOT/logs"

run_daily() {
  local day="${RELEASE_INTELLIGENCE_DATE:-$(date -u -d 'yesterday' +%F)}"
  local next_day
  next_day="$(date -u -d "$day +1 day" +%F)"
  python3 scripts/release_intelligence.py daily \
    --since "${day}T00:00:00+00:00" \
    --until "${next_day}T00:00:00+00:00" \
    --date "$day" \
    --write
}

run_weekly() {
  local week_end="${RELEASE_INTELLIGENCE_WEEK_END:-$(date -u -d 'yesterday' +%F)}"
  local week_start="${RELEASE_INTELLIGENCE_WEEK_START:-$(date -u -d "$week_end -6 days" +%F)}"
  python3 scripts/release_intelligence.py weekly \
    --week-start "$week_start" \
    --week-end "$week_end" \
    --write \
    --discord
}

run_monthly() {
  local current_month_start previous_month_start previous_month_end
  current_month_start="$(date -u +%Y-%m-01)"
  previous_month_start="${RELEASE_INTELLIGENCE_MONTH_START:-$(date -u -d "$current_month_start -1 month" +%Y-%m-01)}"
  previous_month_end="${RELEASE_INTELLIGENCE_MONTH_END:-$(date -u -d "$current_month_start -1 day" +%F)}"
  python3 scripts/release_intelligence.py monthly \
    --month-start "$previous_month_start" \
    --month-end "$previous_month_end" \
    --write
}

case "$MODE" in
  daily)
    run_daily
    ;;
  weekly)
    run_weekly
    ;;
  monthly)
    run_monthly
    ;;
  *)
    echo "Usage: $0 {daily|weekly|monthly}" >&2
    exit 2
    ;;
esac
