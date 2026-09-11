# Task commands

OpenMates Tasks keep their title, description, labels, comments, and attachment-key material encrypted by clients. The CLI decrypts authorized content locally.

Create and assign Tasks with one command:

```bash
openmates tasks create --title "Prepare release" --assign openmates
openmates tasks create --title "Implement bridge" --assign codex --external-chat codex:<thread-uuid> --as-assignee
openmates tasks create --title "Buy test device" --assign user
```

Assignment has two separate parts. `user`, `openmates`, `external_ai`, and `unassigned` describe who owns execution. An allowlisted identity describes a named AI: `openmates` displays as OpenMates and `codex` displays as Codex; legacy `opencode` records display as OpenCode. The `external-ai` CLI value creates `external_ai/codex`; callers cannot supply arbitrary display names.

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
eligibility. Existing OpenCode links remain readable with their original labels;
resuming an OpenCode link is rejected. No historical records are rewritten.
