#!/usr/bin/env bash
# Deprecated compatibility entrypoint for the former automatic deletion job.
# It now delegates to the report-only daily audit and never launches an agent,
# edits source, commits, or deploys. Use scripts/stale_code_daily.py directly.
# Architecture: docs/specs/deterministic-stale-code-reporting/spec.yml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[stale-code] nightly-dead-code-removal.sh is deprecated; running report-only audit." >&2
exec python3 "$SCRIPT_DIR/stale_code_daily.py" "$@"
