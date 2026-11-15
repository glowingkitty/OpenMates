#!/usr/bin/env bash
# Staleness watchdog for the nightly production backup (TASK-5693).
#
# Runs hourly. When the last verified upload recorded by
# openmates-prod-backup.sh is older than OPENMATES_BACKUP_MAX_AGE_HOURS (26 h),
# it sends one Discord alert and repeats it every 24 h while the gap lasts.
# It is independent of the backup run itself, so it also catches a timer that
# never fired, a hung run or a run killed before it could alert.
set -Eeuo pipefail
umask 077

INSTALL_PATH="${OPENMATES_INSTALL_PATH:-/home/superdev/openmates}"
STATE_DIR="${OPENMATES_BACKUP_STATE_DIR:-$HOME/.local/state/openmates-backup}"
MAX_AGE_HOURS="${OPENMATES_BACKUP_MAX_AGE_HOURS:-26}"
REPEAT_HOURS="${OPENMATES_BACKUP_ALERT_REPEAT_HOURS:-24}"

mkdir -p "$STATE_DIR"
stamp="${STATE_DIR}/last-success.json"
alerted="${STATE_DIR}/stale-alerted-at"
now="$(date +%s)"

if [[ -f "$stamp" ]]; then
  last="$(stat -c %Y "$stamp")"
  age_hours=$(( (now - last) / 3600 ))
  if (( age_hours < MAX_AGE_HOURS )); then
    rm -f "$alerted"
    echo "backup fresh: last success ${age_hours} h ago"
    exit 0
  fi
  detail="the last verified backup is ${age_hours} h old ($(date -u -d "@${last}" +%FT%TZ))"
else
  detail="no successful backup is recorded on this host"
fi

if [[ -f "$alerted" ]] && (( now - $(stat -c %Y "$alerted") < REPEAT_HOURS * 3600 )); then
  echo "stale, alert already sent: ${detail}"
  exit 0
fi

webhook="$(awk -v n=OPENMATES_RUNTIME_HEALTH_DISCORD_WEBHOOK_URL_PRODUCTION \
  'index($0, n "=") == 1 { v = substr($0, length(n) + 2) } END { print v }' "${INSTALL_PATH}/.env" |
  sed -e "s/^'\(.*\)'$/\1/" -e 's/^"\(.*\)"$/\1/')"
if [[ -z "$webhook" ]]; then
  echo "ERROR: stale backup and no Discord webhook configured: ${detail}" >&2
  exit 1
fi
message="🟠 **Prod backup overdue** on $(hostname): ${detail}; limit is ${MAX_AGE_HOURS} h. Check \`systemctl status openmates-prod-backup.timer\` and \`journalctl -u openmates-prod-backup.service -n 100\`."
python3 -c 'import json,sys; print(json.dumps({"content": sys.argv[1]}))' "$message" |
  curl -fsS --max-time 20 -H 'Content-Type: application/json' --data-binary @- "$webhook" >/dev/null
touch "$alerted"
echo "stale alert sent: ${detail}"
