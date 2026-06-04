#!/usr/bin/env bash
# =============================================================================
# OpenMates UI Design Review
#
# Starts a read-only OpenCode chat that inspects the current web and Apple UI
# codebase, then recommends top design-system, redundancy, readability, and
# hook/lint improvements. Recent commits are context only; the live codebase is
# always the primary input.
#
# Triggered by system crontab (Tue + Fri at 04:10 UTC):
#   10 4 * * 2,5 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-ui-design-review.sh' >> /path/to/logs/ui-design-review.log 2>&1
#
# Manual:
#   ./scripts/nightly-ui-design-review.sh
#   ./scripts/nightly-ui-design-review.sh --dry-run
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

echo "[ui-design-review] Starting at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
python3 "$SCRIPT_DIR/_scheduled_review_helper.py" ui-design-review "$@"
echo "[ui-design-review] Complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
