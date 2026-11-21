#!/bin/sh
# Install automatic OS security updates and the update-driven reboot window.
# Usage: sudo sh install.sh --role core|upload|preview|dev   |   sh install.sh uninstall
# Windows (Europe/Berlin): preview 03:30 daily, upload 03:45 daily, dev 04:00
# daily (retries every 15 min until 06:00 while tests run), core Sundays 04:30.
# Test hook: OPENMATES_OS_ROOT=<dir> renders files under <dir> and touches nothing else.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT="${OPENMATES_OS_ROOT:-}"
ROLE=""
ACTION=install
while [ $# -gt 0 ]; do
    case "$1" in
        --role) ROLE="${2:-}"; shift 2 ;;
        uninstall) ACTION=uninstall; shift ;;
        *) echo "usage: install.sh --role core|upload|preview|dev | uninstall" >&2; exit 2 ;;
    esac
done
if [ -z "$ROOT" ] && [ "$(id -u)" -ne 0 ]; then echo "run as root" >&2; exit 1; fi
APT_CONF="$ROOT/etc/apt/apt.conf.d/52openmates-unattended-upgrades"
AUTO_CONF="$ROOT/etc/apt/apt.conf.d/20auto-upgrades"
SBIN="$ROOT/usr/local/sbin/openmates-reboot-if-required"
UNIT_DIR="$ROOT/etc/systemd/system"
CONF="$ROOT/etc/openmates/os-maintenance.conf"
ctl() { if [ -z "$ROOT" ]; then systemctl "$@"; fi; }

if [ "$ACTION" = uninstall ]; then
    ctl disable --now openmates-reboot.timer 2>/dev/null || true
    rm -f "$APT_CONF" "$SBIN" "$UNIT_DIR/openmates-reboot.service" "$UNIT_DIR/openmates-reboot.timer" "$CONF"
    ctl daemon-reload
    echo "removed (unattended-upgrades package and 20auto-upgrades left in place)"
    exit 0
fi

case "$ROLE" in
    core) CAL='Sun *-*-* 04:30:00 Europe/Berlin' ;;
    upload) CAL='*-*-* 03:45:00 Europe/Berlin' ;;
    preview) CAL='*-*-* 03:30:00 Europe/Berlin' ;;
    dev) CAL='*-*-* 04,05:00,15,30,45:00 Europe/Berlin
OnCalendar=*-*-* 06:00:00 Europe/Berlin' ;;
    *) echo "--role must be core, upload, preview or dev" >&2; exit 2 ;;
esac

if [ -z "$ROOT" ] && ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades
fi
mkdir -p "$(dirname "$APT_CONF")" "$(dirname "$SBIN")" "$UNIT_DIR" "$(dirname "$CONF")"
cat > "$APT_CONF" <<'CONFEOF'
// Managed by OpenMates (deployment/os_maintenance). Security origins only.
Unattended-Upgrade::Allowed-Origins {
        "${distro_id}:${distro_codename}-security";
        "${distro_id}ESMApps:${distro_codename}-apps-security";
        "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
CONFEOF
cat > "$AUTO_CONF" <<'CONFEOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONFEOF
install -m 0755 "$HERE/openmates-reboot-if-required" "$SBIN"
printf 'ROLE=%s\n' "$ROLE" > "$CONF"
cat > "$UNIT_DIR/openmates-reboot.service" <<'UNITEOF'
[Unit]
Description=Reboot only if an installed update requires it
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/openmates-reboot-if-required
UNITEOF
cat > "$UNIT_DIR/openmates-reboot.timer" <<UNITEOF
[Unit]
Description=OpenMates update reboot window ($ROLE)
[Timer]
OnCalendar=$CAL
Persistent=false
[Install]
WantedBy=timers.target
UNITEOF
ctl daemon-reload
ctl enable --now openmates-reboot.timer
echo "installed role=$ROLE; check: openmates-reboot-if-required --status; systemctl list-timers openmates-reboot.timer"
echo "KEV (approved by Marco): sudo openmates-reboot-if-required --now"
