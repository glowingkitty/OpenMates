#!/bin/bash
# Hook: UserPromptSubmit — linear-context-auto-prefetch
# ------------------------------------------------------------------
# Workflow: .claude/rules/linear-tasks.md makes three fetches MANDATORY
# before any code work when an OPE-\d+ issue ID is referenced:
#   1. mcp__linear__get_issue
#   2. mcp__linear__extract_images (bug reports regularly include
#      screenshots that Claude must view)
#   3. mcp__linear__list_comments
#
# Today this relies on Claude "remembering" the rule — which means the
# image check is regularly skipped. This hook injects a reminder as
# additionalContext every time an OPE-XXX appears in a user prompt,
# scoped to the first occurrence per-session via a tiny sentinel file
# under .claude/.prefetch-cache/.
#
# Strictness: Reminder-only (no blocking). exit 0.
# Related: .claude/rules/linear-tasks.md

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

[ -z "$PROMPT" ] && exit 0

# Extract first OPE-\d+ from the prompt
ISSUE=$(echo "$PROMPT" | grep -oE 'OPE-[0-9]+' | head -1)
[ -z "$ISSUE" ] && exit 0

PROJECT_DIR="/home/superdev/projects/OpenMates"
CACHE_DIR="$PROJECT_DIR/.claude/.prefetch-cache"
mkdir -p "$CACHE_DIR" 2>/dev/null

# Sentinel: skip reminder if we already injected for this session+issue
SENTINEL="$CACHE_DIR/${SESSION_ID:-nosession}_${ISSUE}.ok"
if [ -f "$SENTINEL" ]; then
  exit 0
fi
touch "$SENTINEL" 2>/dev/null

MSG="📋 Linear task context reminder — prompt references $ISSUE.

Per .claude/rules/linear-tasks.md, BEFORE writing any code you MUST:
  1. mcp__linear__get_issue(id=\"$ISSUE\") — full title, description, status
  2. mcp__linear__extract_images(markdown=<issue description>) — bug reports
     frequently contain screenshots. NEVER skip this step.
  3. mcp__linear__list_comments(issueId=\"$ISSUE\") — prior discussion
  4. mcp__linear__save_issue(id=\"$ISSUE\", state=\"In Progress\",
     labels=[\"claude-is-working\"])
  5. mcp__linear__save_comment with the session-resume command

This reminder fires once per (session, issue) pair."
echo "$MSG" >&2
jq -nc --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$msg}}'

exit 0
