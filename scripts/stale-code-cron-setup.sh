#!/usr/bin/env bash
# Installs the report-only deterministic stale-code job in the user crontab.
# The Python installer owns idempotent block rendering and removes the disabled
# legacy auto-removal entry. No source edits or agent sessions run from cron.
# Architecture: docs/specs/deterministic-stale-code-reporting/spec.yml.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/stale_code_daily.py" --install-cron
