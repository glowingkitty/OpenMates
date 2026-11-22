# Hosted Project sandbox: contracts between lanes

Plan: `plan.yml` in this folder. Design: `docs/investigations/project-encryption-agentic-coding-2026-11/e2b-sandbox-plan.md`.

Phase 1 shape: the model loop stays in the existing AI task (`main_processor`).
When the user has the current E2B consent, Project file tools run inline in the
chat's sandbox instead of being dispatched to a device. The sandbox runs one
program, `openmates-sandbox-host` (built from the Rust core, so it decodes and
encrypts exactly like the clients). The server never handles the Project key;
it moves only ciphertext into the sandbox and sandbox-built ciphertext
revisions out.

## 1. Key handover (Rust core, `packages/openmates-rust/src/work/projects/sandbox_key.rs`)

- Sandbox: `SandboxKeyPair::generate()` makes a fresh X25519 secret in memory
  (`OsRng`); `public_key_b64()`; never serialised or logged.
- Grant plaintext (JSON, `v: 1`): `project_key` (b64), `sandbox_id`, `job_id`,
  `project_id`, `expires_at` (unix seconds), `sandbox_public_key` (b64).
- Sealed with `crypto_box` sealed box (anonymous sender) to the sandbox public
  key; wire value `sealed_grant` = standard base64.
- Device: `seal_project_key_grant(&SandboxKeyRequest, project_key, now)`
  refuses an expired request, `expires_at > now + 24h + 300s`, or a public key
  that is not 32 bytes.
- Sandbox: `open_grant(sealed_b64, &expected_binding, now)` refuses
  `binding_mismatch` (any of sandbox_id, job_id, project_id, own public key),
  `expired`, `open_failed`; returns the key in `Zeroizing`.

WebSocket frames (main socket):

| Direction | Event | Payload |
|---|---|---|
| server → user's devices | `project_sandbox_key_request` | `request_id, job_id, sandbox_id, project_id, chat_id, sandbox_public_key, expires_at` |
| device → server | `project_sandbox_key_grant` | `request_id, job_id, sealed_grant` |
| device → server | `project_sandbox_key_decline` | `request_id, job_id, reason` (`no_key`, `expired`, `invalid`) |

The server keeps the grant in process memory only for the single POST to the
sandbox. It is never written to Redis, Directus, logs, traces or task payloads.
The request is answered by the first device that holds the Project key.

## 2. Sandbox host HTTP API (`openmates-sandbox-host serve`)

- Listens on `0.0.0.0:7787` inside the sandbox. The sandbox is created with
  public traffic off, so every request needs E2B's `e2b-traffic-access-token`
  header, plus `Authorization: Bearer $OMSH_TOKEN` (a random per-sandbox token
  the server generates and passes as env at start).
- Env at start: `OMSH_TOKEN, OMSH_SANDBOX_ID, OMSH_JOB_ID, OMSH_PROJECT_ID, OMSH_CHAT_ID`,
  optional `OMSH_TEAM_ID`, `OMSH_PROJECT_DIR` (default `/home/user/project`).
- The daemon runs as `root` (started with the E2B commands API, `user="root"`);
  model-run commands run as `user`, which has no sudo in the template, so they
  cannot read the daemon's memory or environment. The daemon drops `OMSH_TOKEN`
  from its environment at start, sets `PR_SET_DUMPABLE` 0 and chowns written
  files to `user`.
- Calls that need the key before `/v1/key` succeeded answer 409 `no_key`.
- JSON in, JSON out. Errors: HTTP 4xx/5xx with `{"error": "<code>", "detail": "..."}`.
  Details never contain file contents or key material.

| Endpoint | Body | Answer |
|---|---|---|
| `GET /v1/hello` | | `sandbox_public_key, sandbox_id, job_id, project_id, has_key, files` |
| `POST /v1/key` | `sealed_grant` | `{ok: true}`; 409 `binding_mismatch`, `expired`, `already_set`; 400 `open_failed` |
| `POST /v1/file-ids` | `items` (the Project's raw item rows, `directus.project.list_items`) | `embed_ids` of the hosted file embeds (their ids sit in Project-key-encrypted `target_id_encrypted`, so only the sandbox can read them) |
| `POST /v1/sync-in` | `heads: [head, ...]` (repeatable batches; each head is exactly `build_project_embed_head`, the daemon adds path and item from its `/v1/file-ids` map) | `written, bytes, failed: [{embed_id, reason}]` (`unknown_embed` when not in the map) |
| `POST /v1/baseline` | | `files, revision_map` (git baseline after the last sync-in batch) |
| `POST /v1/op` | `operation, arguments` | `result` (model-facing, same shape as the device executor), `revisions: [rev]` |
| `POST /v1/scan` | | `revisions: [rev]` for files changed outside ops (after commands) |
| `POST /v1/committed` | `path, embed_id, version_number` | `{ok: true}` (new base after the server committed) |
| `POST /v1/merge` | `path, head` (the newer head from another device) | `{status: "merged", revision}` (`revision` null: nothing to commit) or `{status: "conflict", conflict_text}` |

- `head` = exactly the JSON object a hosted client receives for one file head
  and passes to `decode_head` (`packages/openmates-rust/src/work/projects/hosted/io.rs`).
- `operation`, `arguments` and `result` mirror the hosted device executor in
  the Rust core (`work/projects/hosted*.rs`) and `PROJECT_FILE_TOOL_TO_OPERATION`
  (`backend/apps/ai/processing/project_file_tools.py`), so tool schemas and what
  the model sees do not change.
- `rev` = `{path, embed_id, base_version, kind: update|create|delete|move, transaction}`.
  `transaction` holds every ciphertext field of the `commit_embed_revision`
  transaction (`EmbedVersionTransactionService`) that a client fills; the
  server adds only `chat_id`, `request_id`, authorization and the server-set
  `origin: project_sandbox` (`EmbedVersionTransactionService.commit_sandbox_revision`).
  `proposal_digest` comes from the sandbox and is never recomputed. A create
  carries only the Project key wrapper; the extension accepts that only with
  the sandbox origin, which `commit()` (the device path) refuses.
- Revisions are committed strictly in order, each followed by `/v1/committed`.
- After each commit the user's devices get `embed_revision_committed`
  `{embed_id, current_revision, operation_id, chat_id, project_id, kind,
  source: "project_sandbox"}`: ids only, never a path or file text. The Rust
  core (`Client::describe_project_sandbox_commit`) checks the chat's Project
  focus, decrypts the committed head with the device's Project key and returns
  the applied-change card the shell records like a device write (web
  `projectSandboxCommitRelay.ts`), so Apply and show changes presents sandbox
  writes too. Deletes and moves show no card.
  `delete` and `move` carry `transaction = {action: delete|rename, item_id, body}`,
  applied through `apply_item_link_operation` with the routes' own checks.
- Merge: three-way, base = what the sandbox read, ours = sandbox, theirs =
  head. Clean result becomes a new rev on top of `head`'s version.

## 3. Backend

- `backend/shared/providers/e2b_project_sandbox.py`: lifecycle and
  `ProjectSandboxClient.call(endpoint, body=None) -> dict`, raising
  `ProjectSandboxError(code)`. Create from template env
  `E2B_PROJECT_SANDBOX_TEMPLATE`, `secure=True`, public traffic off, E2B
  timeout = 15 min idle, renewed on activity, on-timeout kill, never pause.
- `backend/core/api/app/services/project_sandbox_service.py`:
  `ensure_ready(...)` (find or create, key request, wait for grant up to 30 s,
  relay, sync-in, baseline) and `kill(...)`. Job record in cache holds ids,
  timestamps, sandbox id and the bearer token only. Hard maximum 4 h by
  default, 24 h opt-in (`max_lifetime_seconds`); a periodic reaper kills
  sandboxes past their maximum or whose record is gone.
- `backend/core/api/app/services/project_sandbox_writeback.py`: commits
  revs through `EmbedVersionTransactionService`; on stale base fetches the
  newer head, calls `/v1/merge`, commits the merge; a real conflict is
  returned to the model while the job runs and becomes a proposal after it
  ended. Never overwrites another device's revision.
- Billing: sandbox lifetime and code runs are billed per second
  (`backend/apps/code/app.yml`).
- Consent: `E2B_UPLOAD_CONSENT_VERSION = 2`, wording says the Project, and the
  key that opens it, are processed in an E2B sandbox in the US.
- Users without the current consent, or who declined, keep the existing device
  executor unchanged (frozen).
