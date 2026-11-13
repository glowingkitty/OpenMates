# Task commands

OpenMates Tasks keep their title, description, labels, comments, and attachment-key material encrypted by clients. The CLI decrypts authorized content locally.

Create and assign Tasks with one command:

```bash
openmates tasks create --title "Prepare release" --assign openmates
openmates tasks create --title "Implement bridge" --assign codex --external-chat codex:<thread-uuid> --as-assignee
openmates tasks create --title "Buy test device" --assign user
```

Assignment has two separate parts. `user`, `openmates`, `external_ai`, and `unassigned` describe who owns execution. An allowlisted identity describes a named AI: `openmates` displays as OpenMates and `codex` displays as Codex; legacy `codex` records display as Codex. The `external-ai` CLI value creates `external_ai/codex`; callers cannot supply arbitrary display names.

Task Activity uses ordinary comments and server-generated lifecycle rows:

```bash
openmates tasks activity list TASK-1234
openmates tasks activity add TASK-1234 --message "The API specification behavior is verified."
openmates tasks activity delete TASK-1234 <entry-id>
```

Each comment is encrypted directly with the Task key using a fresh AES-GCM nonce and Task/entry/version authenticated data. Attachment key material is encrypted separately with another nonce. The server stores ciphertext, safe actor attribution, timestamps, event type, and lifecycle status metadata. Creation and actual status changes automatically append system lifecycle entries; clients do not create those entries.

For activity comments, `--as-assignee` uses the Task's validated external AI
identity. It does not establish creator eligibility or start an agent.

## Connect a Task to Codex

Use an existing Codex thread with the local Codex app already running:

```bash
openmates tasks connect TASK-1234 --thread <thread-uuid>
openmates tasks connection TASK-1234 --json
openmates tasks resume TASK-1234
```

`connect` verifies the thread and saves its encrypted link. `connection` reads
live status without resuming work. `resume` opens the installed Codex CLI in an
interactive terminal; it never sends a prompt automatically. `tasks start`
continues to run native OpenMates AI.

New `--assign external-ai` assignments use Codex. Eligibility requires a Task
created explicitly from Codex using the paired CLI session:

```bash
openmates tasks create --title "Implement the requested change" --assign codex \
  --external-chat codex:<thread-uuid> --as-assignee
```

The CLI verifies the thread before declaring Codex creator identity. This is
an authenticated user declaration, not remote process attestation. It enables
assignment, not automatic execution. Changing an old assignment does not grant
eligibility. Existing Codex links remain readable with their original labels;
resuming an Codex link is rejected. No historical records are rewritten.

## Due dates

Set a due date when you create a Task, or set and change it later on an existing Task:

```bash
openmates tasks create --title "Send the press release" --due 2026-11-17
openmates tasks edit TASK-1234 --due "2026-11-17T11:00:00+01:00"
```

`--due` takes a date (`2026-11-17`, stored as that day at 00:00 UTC), a date and time with a
UTC offset, or Unix seconds. A due date can be replaced but not cleared from the CLI.

## Link a Task to a Claude Code session

Claude Code exports its session UUID as `CLAUDE_CODE_SESSION_ID`. Inside that
session, link, filter and release Tasks with the `claude` provider:

```bash
openmates tasks create --title "Fix footer links" \
  --external-chat "claude:$CLAUDE_CODE_SESSION_ID" --external-chat-title "Landing - Footer"
openmates tasks list --external-chat "claude:$CLAUDE_CODE_SESSION_ID"
openmates tasks edit TASK-1234 --external-chat "claude:$CLAUDE_CODE_SESSION_ID"
openmates tasks release TASK-1234
```

The session ID must be a UUID and must match `CLAUDE_CODE_SESSION_ID`; the CLI
rejects links made on behalf of another session. The ID and title (default
"Claude Code session") are encrypted locally like Codex links. A Claude Code
link is conversation context only: it does not change the Task's assignee, does
not declare creator identity, and cannot be used with `--as-assignee`,
`connect`, `connection` or `resume` (use `claude --resume <session-uuid>`).
