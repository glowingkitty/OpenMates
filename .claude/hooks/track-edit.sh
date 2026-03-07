#!/bin/bash
# PostToolUse hook: track files modified by Edit|Write tools.
# Receives JSON on stdin from Claude Code hook system.
# Runs async — does not block the edit operation.
python3 "$(dirname "$0")/../../scripts/sessions.py" track-stdin
