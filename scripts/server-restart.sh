#!/bin/bash
# server-restart.sh — Full server restart: rebuild Docker + launch OpenCode tmux workspace
#
# Usage:
#   ./scripts/server-restart.sh              # restore last 8 OpenCode sessions
#   ./scripts/server-restart.sh --fresh      # start fresh OpenCode sessions instead
#   ./scripts/server-restart.sh --no-docker  # skip Docker rebuild, just launch tmux
#
# Creates tmux session "opencode" with 2 windows × 4 panes each (side by side),
# all in ~/projects/OpenMates attached to the local OpenCode server.

set -euo pipefail

PROJECT_DIR="$HOME/projects/OpenMates"
TMUX_SESSION="opencode"
OPENCODE_SERVER_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"
OPENCODE_MODEL="${OPENCODE_MODEL:-openai/gpt-5.6-sol}"
DOCKER_ENV="$PROJECT_DIR/.env"
COMPOSE_BASE="$PROJECT_DIR/backend/core/docker-compose.yml"
COMPOSE_OVERRIDE="$PROJECT_DIR/backend/core/docker-compose.override.yml"
COMPOSE_CMD="docker compose --env-file $DOCKER_ENV -f $COMPOSE_BASE -f $COMPOSE_OVERRIDE"
PANES_PER_WINDOW=4
NUM_WINDOWS=2
TOTAL_PANES=$((PANES_PER_WINDOW * NUM_WINDOWS))

# --- Parse flags ---
FRESH=false
SKIP_DOCKER=false
for arg in "$@"; do
    case "$arg" in
        --fresh)     FRESH=true ;;
        --no-docker) SKIP_DOCKER=true ;;
        -h|--help)
            echo "Usage: $0 [--fresh] [--no-docker]"
            echo "  --fresh      Start fresh OpenCode sessions (default: restore recent)"
            echo "  --no-docker  Skip Docker rebuild, only launch tmux"
            exit 0
            ;;
    esac
done

# --- Collect session IDs for restore ---
SESSION_IDS=()
if ! $FRESH; then
    command -v opencode >/dev/null || { echo "Error: opencode is required." >&2; exit 1; }
    command -v jq >/dev/null || { echo "Error: jq is required." >&2; exit 1; }
    echo "Finding last $TOTAL_PANES OpenCode sessions to restore..."
    CURRENT_SID="${OPENCODE_SESSION_ID:-}"
    if ! session_json="$(opencode session list -n "$((TOTAL_PANES + 1))" --format json)"; then
        echo "Error: failed to list OpenCode sessions; refusing to start fresh sessions implicitly." >&2
        exit 1
    fi
    if ! session_id_lines="$(jq -r '.[].id' <<< "$session_json")"; then
        echo "Error: invalid OpenCode session data; refusing to start fresh sessions implicitly." >&2
        exit 1
    fi
    while IFS= read -r session_id; do
        if [ -n "$session_id" ] && [ "$session_id" != "$CURRENT_SID" ]; then
            SESSION_IDS+=("$session_id")
        fi
        [ ${#SESSION_IDS[@]} -ge "$TOTAL_PANES" ] && break
    done <<< "$session_id_lines"
    if [ ${#SESSION_IDS[@]} -eq 0 ]; then
        echo "  No sessions found to restore. Starting fresh."
        FRESH=true
    else
        echo "  Found ${#SESSION_IDS[@]} sessions:"
        for i in "${!SESSION_IDS[@]}"; do
            echo "    [$((i+1))] ${SESSION_IDS[$i]}"
        done
    fi
fi

# --- Docker rebuild ---
if ! $SKIP_DOCKER; then
    echo ""
    echo "Rebuilding Docker (running in background)..."
    echo "  down -> rm cache volume -> build -> up"
    (
        cd "$PROJECT_DIR"
        $COMPOSE_CMD down
        docker volume rm openmates-cache-data 2>/dev/null || true
        $COMPOSE_CMD build
        $COMPOSE_CMD up -d
        echo ""
        echo "Docker rebuild complete!"
    ) &
    DOCKER_PID=$!
    echo "  Docker PID: $DOCKER_PID"
else
    echo "Skipping Docker rebuild (--no-docker)"
fi

# --- Kill existing tmux session if any ---
if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo ""
    echo "Killing existing tmux session '$TMUX_SESSION'..."
    tmux kill-session -t "$TMUX_SESSION"
fi

# --- Build OpenCode command for each pane ---
build_opencode_cmd() {
    local pane_index=$1
    local -a opencode_args=(opencode run --attach "$OPENCODE_SERVER_URL" --interactive)
    local quoted_dir command_text

    if ! $FRESH && [ $pane_index -lt ${#SESSION_IDS[@]} ]; then
        opencode_args+=(--session "${SESSION_IDS[$pane_index]}" --agent plan "Resume this OpenCode session in read-only plan mode.")
    else
        opencode_args+=(--title "server-restart-$pane_index" --agent build --model "$OPENCODE_MODEL" --auto "Start a fresh OpenMates coding session. Run sessions.py start before mutating work.")
    fi
    printf -v quoted_dir '%q' "$PROJECT_DIR"
    printf -v command_text '%q ' "${opencode_args[@]}"
    printf 'cd %s && %s' "$quoted_dir" "$command_text"
}

# --- Create tmux session with horizontal panes ---
echo ""
echo "Creating tmux session '$TMUX_SESSION' ($NUM_WINDOWS windows x $PANES_PER_WINDOW panes)..."

pane_counter=0

for win in $(seq 0 $((NUM_WINDOWS - 1))); do
    if [ $win -eq 0 ]; then
        tmux new-session -d -s "$TMUX_SESSION" -n "work-$((win + 1))" -c "$PROJECT_DIR"
    else
        tmux new-window -t "$TMUX_SESSION" -n "work-$((win + 1))" -c "$PROJECT_DIR"
    fi

    # First pane (index 0) already exists — launch OpenCode in it
    tmux send-keys -t "$TMUX_SESSION:$win.0" "$(build_opencode_cmd $pane_counter)" Enter
    pane_counter=$((pane_counter + 1))

    # Split horizontally 3 more times to get 4 side-by-side panes
    for _ in $(seq 1 $((PANES_PER_WINDOW - 1))); do
        tmux split-window -h -t "$TMUX_SESSION:$win" -c "$PROJECT_DIR"
        # After split, the new pane is selected — send OpenCode command to it
        tmux send-keys -t "$TMUX_SESSION:$win" "$(build_opencode_cmd $pane_counter)" Enter
        pane_counter=$((pane_counter + 1))
    done

    # Distribute panes evenly (equal width, side by side)
    tmux select-layout -t "$TMUX_SESSION:$win" even-horizontal
done

# Select first window, first pane
tmux select-window -t "$TMUX_SESSION:0"
tmux select-pane -t "$TMUX_SESSION:0.0"

echo ""
echo "tmux session '$TMUX_SESSION' ready!"
echo "  $NUM_WINDOWS windows x $PANES_PER_WINDOW panes = $TOTAL_PANES OpenCode instances"
if ! $FRESH; then
    echo "  Restoring ${#SESSION_IDS[@]} previous sessions"
fi
echo ""
echo "  Attach with:  tmux attach -t $TMUX_SESSION"

# --- Wait for Docker if it was started ---
if ! $SKIP_DOCKER; then
    echo ""
    echo "Docker rebuild still running (PID $DOCKER_PID)..."
    echo "  You can attach to tmux now — Docker will finish in background."
fi
