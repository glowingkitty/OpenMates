#!/bin/bash
# Hook: SessionStart / UserPromptSubmit
# Fable runs only on explicit request: a chat that starts on Fable without one
# is told to stop and ask the user first (see scripts/fable_guard.py).
exec python3 "$(dirname "$0")/../../scripts/fable_guard.py"
