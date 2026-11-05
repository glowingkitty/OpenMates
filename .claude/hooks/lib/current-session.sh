#!/bin/bash
# Shared helper: print the sessions.py session ID owned by this Claude
# conversation, or nothing. Never guesses by recency.
#   $1 = Claude conversation ID (hook payload .session_id)
#   $2 = working directory (hook payload .cwd)
# Match order: recorded agent identity, then exact worktree containing cwd.
current_session_id() {
  local claude_id="$1" cwd="$2" sessions_file="$3"
  [ -f "$sessions_file" ] || return 0
  jq -r --arg id "$claude_id" --arg cwd "$cwd" '
    (.sessions // {}) | to_entries as $all
    | ([$all[] | select($id != "" and ((.value.agent_task_id // .value.codex_task_id) == $id)) | .key]) as $byid
    | if ($byid | length) == 1 then $byid[0]
      else
        [$all[] | select((.value.worktree.path // "") as $p
          | $p != "" and ($cwd == $p or ($cwd | startswith($p + "/")))) | .key]
        | if length == 1 then .[0] else empty end
      end
  ' "$sessions_file" 2>/dev/null
}
