#!/usr/bin/env bash
# =============================================================================
# OpenMates SEO Audit
#
# Starts a read-only OpenCode chat that inspects production SEO behavior and the
# current SvelteKit source code. This is deeper than the daily meeting SEO smoke
# check and returns prioritized optimization suggestions only.
#
# Triggered by system crontab (Sun at 04:50 UTC):
#   50 4 * * 0 bash -c 'set -a && . /path/to/.env && set +a && /path/to/scripts/nightly-seo-audit.sh' >> /path/to/logs/seo-audit.log 2>&1
#
# Manual:
#   ./scripts/nightly-seo-audit.sh
#   ./scripts/nightly-seo-audit.sh --dry-run
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

echo "[seo-audit] Starting at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
python3 "$SCRIPT_DIR/_scheduled_review_helper.py" seo-audit "$@"
echo "[seo-audit] Complete at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
