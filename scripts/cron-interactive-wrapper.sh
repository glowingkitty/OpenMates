#!/usr/bin/env bash
# =============================================================================
# Cron Interactive Wrapper
#
# Two-phase wrapper for cron-spawned Claude Code sessions. Runs inside a
# Zellij pane, launched by _claude_utils.spawn_interactive_session().
#
# Phase 1 — Headless planning:
#   Runs `claude -p` (Opus, plan mode) to analyze/plan the task.
#   Captures session_id from JSON output.
#
# Phase 2 — Interactive resume:
#   Updates Linear with resume instructions, then runs `claude --resume`
#   so the session stays alive for the user to attach and interact.
#
# The user can attach at any time during either phase:
#   zellij attach <session-name>
#
# Arguments (positional — set by spawn_interactive_session):
#   $1  prompt file path (cleaned up after phase 1)
#   $2  project root
#   $3  linear issue id ("none" if no task)
#   $4  linear identifier ("none" if no task)
#   $5  zellij session name
#   $6  timeout (seconds for phase 1)
#   $7+ claude command (full argv for headless phase)
#
# Not intended for direct use. Called by _claude_utils.py.
# =============================================================================
set -uo pipefail

PROMPT_FILE="${1:?}"
PROJECT_ROOT="${2:?}"
LINEAR_ISSUE_ID="${3:?}"
LINEAR_IDENTIFIER="${4:?}"
ZELLIJ_SESSION="${5:?}"
TIMEOUT="${6:?}"
shift 6
CLAUDE_CMD=("$@")

cd "$PROJECT_ROOT"
export PATH="/home/superdev/.local/bin:/home/superdev/.npm-global/bin:$PATH"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Phase 1: Headless Planning"
echo "  Timeout: ${TIMEOUT}s"
echo "══════════════════════════════════════════════════════════"
echo ""

OUTPUT_FILE=$(mktemp /tmp/claude-interactive-XXXXXX.json)

# Run headless planning phase
timeout "$TIMEOUT" "${CLAUDE_CMD[@]}" > "$OUTPUT_FILE" 2>&1
PHASE1_EXIT=$?

# Clean up prompt file (claude has already read it)
rm -f "$PROMPT_FILE"

if [[ $PHASE1_EXIT -eq 124 ]]; then
    echo "[wrapper] Planning timed out after ${TIMEOUT}s"
elif [[ $PHASE1_EXIT -ne 0 ]]; then
    echo "[wrapper] Planning exited with code $PHASE1_EXIT"
fi

# Extract session ID from JSON output
SESSION_ID=""
if [[ -f "$OUTPUT_FILE" ]]; then
    SESSION_ID=$(python3 -c "
import json
try:
    data = json.load(open('$OUTPUT_FILE'))
    print(data.get('session_id', ''))
except Exception:
    print('')
" 2>/dev/null)
fi

rm -f "$OUTPUT_FILE"

# Update Linear with resume instructions
if [[ -n "$SESSION_ID" && "$LINEAR_ISSUE_ID" != "none" ]]; then
    WRAPPER_PROJECT_ROOT="$PROJECT_ROOT" \
    WRAPPER_LINEAR_ISSUE_ID="$LINEAR_ISSUE_ID" \
    WRAPPER_LINEAR_IDENTIFIER="$LINEAR_IDENTIFIER" \
    WRAPPER_ZELLIJ_SESSION="$ZELLIJ_SESSION" \
    WRAPPER_SESSION_ID="$SESSION_ID" \
    python3 << 'PYEOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["WRAPPER_PROJECT_ROOT"], "scripts"))
from _linear_client import post_comment, update_issue_status

issue_id = os.environ["WRAPPER_LINEAR_ISSUE_ID"]
identifier = os.environ["WRAPPER_LINEAR_IDENTIFIER"]
zellij = os.environ["WRAPPER_ZELLIJ_SESSION"]
session_id = os.environ["WRAPPER_SESSION_ID"]

post_comment(issue_id, (
    "**Planning complete \u2014 ready for review.**\n\n"
    f"**Resume:** `zellij attach {zellij}`\n"
    f"**Session:** `claude --resume {session_id}`"
))
update_issue_status(issue_id, "In Review")
print(f"[wrapper] Linear: {identifier} \u2192 In Review")
PYEOF
fi

# Phase 2: Interactive resume
if [[ -n "$SESSION_ID" ]]; then
    echo ""
    echo "══════════════════════════════════════════════════════════"
    echo "  Phase 2: Interactive Session"
    echo "  Session: $SESSION_ID"
    echo "  Attach:  zellij attach $ZELLIJ_SESSION"
    echo "══════════════════════════════════════════════════════════"
    echo ""
    exec claude --resume "$SESSION_ID"
else
    echo ""
    echo "══════════════════════════════════════════════════════════"
    echo "  ERROR: No session ID from planning phase."
    echo "  Starting shell for investigation..."
    echo "══════════════════════════════════════════════════════════"
    exec bash
fi
