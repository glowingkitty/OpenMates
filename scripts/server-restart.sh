#!/bin/bash
# server-restart.sh — Full server restart: rebuild Docker + launch Claude tmux workspace
#
# Usage:
#   ./scripts/server-restart.sh              # restore last 8 Claude sessions
#   ./scripts/server-restart.sh --fresh      # start fresh Claude sessions instead
#   ./scripts/server-restart.sh --no-docker  # skip Docker rebuild, just launch tmux
#
# Creates tmux session "claude" with 2 windows × 4 panes each (side by side),
# all in ~/projects/OpenMates running claude --dangerously-skip-permissions.

set -euo pipefail

PROJECT_DIR="$HOME/projects/OpenMates"
TMUX_SESSION="claude"
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
            echo "  --fresh      Start fresh Claude sessions (default: restore recent)"
            echo "  --no-docker  Skip Docker rebuild, only launch tmux"
            exit 0
            ;;
    esac
done

# --- Collect session IDs for restore ---
SESSION_IDS=()
if ! $FRESH; then
    echo "Finding last $TOTAL_PANES Claude sessions to restore..."
    # Get most recently modified session-env dirs (each is a session UUID)
    # Skip the current session (the one running this script)
    CURRENT_SID="${CLAUDE_SESSION_ID:-}"
    mapfile -t SESSION_IDS < <(
        ls -dt "$HOME/.claude/session-env"/*/ 2>/dev/null \
        | xargs -I{} basename {} \
        | grep -v "^${CURRENT_SID}$" \
        | head -n "$TOTAL_PANES"
    )
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

# --- Build claude command for each pane ---
build_claude_cmd() {
    local pane_index=$1
    local cmd="cd $PROJECT_DIR && "

    if ! $FRESH && [ $pane_index -lt ${#SESSION_IDS[@]} ]; then
        cmd+="claude --resume ${SESSION_IDS[$pane_index]} --dangerously-skip-permissions"
    else
        cmd+="claude --dangerously-skip-permissions"
    fi
    echo "$cmd"
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

    # First pane (index 0) already exists — launch claude in it
    tmux send-keys -t "$TMUX_SESSION:$win.0" "$(build_claude_cmd $pane_counter)" Enter
    pane_counter=$((pane_counter + 1))

    # Split horizontally 3 more times to get 4 side-by-side panes
    for _ in $(seq 1 $((PANES_PER_WINDOW - 1))); do
        tmux split-window -h -t "$TMUX_SESSION:$win" -c "$PROJECT_DIR"
        # After split, the new pane is selected — send claude command to it
        tmux send-keys -t "$TMUX_SESSION:$win" "$(build_claude_cmd $pane_counter)" Enter
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
echo "  $NUM_WINDOWS windows x $PANES_PER_WINDOW panes = $TOTAL_PANES Claude instances"
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
