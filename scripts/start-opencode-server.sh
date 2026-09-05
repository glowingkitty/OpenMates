#!/bin/bash
# Start one verified OpenCode binary/app/control-plane release for code.dev.openmates.org.

set -euo pipefail

PORT="${1:-4096}"
HOSTNAME="127.0.0.1"
SOURCE_CHECKOUT="${OPENCODE_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNTIME_CHECKOUT="${OPENCODE_RUNTIME_CHECKOUT:-$(dirname "$SOURCE_CHECKOUT")/.openmates-runtime/opencode-server}"
RELEASES="${OPENCODE_RELEASES_DIR:-$HOME/.local/lib/opencode/releases}"
RELEASE="$RELEASES/current"
LOG_FILE="${OPENCODE_SERVER_LOG:-$HOME/.local/share/opencode/log/serve-${PORT}.log}"
SECRETS_FILE="${OPENCODE_SECRETS_FILE:-$HOME/.config/opencode/secrets.env}"
CONTROL_PLANE_COMMIT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["control_plane_commit"])' "$RELEASE/manifest.json")"
RESEARCH_CONFIG_PATHS=(
    "$HOME/.config/opencode/opencode.jsonc"
    "$HOME/.config/opencode/opencode.json"
    "$HOME/.opencode/opencode.jsonc"
    "$HOME/.opencode/opencode.json"
    "$SOURCE_CHECKOUT/opencode.jsonc"
    "$SOURCE_CHECKOUT/opencode.json"
    "$SOURCE_CHECKOUT/.opencode/opencode.jsonc"
    "$SOURCE_CHECKOUT/.opencode/opencode.json"
)

git -C "$SOURCE_CHECKOUT" fetch origin dev
git -C "$SOURCE_CHECKOUT" merge-base --is-ancestor "$CONTROL_PLANE_COMMIT" origin/dev || {
    echo "ERROR: release control-plane commit is not reachable from origin/dev: $CONTROL_PLANE_COMMIT" >&2
    exit 1
}
if [ ! -e "$RUNTIME_CHECKOUT/.git" ]; then
    mkdir -p "$(dirname "$RUNTIME_CHECKOUT")"
    git -C "$SOURCE_CHECKOUT" worktree add --detach "$RUNTIME_CHECKOUT" "$CONTROL_PLANE_COMMIT"
else
    if [ -n "$(git -C "$RUNTIME_CHECKOUT" status --porcelain)" ]; then
        echo "ERROR: OpenCode runtime checkout is dirty: $RUNTIME_CHECKOUT" >&2
        exit 1
    fi
    git -C "$RUNTIME_CHECKOUT" checkout --detach "$CONTROL_PLANE_COMMIT"
fi

python3 "$RUNTIME_CHECKOUT/scripts/opencode_runtime_release.py" validate \
    --release "$RELEASE" --require-workflow \
    --control-plane-commit "$(git -C "$RUNTIME_CHECKOUT" rev-parse HEAD)" \
    >/dev/null
RESEARCH_AUDIT_ARGS=(--research-routing-only)
for CONFIG_PATH in "${RESEARCH_CONFIG_PATHS[@]}"; do
    RESEARCH_AUDIT_ARGS+=(--runtime-config "$CONFIG_PATH")
done
python3 "$RUNTIME_CHECKOUT/scripts/audit_opencode_output_quality.py" "${RESEARCH_AUDIT_ARGS[@]}"
WORKFLOW_PACKAGE="$(readlink -f "$RELEASE")/workflow"
# Exactly one release-owned config directory supplies hooks, agents and skills.
# Project discovery stays disabled; the shared tracked checkout is never mirrored.

if [ -f "$SECRETS_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$SECRETS_FILE"
    set +a
fi

while read -r OPENCODE_PID; do
    [ -n "$OPENCODE_PID" ] || continue
    OPENCODE_ARGS="$(ps -p "$OPENCODE_PID" -o args= 2>/dev/null || true)"
    if [[ "$OPENCODE_ARGS" =~ opencode\ (serve|web).*\-\-port[[:space:]]+${PORT} ]]; then
        echo "ERROR: opencode is already running on port ${PORT}." >&2
        exit 1
    fi
done < <(pgrep -x opencode 2>/dev/null || true)

if ss -ltn "( sport = :${PORT} )" | grep -q ":${PORT}"; then
    echo "ERROR: port ${PORT} is already in use by another process." >&2
    exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"
echo "Starting verified OpenCode release: $(readlink -f "$RELEASE")"
echo "Runtime checkout: $RUNTIME_CHECKOUT ($(git -C "$RUNTIME_CHECKOUT" rev-parse --short HEAD))"

exec env -u OPENCODE_SERVER_PASSWORD -u OPENCODE_SERVER_USERNAME -u OPENCODE_CONFIG -u OPENCODE_CONFIG_CONTENT \
    OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1 \
    OPENCODE_DISABLE_PROJECT_CONFIG=1 \
    OPENCODE_CONFIG_DIR="$WORKFLOW_PACKAGE" \
    OPENMATES_REQUIRE_PLUGIN=1 \
    OPENMATES_PROJECT_ROOT="$SOURCE_CHECKOUT" \
    OPENMATES_CONTROL_PLANE_RUNTIME="$RUNTIME_CHECKOUT" \
    "$(readlink -f "$RELEASE")/opencode" web --hostname "$HOSTNAME" --port "$PORT" \
    2>&1 | tee -a "$LOG_FILE"
