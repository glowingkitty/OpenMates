#!/bin/bash
# Sync the tracked dev Caddyfile to the live system Caddy config.
#
# Source of truth:
#   deployment/dev_server/Caddyfile
#
# Runtime-only secrets, such as OpenCode Basic Auth credentials, stay in the
# caddy.service systemd drop-in and are referenced by env vars from the tracked
# Caddyfile. This prevents /etc/caddy/Caddyfile drift when dev API routes change.

set -euo pipefail

usage() {
    cat <<'EOF'
Usage: sudo scripts/sync-dev-caddy.sh [--opencode-auth <username> <password>] [--source <path>] [--target <path>]

Installs deployment/dev_server/Caddyfile as /etc/caddy/Caddyfile, validates it,
and reloads Caddy. If --opencode-auth is provided, the password is hashed with
Caddy and stored in /etc/systemd/system/caddy.service.d/opencode-auth.conf.

Examples:
  sudo scripts/sync-dev-caddy.sh
  sudo scripts/sync-dev-caddy.sh --opencode-auth marco '<password>'
EOF
}

if [ "${EUID}" -ne 0 ]; then
    echo "ERROR: run this script with sudo or as root." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_CADDYFILE="$REPO_ROOT/deployment/dev_server/Caddyfile"
TARGET_CADDYFILE="/etc/caddy/Caddyfile"
DROPIN_DIR="/etc/systemd/system/caddy.service.d"
DROPIN_FILE="$DROPIN_DIR/opencode-auth.conf"
OPENCODE_USER=""
OPENCODE_PASSWORD=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --opencode-auth)
            if [ "$#" -lt 3 ]; then
                usage
                exit 1
            fi
            OPENCODE_USER="$2"
            OPENCODE_PASSWORD="$3"
            shift 3
            ;;
        --source)
            if [ "$#" -lt 2 ]; then
                usage
                exit 1
            fi
            SOURCE_CADDYFILE="$2"
            shift 2
            ;;
        --target)
            if [ "$#" -lt 2 ]; then
                usage
                exit 1
            fi
            TARGET_CADDYFILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

if ! command -v caddy >/dev/null 2>&1; then
    echo "ERROR: caddy binary not found in PATH." >&2
    exit 1
fi

if [ ! -f "$SOURCE_CADDYFILE" ]; then
    echo "ERROR: source caddyfile not found: $SOURCE_CADDYFILE" >&2
    exit 1
fi

if [ -n "$OPENCODE_USER" ]; then
    PASSWORD_HASH="$(caddy hash-password --plaintext "$OPENCODE_PASSWORD")"
    mkdir -p "$DROPIN_DIR"
    python3 - "$OPENCODE_USER" "$PASSWORD_HASH" "$DROPIN_FILE" <<'PY'
import pathlib
import sys

username, password_hash, dropin_file = sys.argv[1:4]

def systemd_escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')

content = (
    "[Service]\n"
    f'Environment="OPENCODE_BASIC_AUTH_USER={systemd_escape(username)}"\n'
    f'Environment="OPENCODE_BASIC_AUTH_HASH={systemd_escape(password_hash)}"\n'
)

path = pathlib.Path(dropin_file)
path.write_text(content)
PY
fi

if [ ! -f "$DROPIN_FILE" ]; then
    echo "ERROR: missing $DROPIN_FILE." >&2
    echo "Run with --opencode-auth <username> <password> once before syncing." >&2
    exit 1
fi

install -m 0644 "$SOURCE_CADDYFILE" "$TARGET_CADDYFILE"
caddy adapt --config "$TARGET_CADDYFILE" >/dev/null
systemctl daemon-reload
systemctl reload caddy

echo "Dev Caddy config synced from: $SOURCE_CADDYFILE"
echo "Live Caddy config updated:     $TARGET_CADDYFILE"
echo "OpenCode auth drop-in:         $DROPIN_FILE"
