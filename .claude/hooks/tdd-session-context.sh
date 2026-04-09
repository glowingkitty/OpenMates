#!/bin/bash
# Hook: SessionStart (matchers: startup, resume)
# Injects a TDD context block for bug/feature sessions:
#   - Reminds Claude of the test-first workflow (reproduce red → fix → verify green)
#   - Keyword-matches task description against E2E spec filenames
#   - Suggests running sessions.py check-tests early
#
# Rationale: see .claude/rules/testing.md "Test-First Enforcement"
# For docs/question/testing modes the hook is a no-op (test-first doesn't apply).

set -eu

PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"
SPEC_DIR="$PROJECT_DIR/frontend/apps/web_app/tests"

emit_empty() {
  # Always exit 0 — this hook must never block session start.
  exit 0
}

[ -f "$SESSIONS_FILE" ] || emit_empty
command -v jq >/dev/null 2>&1 || emit_empty

# Pick the most recently active session (by last_active timestamp).
# On fresh startups before `sessions.py start` runs, this may surface a stale
# session; that's acceptable — the user will re-invoke /start and the next
# SessionStart on resume will pick up the new one.
SESSION_JSON=$(jq -c '
  .sessions
  | to_entries
  | map(select(.value.last_active != null))
  | sort_by(.value.last_active)
  | reverse
  | .[0] // empty
' "$SESSIONS_FILE" 2>/dev/null || true)

[ -n "$SESSION_JSON" ] || emit_empty

MODE=$(printf '%s' "$SESSION_JSON" | jq -r '.value.mode // ""')
TASK=$(printf '%s' "$SESSION_JSON" | jq -r '.value.task // ""')
SESSION_ID=$(printf '%s' "$SESSION_JSON" | jq -r '.key // ""')

# Only fire for modes where TDD actually applies.
case "$MODE" in
  bug|feature) ;;
  *) emit_empty ;;
esac

# Extract candidate specs by keyword-matching task text against spec filenames.
# Keep this cheap: lowercase the task, split into words ≥4 chars, grep filenames.
CANDIDATES=""
if [ -d "$SPEC_DIR" ]; then
  # Build a newline-separated list of spec basenames (no path, no .spec.ts).
  ALL_SPECS=$(find "$SPEC_DIR" -maxdepth 1 -name '*.spec.ts' -printf '%f\n' 2>/dev/null | sed 's/\.spec\.ts$//')

  # Tokenize task text into useful keywords (lowercase, 4+ chars, alnum only).
  KEYWORDS=$(printf '%s' "$TASK" \
    | tr '[:upper:]' '[:lower:]' \
    | tr -c 'a-z0-9' '\n' \
    | awk 'length($0) >= 4 { print }' \
    | sort -u)

  if [ -n "$KEYWORDS" ] && [ -n "$ALL_SPECS" ]; then
    # For each spec name, check whether any task keyword is a substring.
    MATCHED=""
    while IFS= read -r spec; do
      [ -z "$spec" ] && continue
      spec_lower=$(printf '%s' "$spec" | tr '[:upper:]' '[:lower:]')
      while IFS= read -r kw; do
        [ -z "$kw" ] && continue
        case "$spec_lower" in
          *"$kw"*)
            MATCHED="${MATCHED}${spec}.spec.ts\n"
            break
            ;;
        esac
      done <<EOF
$KEYWORDS
EOF
    done <<EOF
$ALL_SPECS
EOF

    # Keep up to 6 unique candidates.
    if [ -n "$MATCHED" ]; then
      CANDIDATES=$(printf '%b' "$MATCHED" | sort -u | head -6)
    fi
  fi
fi

# Build the additionalContext block. Keep it short — this is injected into
# every session start, so token cost matters.
CONTEXT="## Test-First Enforcement (mode=${MODE})

This is a **${MODE}** session. Per .claude/rules/testing.md, follow this workflow:

"
if [ "$MODE" = "bug" ]; then
  CONTEXT="${CONTEXT}1. Find or create a spec that **reproduces the bug (red)** before any fix code.
2. Run the spec to confirm it fails: \`python3 scripts/run_tests.py --spec <name>.spec.ts\`
3. Fix the bug.
4. Rerun the same spec — it must pass (green).
"
else
  CONTEXT="${CONTEXT}1. Check for an existing spec that covers this feature area.
2. Extend it (or propose a new spec) with assertions for the new behavior.
3. Implement.
4. Run the spec — it must pass (green).
"
fi

CONTEXT="${CONTEXT}
**First action:** run \`python3 scripts/sessions.py check-tests --session ${SESSION_ID}\` once you've touched any source file.
"

if [ -n "$CANDIDATES" ]; then
  CONTEXT="${CONTEXT}
**Candidate specs matched against the task description** (verify relevance before trusting):
"
  while IFS= read -r spec; do
    [ -z "$spec" ] && continue
    CONTEXT="${CONTEXT}- \`${spec}\` → \`python3 scripts/run_tests.py --spec ${spec}\`
"
  done <<EOF
$CANDIDATES
EOF
fi

CONTEXT="${CONTEXT}
Tip: use the \`/reproduce-first\` skill to let the harness walk the reproduce→fix→verify loop."

# Emit JSON. Use jq -n to escape the context safely.
jq -n --arg ctx "$CONTEXT" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: $ctx
  }
}'
exit 0
