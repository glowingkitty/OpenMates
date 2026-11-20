#!/usr/bin/env bash
# Installs the systemd user service and timer for the daily AI test users run.
# Mon-Sat 06:30 UTC: `daily` (weekdays: 3 dev + 2 prod personas; Saturday: the weekly full run on dev).
# Prod personas only run when ~/.openmates/ai-test-users/prod-enabled exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/ai-test-users.service" <<UNIT
[Unit]
Description=OpenMates AI test users daily run
OnFailure=ai-test-users-failure.service

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=90min
Nice=10
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/ai_test_users.py daily
UNIT

# A crash, timeout or kill of the daily run sends one alert push (the run's own summary covers
# failures inside a finished run).
cat > "$SYSTEMD_DIR/ai-test-users-failure.service" <<UNIT
[Unit]
Description=Alert push for a failed OpenMates AI test users run

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/ai_test_users.py notify-failure --unit ai-test-users.service
UNIT

cat > "$SYSTEMD_DIR/ai-test-users.timer" <<UNIT
[Unit]
Description=Run the AI test users Monday to Saturday at 06:30 UTC

[Timer]
OnCalendar=Mon..Sat *-*-* 06:30:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now ai-test-users.timer
systemctl --user status ai-test-users.timer --no-pager
