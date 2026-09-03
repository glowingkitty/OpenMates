#!/usr/bin/env bash
# =============================================================================
# OpenMates Agent Worktree Reconciliation Timer Installer
#
# Installs a user-level systemd oneshot and hourly timer on the dev machine.
# The job first enforces the unconditional 72-hour hard lifetime without a
# network dependency, then integrates current eligible checkpoints and safely
# reconciles younger worktrees. Legacy state is never merged.
# Run manually after deploying lifecycle changes to the root control plane.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_ROOT="$(cd "$GIT_COMMON_DIR/.." && pwd)"
RUNTIME_ROOT="${OPENMATES_RECONCILIATION_RUNTIME_ROOT:-$(cd "$PROJECT_ROOT/.." && pwd)/.openmates-runtime/product-stack}"
SYSTEMD_DIR="$HOME/.config/systemd/user"

if [ -f "$RUNTIME_ROOT/scripts/sessions.py" ] \
    && [ "$(git -C "$RUNTIME_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)" = "$GIT_COMMON_DIR" ]; then
    EXECUTION_ROOT="$RUNTIME_ROOT"
else
    EXECUTION_ROOT="$PROJECT_ROOT"
fi

mkdir -p "$SYSTEMD_DIR"

cat > "$SYSTEMD_DIR/worktree-reconciliation.service" <<EOF
[Unit]
Description=OpenMates agent worktree reconciliation

[Service]
Type=oneshot
WorkingDirectory=$EXECUTION_ROOT
TimeoutStartSec=50min
Nice=10
ExecStart=/bin/bash -lc 'expire_status=0; /usr/bin/python3 $EXECUTION_ROOT/scripts/sessions.py worktree expire --max-age-hours 72 || expire_status=\$?; fetch_status=0; git fetch origin dev || fetch_status=\$?; if [ "\$fetch_status" -eq 0 ]; then /usr/bin/python3 $EXECUTION_ROOT/scripts/sessions.py worktree auto-integrate || echo "WARNING: checkpoint auto-integration failed; hard expiry already completed"; /usr/bin/python3 $EXECUTION_ROOT/scripts/sessions.py worktree reconcile --target origin/dev --idle-hours 48 --apply-safe || echo "WARNING: safe reconciliation failed; hard expiry already completed"; else echo "WARNING: git fetch failed; hard expiry already completed"; fi; exit "\$expire_status"'
EOF

cat > "$SYSTEMD_DIR/worktree-reconciliation.timer" <<EOF
[Unit]
Description=Reconcile OpenMates agent worktrees hourly

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now worktree-reconciliation.timer
systemctl --user status worktree-reconciliation.timer --no-pager
