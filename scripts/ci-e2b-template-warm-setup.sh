#!/usr/bin/env bash
# Installs a user timer that keeps the E2B CI runner dependency template for
# origin/dev built (scripts/ci_e2b_runner.py warm, TASK-9435). Warm only builds
# when origin/dev's dependency hash has no template yet; otherwise it is a cheap
# lookup. Uses the heavy-remote venv because it holds the E2B SDK.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
PYTHON="$HOME/.cache/openmates/heavy-remote/venv/bin/python"

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/openmates-ci-e2b-template-warm.service" <<UNIT
[Unit]
Description=OpenMates: build the E2B CI runner dependency template for origin/dev when missing

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
TimeoutStartSec=40min
Nice=10
ExecStart=$PYTHON $PROJECT_ROOT/scripts/ci_e2b_runner.py warm
UNIT

cat > "$SYSTEMD_DIR/openmates-ci-e2b-template-warm.timer" <<UNIT
[Unit]
Description=Keep the E2B CI runner dependency template warm every 30 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=30min
RandomizedDelaySec=2min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now openmates-ci-e2b-template-warm.timer
systemctl --user status openmates-ci-e2b-template-warm.timer --no-pager | head -5
