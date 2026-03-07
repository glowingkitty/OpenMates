#!/bin/bash
# PreToolUse hook: check if a file is locked by another session.
# Receives JSON on stdin from Claude Code hook system.
# Exit 2 = block the edit; Exit 0 = allow.
python3 "$(dirname "$0")/../../scripts/sessions.py" check-write
