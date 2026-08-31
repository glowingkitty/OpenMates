#!/bin/bash
# Restart the OpenCode Web server without abandoning in-flight top-level chats.
# The exact busy set is persisted before Zellij receives Ctrl-C, then every
# captured chat is resumed once and verified after the replacement is healthy.
# This script intentionally does not touch the OpenMates Docker stack.

set -euo pipefail

SCRIPT_CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GIT_COMMON_DIR="$(git -C "$SCRIPT_CHECKOUT" rev-parse --path-format=absolute --git-common-dir)"
PROJECT_DIR="$(dirname "$GIT_COMMON_DIR")"
ZELLIJ_SESSION="${OPENCODE_ZELLIJ_SESSION:-code}"
PORT="${OPENCODE_PORT:-4096}"
SERVER_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:${PORT}}"
MANIFEST_DIR="$PROJECT_DIR/scripts/.tmp"
MANIFEST="$MANIFEST_DIR/opencode-restart-$(date -u +%Y%m%dT%H%M%SZ).json"

for arg in "$@"; do
    case "$arg" in
        --no-docker)
            echo "Note: --no-docker is now implicit; this workflow never restarts Docker."
            ;;
        -h|--help)
            echo "Usage: $0 [--no-docker]"
            echo "Captures busy top-level chats, restarts OpenCode in Zellij, then resumes and verifies them."
            exit 0
            ;;
        --fresh)
            echo "Error: --fresh was removed because it silently abandoned running chats." >&2
            exit 2
            ;;
        *)
            echo "Error: unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

command -v zellij >/dev/null || { echo "Error: zellij is required." >&2; exit 1; }
command -v jq >/dev/null || { echo "Error: jq is required." >&2; exit 1; }
command -v curl >/dev/null || { echo "Error: curl is required." >&2; exit 1; }

mkdir -p "$MANIFEST_DIR"
python3 "$SCRIPT_CHECKOUT/scripts/sessions.py" opencode-restart capture --manifest "$MANIFEST"

pane_json="$(zellij --session "$ZELLIJ_SESSION" action list-panes --json --command --state)"
mapfile -t server_panes < <(
    jq -r --arg port "$PORT" '
        .[]
        | select(.is_plugin == false)
        | ((.terminal_command // "") + " " + (.pane_command // "")) as $command
        | select($command | contains("start-opencode-server.sh"))
        | select($command | contains($port))
        | "terminal_\(.id)"
    ' <<< "$pane_json"
)
if [ "${#server_panes[@]}" -ne 1 ]; then
    echo "Error: expected exactly one OpenCode server pane in Zellij '$ZELLIJ_SESSION'; found ${#server_panes[@]}." >&2
    echo "Restart not attempted. Captured manifest: $MANIFEST" >&2
    exit 1
fi

server_pane="${server_panes[0]}"
echo "Stopping OpenCode server in $ZELLIJ_SESSION/$server_pane..."
zellij --session "$ZELLIJ_SESSION" action send-keys --pane-id "$server_pane" "Ctrl c"

for _ in $(seq 1 60); do
    if ! curl -fsS --max-time 1 "$SERVER_URL/session/status" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
if curl -fsS --max-time 1 "$SERVER_URL/session/status" >/dev/null 2>&1; then
    echo "Error: OpenCode server did not stop; replacement not started. Manifest: $MANIFEST" >&2
    exit 1
fi

zellij --session "$ZELLIJ_SESSION" action close-pane --pane-id "$server_pane" >/dev/null 2>&1 || true
zellij --session "$ZELLIJ_SESSION" action new-tab \
    --name opencode-server \
    --cwd "$PROJECT_DIR" \
    --close-on-exit \
    -- env OPENCODE_PROJECT_ROOT="$PROJECT_DIR" "$SCRIPT_CHECKOUT/scripts/start-opencode-server.sh" "$PORT" \
    >/dev/null

for _ in $(seq 1 120); do
    if curl -fsS --max-time 1 "$SERVER_URL/session/status" >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
if ! curl -fsS --max-time 2 "$SERVER_URL/session/status" >/dev/null; then
    echo "Error: replacement OpenCode server did not become healthy. Manifest: $MANIFEST" >&2
    echo "After recovery, run: python3 scripts/sessions.py opencode-restart resume --manifest '$MANIFEST'" >&2
    exit 1
fi

python3 "$SCRIPT_CHECKOUT/scripts/sessions.py" opencode-restart resume --manifest "$MANIFEST"
echo "OpenCode restart completed without abandoning the captured busy chat set."
