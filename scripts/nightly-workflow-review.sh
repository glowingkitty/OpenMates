#!/usr/bin/env bash
# =============================================================================
# OpenMates Nightly Workflow Review
#
# Analyzes yesterday's opencode sessions to extract concrete improvement
# suggestions for scripts/sessions.py, backend/scripts/debug.py, and CLAUDE.md.
#
# Reads directly from the opencode SQLite DB (no API key needed).
# Filters to workflow-relevant sessions by title keywords, extracts text parts
# and targeted bash tool outputs, applies a per-session token budget, then
# runs a single claude analysis session to produce a numbered suggestion list.
#
# Triggered by a system crontab entry:
#   0 5 * * * /path/to/scripts/nightly-workflow-review.sh >> /path/to/logs/nightly-workflow-review.log 2>&1
#
# Can also be invoked manually:
#   ./scripts/nightly-workflow-review.sh               # review yesterday
#   REVIEW_DATE=2026-03-17 ./scripts/nightly-workflow-review.sh   # review specific date
#   DRY_RUN=true ./scripts/nightly-workflow-review.sh  # print prompt, skip claude
#
# No env vars required (reads opencode DB directly).
# State file: scripts/.workflow-review-state.json
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Ensure npm-global bin is on PATH (cron runs with minimal PATH)
export PATH="/home/superdev/.npm-global/bin:$PATH"

echo "[workflow-review] Starting nightly workflow review at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# Run the Python helper (dry-run or full review)
if [[ "${DRY_RUN:-false}" == "true" ]]; then
  python3 "$SCRIPT_DIR/_workflow_review_helper.py" dry-run
else
  python3 "$SCRIPT_DIR/_workflow_review_helper.py" run-review
fi

echo "[workflow-review] Nightly workflow review complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
