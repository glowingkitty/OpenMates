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
SOURCE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$SOURCE_ROOT"
MODE="${1:-daily}"

cd "$SOURCE_ROOT"

if [[ -f "$SOURCE_ROOT/.env" ]]; then
  set +u
  set -a
  # shellcheck disable=SC1091
  . "$SOURCE_ROOT/.env"
  set +a
  set -u
fi
export RELEASE_INTELLIGENCE_SOURCE_ROOT="$SOURCE_ROOT"

mkdir -p "$SOURCE_ROOT/logs"

LOCK_FILE="${RELEASE_INTELLIGENCE_LOCK_FILE:-$SOURCE_ROOT/logs/release-intelligence.lock}"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[release-intelligence] another generation run is active; skipping $MODE" >&2
  exit 0
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/openmates-release-intelligence.XXXXXX")"
SHARED_LOCK_OWNER="release-intelligence-cron-$(hostname)-$$"
SHARED_LOCK_HELD=false
cleanup() {
  if [[ "$SHARED_LOCK_HELD" == true ]]; then
    python3 "$SOURCE_ROOT/scripts/sessions.py" unlock --session "$SHARED_LOCK_OWNER" --type vercel >/dev/null
  fi
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

REMOTE_URL="$(git -C "$SOURCE_ROOT" remote get-url origin)"
git clone --quiet --branch dev "$REMOTE_URL" "$TEMP_ROOT/repo"
PROJECT_ROOT="$TEMP_ROOT/repo"
cd "$PROJECT_ROOT"
BASE_DEV_SHA="$(git rev-parse HEAD)"
PUBLISHED_SHA=""

mkdir -p "$PROJECT_ROOT/docs/releases/daily" "$PROJECT_ROOT/docs/releases/weekly" "$PROJECT_ROOT/docs/releases/monthly"

run_daily_for_day() {
  local day="$1"
  local next_day
  next_day="$(date -u -d "$day +1 day" +%F)"
  python3 scripts/release_intelligence.py daily \
    --since "${day}T00:00:00+00:00" \
    --until "${next_day}T00:00:00+00:00" \
    --date "$day" \
    --write
}

refresh_daily_range() {
  local day="$1"
  local end_day="$2"
  while [[ "$day" < "$end_day" || "$day" == "$end_day" ]]; do
    run_daily_for_day "$day"
    day="$(date -u -d "$day +1 day" +%F)"
  done
}

run_daily() {
  local day="${RELEASE_INTELLIGENCE_DATE:-$(date -u -d 'yesterday' +%F)}"
  run_daily_for_day "$day"
}

run_weekly() {
  local week_end="${RELEASE_INTELLIGENCE_WEEK_END:-$(date -u -d 'yesterday' +%F)}"
  local week_start="${RELEASE_INTELLIGENCE_WEEK_START:-$(date -u -d "$week_end -6 days" +%F)}"
  WEEKLY_ARTIFACT="docs/releases/weekly/$(date -u -d "$week_start" +%G-W%V).yml"
  refresh_daily_range "$week_start" "$week_end"
  python3 scripts/release_intelligence.py weekly \
    --week-start "$week_start" \
    --week-end "$week_end" \
    --write
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

publish_artifacts() {
  local changes title current_dev_sha published_sha
  changes="$(git status --porcelain -- docs/releases)"
  title="docs: update ${MODE} release intelligence"

  while ! python3 "$SOURCE_ROOT/scripts/sessions.py" lock --session "$SHARED_LOCK_OWNER" --type vercel; do
    sleep 30
  done
  SHARED_LOCK_HELD=true
  git fetch --quiet origin dev
  current_dev_sha="$(git rev-parse origin/dev)"
  if [[ "$current_dev_sha" != "$BASE_DEV_SHA" ]] && \
    ! git diff --quiet "$BASE_DEV_SHA..$current_dev_sha" -- docs/releases; then
    echo "[release-intelligence] dev release artifacts changed during generation; aborting stale publication" >&2
    return 1
  fi

  if [[ -z "$changes" ]]; then
    PUBLISHED_SHA="$current_dev_sha"
    echo "[release-intelligence] no release artifact changes to publish" >&2
    return
  fi

  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add docs/releases
  git commit --quiet -m "$title"
  if [[ "$current_dev_sha" != "$BASE_DEV_SHA" ]]; then
    git rebase "$current_dev_sha"
  fi
  published_sha="$(git rev-parse HEAD)"
  git push --quiet origin HEAD:dev
  git fetch --quiet origin dev
  current_dev_sha="$(git rev-parse origin/dev)"
  if [[ "$current_dev_sha" != "$published_sha" ]]; then
    echo "[release-intelligence] remote dev did not reach generated commit $published_sha" >&2
    return 1
  fi
  PUBLISHED_SHA="$published_sha"
  echo "[release-intelligence] publication pushed: $published_sha" >&2
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

publish_artifacts

if [[ "$MODE" == "weekly" ]]; then
  git fetch --quiet origin dev
  if [[ "$(git rev-parse origin/dev)" != "$PUBLISHED_SHA" ]]; then
    echo "[release-intelligence] dev changed before weekly notification; refusing stale Discord post" >&2
    exit 1
  fi
  python3 scripts/release_intelligence.py notify-weekly \
    --artifact "$WEEKLY_ARTIFACT"
fi
