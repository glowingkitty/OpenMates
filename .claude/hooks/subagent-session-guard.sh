#!/usr/bin/env bash
# subagent-session-guard: thin wrapper; logic lives in scripts/subagent_session_guard.py (fails open).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/scripts/subagent_session_guard.py"
