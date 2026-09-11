#!/bin/bash
# Hook: PreToolUse (Edit|Write)
# Guards against editing generated files and warns on concurrent session conflicts.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE" ] && exit 0

# --- Guard 1: Block edits to generated translation JSON files ---
if echo "$FILE" | grep -qE 'i18n/locales/.*\.json$'; then
  echo "BLOCKED: Never edit generated translation JSON files directly. Edit the .yml source files in frontend/packages/ui/src/i18n/sources/ instead, then run: cd frontend/packages/ui && npm run build:translations" >&2
  exit 2
fi

# --- Guard 2: Warn on concurrent session file conflicts ---
PROJECT_DIR="/home/superdev/projects/OpenMates"
SESSIONS_FILE="$PROJECT_DIR/.claude/sessions.json"

normalize_repo_relative() {
  local file="$1"
  case "$file" in
    "$PROJECT_DIR"/*)
      printf '%s\n' "${file#$PROJECT_DIR/}"
      return
      ;;
  esac

  jq -r --arg file "$file" '
    [.sessions[]? | (.worktree.path? // .repo_root? // empty) | select($file | startswith(. + "/"))] |
    sort_by(length) |
    reverse |
    .[0] // empty
  ' "$SESSIONS_FILE" 2>/dev/null | {
    read -r worktree_path
    if [ -n "$worktree_path" ]; then
      printf '%s\n' "${file#$worktree_path/}"
    else
      printf '%s\n' "$file"
    fi
  }
}

if [ -f "$SESSIONS_FILE" ]; then
  # Get relative path for matching against session tracked files.
  REL_FILE=$(normalize_repo_relative "$FILE")

  # Codex identity is host-scoped; Claude retains its unique terminal fallback.
  if [ -n "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" ]; then
    CURRENT_SESSION=$(jq -r --arg id "${CODEX_THREAD_ID:-$CODEX_SESSION_ID}" --arg host "$(hostname)" \
      '[.sessions | to_entries[] | select(.value.codex_task_id == $id and .value.codex_host == $host) | .key] | if length == 1 then .[0] else empty end' \
      "$SESSIONS_FILE" 2>/dev/null)
  else
    CURRENT_SESSION=$(jq -r --arg z "${ZELLIJ_SESSION_NAME:-}" \
      '[.sessions | to_entries[] | select($z != "" and .value.zellij_session == $z) | .key] | if length == 1 then .[0] else empty end' \
      "$SESSIONS_FILE" 2>/dev/null)
  fi
  CURRENT_REPO=$(jq -r --arg current "$CURRENT_SESSION" '.sessions[$current].repo_id // "openmates"' "$SESSIONS_FILE" 2>/dev/null)
  CONFLICTS=$(jq -r --arg file "$REL_FILE" --arg current "$CURRENT_SESSION" --arg repo "$CURRENT_REPO" '
    [.sessions | to_entries[] |
     select(.key != $current) |
     select((.value.repo_id // "openmates") == $repo) |
     select(.value.modified_files[]? == $file) |
     "\(.key) (\(.value.task // "unknown task"))"] | join(", ")
  ' "$SESSIONS_FILE" 2>/dev/null)

  if [ -n "$CONFLICTS" ] && [ "$CONFLICTS" != "" ]; then
    # Output as additional context (non-blocking warning)
    echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"additionalContext\":\"WARNING: File $REL_FILE is also tracked by session(s): $CONFLICTS. Coordinate to avoid merge conflicts.\"}}"
    exit 0
  fi
fi

exit 0
