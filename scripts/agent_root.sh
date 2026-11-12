#!/usr/bin/env bash
# Unprivileged wrapper: scripts/agent_root.sh <verb...>
# Forwards to the root-owned helper through a single sudoers rule. See
# scripts/agent_root_ops.py for the allowed verbs.
set -uo pipefail

HELPER="/usr/local/sbin/openmates-agent-root-ops"
HINT="Root helper not installed. Ask the user once to run: sudo bash scripts/agent-root-ops-setup.sh --user ${USER:-$(id -un)}"

if [ ! -x "$HELPER" ]; then
    echo "$HINT" >&2
    exit 3
fi

args=("$@")
if [ "${1:-}" = "caddy" ] && [ "${2:-}" = "apply" ] && [ $# -eq 2 ]; then
    dev_caddyfile="$HOME/projects/OpenMates/deployment/dev_server/Caddyfile"
    if [ -L "$dev_caddyfile" ] || [ ! -f "$dev_caddyfile" ]; then
        echo "Canonical dev Caddyfile missing or a symlink: $dev_caddyfile" >&2
        exit 2
    fi
    args=(caddy apply "$(sha256sum "$dev_caddyfile" | cut -d' ' -f1)")
fi

if ! sudo -n -l "$HELPER" >/dev/null 2>&1; then
    echo "$HINT" >&2
    exit 3
fi
exec sudo -n "$HELPER" "${args[@]}"
