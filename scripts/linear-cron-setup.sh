#!/usr/bin/env bash
# =============================================================================
# Linear Integration Systemd Service Installer
#
# Installs two systemd user services for the Linear-to-Claude investigation
# pipeline on the DEV SERVER ONLY. NOT for production use.
#
# 1. linear-poller.service — Runs every 30s, polls Linear for issues with
#    the claude-investigate label and writes trigger files.
# 2. linear-archive.service + timer — Runs daily, archives old closed issues
#    to stay within Linear's free plan 250-issue limit.
#
# Both scripts run on the HOST with LINEAR_API_KEY sourced from .env.
#
# Usage:
#   bash scripts/linear-cron-setup.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "=== Linear Integration Service Installer ==="
echo "Project root: $PROJECT_ROOT"
echo "Systemd dir:  $SYSTEMD_DIR"
echo ""

mkdir -p "$SYSTEMD_DIR"

# --- 1. Linear Poller Service (30s loop) ---

cat > "$SYSTEMD_DIR/linear-poller.service" << EOF
[Unit]
Description=OpenMates Linear Issue Poller (30s polling loop)
After=docker.service

[Service]
Type=simple
Restart=always
RestartSec=10
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$PROJECT_ROOT/.env
ExecStart=/bin/bash -c 'while true; do flock -n /tmp/linear-poller.lock python3 $PROJECT_ROOT/scripts/linear-poller.py 2>&1 || true; sleep 30; done'

[Install]
WantedBy=default.target
EOF

echo "[OK] Created linear-poller.service"

# --- 2. Linear Enricher Service + Timer (nightly at 3 AM) ---

cat > "$SYSTEMD_DIR/linear-enricher.service" << EOF
[Unit]
Description=OpenMates Linear Task Enrichment (nightly research)
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$PROJECT_ROOT/.env
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/linear-enricher.py --max-tasks 5
EOF

cat > "$SYSTEMD_DIR/linear-enricher.timer" << EOF
[Unit]
Description=Nightly Linear task enrichment (3 AM UTC)

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "[OK] Created linear-enricher.service + linear-enricher.timer"

# --- 3. Linear Archive Service + Timer (daily) ---

cat > "$SYSTEMD_DIR/linear-archive.service" << EOF
[Unit]
Description=OpenMates Linear Issue Archiver (daily sweep)
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$PROJECT_ROOT/.env
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/linear-archive-issues.py
EOF

cat > "$SYSTEMD_DIR/linear-archive.timer" << EOF
[Unit]
Description=Daily Linear issue archive sweep

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "[OK] Created linear-archive.service + linear-archive.timer"

# --- 4. Session Cleanup Service + Timer (every 5 minutes) ---

cat > "$SYSTEMD_DIR/session-cleanup.service" << EOF
[Unit]
Description=OpenMates Stale Session Cleanup
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$PROJECT_ROOT/.env
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/session-cleanup.py
EOF

cat > "$SYSTEMD_DIR/session-cleanup.timer" << EOF
[Unit]
Description=Clean stale Claude sessions every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "[OK] Created session-cleanup.service + session-cleanup.timer"

# --- 5. Linear E2E Artifact Cleanup + Done Archive (daily at 4 AM) ---

cat > "$SYSTEMD_DIR/linear-cleanup.service" << EOF
[Unit]
Description=OpenMates Linear E2E artifact cleanup + Done issue archive
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
EnvironmentFile=$PROJECT_ROOT/.env
ExecStart=/usr/bin/python3 $PROJECT_ROOT/scripts/linear-cleanup-e2e-artifacts.py
EOF

cat > "$SYSTEMD_DIR/linear-cleanup.timer" << EOF
[Unit]
Description=Daily Linear cleanup (E2E artifacts + archive old Done issues)

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "[OK] Created linear-cleanup.service + linear-cleanup.timer"

# --- Reload and enable ---

systemctl --user daemon-reload
echo "[OK] Systemd daemon reloaded"

systemctl --user enable --now linear-poller.service
echo "[OK] linear-poller.service enabled and started"

systemctl --user enable --now linear-enricher.timer
echo "[OK] linear-enricher.timer enabled and started"

systemctl --user enable --now linear-archive.timer
echo "[OK] linear-archive.timer enabled and started"

systemctl --user enable --now session-cleanup.timer
echo "[OK] session-cleanup.timer enabled and started"

systemctl --user enable --now linear-cleanup.timer
echo "[OK] linear-cleanup.timer enabled and started"

echo ""
echo "=== Service Status ==="
echo ""
echo "--- linear-poller.service ---"
systemctl --user status linear-poller.service --no-pager || true
echo ""
echo "--- linear-enricher.timer ---"
systemctl --user status linear-enricher.timer --no-pager || true
echo ""
echo "--- linear-archive.timer ---"
systemctl --user status linear-archive.timer --no-pager || true
echo ""
echo "--- session-cleanup.timer ---"
systemctl --user status session-cleanup.timer --no-pager || true
echo ""
echo "--- linear-cleanup.timer ---"
systemctl --user status linear-cleanup.timer --no-pager || true
echo ""
echo "Done. All services are running."
