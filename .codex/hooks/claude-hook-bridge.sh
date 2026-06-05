#!/bin/bash
# Bridge Codex hook payloads to the Claude hook scripts used by OpenMates.
# Codex reports patch edits as apply_patch commands, while many Claude hooks
# expect a per-file `tool_input.file_path`. This script extracts edited paths
# and invokes the existing Claude hooks with compatible payloads.

set -u

EVENT="${1:-}"
PROJECT_ROOT="/home/superdev/projects/OpenMates"
HOOK_DIR="$PROJECT_ROOT/.claude/hooks"
INPUT=$(cat)

if [ -z "$EVENT" ]; then
  exit 0
fi

tool_name() {
  echo "$INPUT" | jq -r '.tool_name // empty'
}

tool_command() {
  echo "$INPUT" | jq -r '.tool_input.command // .tool_input.patchText // .tool_input.patch // empty'
}

tool_file_path() {
  echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // .tool_input.path // empty'
}

to_abs_path() {
  local file="$1"
  case "$file" in
    /*) printf '%s\n' "$file" ;;
    *) printf '%s/%s\n' "$PROJECT_ROOT" "$file" ;;
  esac
}

extract_patch_files() {
  local explicit
  explicit=$(tool_file_path)
  if [ -n "$explicit" ]; then
    to_abs_path "$explicit"
    return
  fi

  tool_command | while IFS= read -r line; do
    case "$line" in
      "*** Add File: "*) to_abs_path "${line#*** Add File: }" ;;
      "*** Update File: "*) to_abs_path "${line#*** Update File: }" ;;
      "*** Delete File: "*) to_abs_path "${line#*** Delete File: }" ;;
      "*** Move to: "*) to_abs_path "${line#*** Move to: }" ;;
    esac
  done | sort -u
}

run_hook() {
  local script="$1"
  local payload="$2"
  local block_on_failure="${3:-true}"
  local stdout_file stderr_file
  local status

  stdout_file=$(mktemp)
  stderr_file=$(mktemp)
  printf '%s' "$payload" | "$HOOK_DIR/$script" >"$stdout_file" 2>"$stderr_file"
  status=$?

  if [ -s "$stdout_file" ]; then
    cat "$stdout_file"
  fi

  if [ -s "$stderr_file" ]; then
    cat "$stderr_file" >&2
  fi

  rm -f "$stdout_file" "$stderr_file"

  if [ "$status" -eq 2 ]; then
    exit 2
  fi

  if [ "$block_on_failure" = "true" ] && [ "$status" -ne 0 ]; then
    exit "$status"
  fi
}

payload_for_file() {
  local event="$1"
  local file="$2"
  echo "$INPUT" | jq \
    --arg cwd "$PROJECT_ROOT" \
    --arg event "$event" \
    --arg file "$file" \
    '{cwd: $cwd, hook_event_name: $event, tool_name: (.tool_name // "Edit"), tool_input: ((.tool_input // {}) + {file_path: $file})}'
}

payload_for_bash() {
  local command
  command=$(tool_command)
  jq -n \
    --arg cwd "$PROJECT_ROOT" \
    --arg command "$command" \
    '{cwd: $cwd, hook_event_name: "PreToolUse", tool_name: "Bash", tool_input: {command: $command}}'
}

run_for_files() {
  local event="$1"
  local block_on_failure="$2"
  shift 2
  local scripts=("$@")
  local file payload script
  local files=()

  mapfile -t files < <(extract_patch_files)

  for file in "${files[@]}"; do
    [ -z "$file" ] && continue
    payload=$(payload_for_file "$event" "$file")
    for script in "${scripts[@]}"; do
      run_hook "$script" "$payload" "$block_on_failure"
    done
  done
}

case "$EVENT" in
  SessionStart)
    run_hook "tdd-session-context.sh" '{"cwd":"/home/superdev/projects/OpenMates","hook_event_name":"SessionStart","source":"startup"}' false
    ;;
  PreToolUse)
    TOOL=$(tool_name)
    if [ "$TOOL" = "Bash" ] || [ "$TOOL" = "bash" ]; then
      run_hook "bash-guard.sh" "$(payload_for_bash)" true
      exit 0
    fi

    case "$TOOL" in
      apply_patch|Edit|Write)
        if [ "$TOOL" = "apply_patch" ]; then
          run_hook "e2e-encryption-guard.sh" "$INPUT" true
        fi

        run_for_files "PreToolUse" true \
          "pre-edit-guard.sh" \
          "provider-registry-sync.sh" \
          "analytics-sdk-forbidden.sh" \
          "legal-text-lastupdated-bump.sh" \
          "pii-logger-guard.sh" \
          "privacy-promise-guard.sh" \
          "cli-credential-prompt-guard.sh" \
          "external-resources-guard.sh" \
          "cookie-consent-gate.sh" \
          "css-selector-in-specs.sh" \
          "code-debt-pre-edit-guard.sh" \
          "svelte5-legacy-syntax.sh" \
          "donation-language-guard.sh" \
          "settings-canonical-elements.sh" \
          "native-ios-control-guard.sh" \
          "e2e-encryption-guard.sh"
        ;;
    esac
    ;;
  PostToolUse)
    TOOL=$(tool_name)
    case "$TOOL" in
      apply_patch|Edit|Write)
        run_for_files "PostToolUse" false \
          "auto-track.sh" \
          "auto-rebuild-translations.sh" \
          "testid-drift-detector.sh" \
          "encryption-architecture-reminder.sh" \
          "svelte-swift-counterpart-linker.sh"
        ;;
    esac
    ;;
  UserPromptSubmit)
    run_hook "session-gate.sh" "$INPUT" true
    run_hook "linear-context-auto-prefetch.sh" "$INPUT" false
    ;;
  Stop)
    run_hook "check-uncommitted.sh" '{"cwd":"/home/superdev/projects/OpenMates","hook_event_name":"Stop","stop_hook_active":false}' false
    ;;
esac

exit 0
