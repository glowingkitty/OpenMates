#!/usr/bin/env bash
# read-outline-guard: thin wrapper; logic lives in scripts/read_outline_guard.py (fails open).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/scripts/read_outline_guard.py"
