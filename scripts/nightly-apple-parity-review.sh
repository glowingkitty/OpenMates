#!/usr/bin/env bash
# =============================================================================
# OpenMates Apple Parity Review
#
# Starts a read-only OpenCode chat that inspects current Swift and web UI code,
# uses recent web commits as prioritization context, and recommends the most
# important Apple parity follow-ups.
#
# Triggered by system crontab (Mon + Thu at 04:30 UTC):
#   30 4 * * 1,4 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-apple-parity-review.sh' >> /path/to/logs/apple-parity-review.log 2>&1
#
# Manual:
#   ./scripts/nightly-apple-parity-review.sh
#   ./scripts/nightly-apple-parity-review.sh --dry-run
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

echo "[apple-parity-review] Starting at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
python3 "$SCRIPT_DIR/apple_parity_audit.py" --output "$PROJECT_ROOT/test-results/apple-parity-inventory.json"
python3 "$SCRIPT_DIR/_scheduled_review_helper.py" apple-parity-review "$@"
echo "[apple-parity-review] Complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
