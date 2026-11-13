#!/usr/bin/env bash
# One-time installer for the agent root helper. Run by the user with sudo:
#   sudo bash scripts/agent-root-ops-setup.sh --user <name>
#   sudo bash scripts/agent-root-ops-setup.sh --uninstall
# Copies agent_root_ops.py to a root-owned path outside the repo and adds a
# single sudoers rule for that exact path. Re-run after reviewing helper changes.
set -euo pipefail

HELPER_DEST="/usr/local/sbin/openmates-agent-root-ops"
SUDOERS_DEST="/etc/sudoers.d/openmates-agent-root-ops"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agent_root_ops.py"

if [ "$(id -u)" -ne 0 ]; then
    echo "Must run as root: sudo bash scripts/agent-root-ops-setup.sh --user <name>" >&2
    exit 1
fi

TARGET_USER=""
UNINSTALL=false
while [ $# -gt 0 ]; do
    case "$1" in
        --user) TARGET_USER="${2:-}"; shift 2 || true ;;
        --uninstall) UNINSTALL=true; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ "$UNINSTALL" = true ]; then
    rm -f "$SUDOERS_DEST" "$HELPER_DEST"
    echo "Removed $SUDOERS_DEST and $HELPER_DEST"
    exit 0
fi

if ! [[ "$TARGET_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "Usage: sudo bash scripts/agent-root-ops-setup.sh --user <name>" >&2
    exit 2
fi
if ! id "$TARGET_USER" >/dev/null 2>&1; then
    echo "Unknown user: $TARGET_USER" >&2
    exit 2
fi
if [ ! -f "$SRC" ]; then
    echo "Helper source not found: $SRC" >&2
    exit 1
fi

TMP_HELPER="$(mktemp /usr/local/sbin/.openmates-agent-root-ops.XXXXXX)"
TMP_SUDOERS="$(mktemp /etc/sudoers.d/.openmates-agent-root-ops.XXXXXX)"
trap 'rm -f "$TMP_HELPER" "$TMP_SUDOERS"' EXIT

install -m 0755 -o root -g root "$SRC" "$TMP_HELPER"
mv -f "$TMP_HELPER" "$HELPER_DEST"
echo "Installed $HELPER_DEST"
echo "sha256: $(sha256sum "$HELPER_DEST" | cut -d' ' -f1)"

printf '%s ALL=(root) NOPASSWD: %s\n' "$TARGET_USER" "$HELPER_DEST" > "$TMP_SUDOERS"
chown root:root "$TMP_SUDOERS"
chmod 0440 "$TMP_SUDOERS"
visudo -cf "$TMP_SUDOERS" >/dev/null
mv -f "$TMP_SUDOERS" "$SUDOERS_DEST"
echo "Installed $SUDOERS_DEST for user $TARGET_USER"
