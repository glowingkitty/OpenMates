# Agentic coding with encrypted Projects: what is slow, and the target design

Follow-up for Marco, 21 Nov 2026, to the [20 Nov report](report.md). Research
and planning only, no product code changed. Every claim was checked in the
code at dev `f1fc1d891c` or in dev logs. File references are
`path:line`. Points the code could not settle are marked *not verified*.

## Summary

- **The privacy design is not what makes agentic coding slow. The loop around
  it is.** Each file operation the AI makes still:
  - ends the AI task;
  - waits for the user's device;
  - starts a brand-new AI task that rebuilds the whole prompt.

  On the device side, one file read costs 5 or more sequential HTTP calls and
  about 19 database reads. A file write costs about 9 HTTP calls and 45–60
  database reads. Almost all of these fetch the same Project data again. None
  of that is needed to keep files encrypted.
- **Two corrections to my 20 Nov report.**
  - *Prompt caching is partly on*, as you thought. Gemini 3.8 Flash caches the
    fixed part of the system prompt and the tools (about 10K of about 34K
    tokens per step, 30 %). It does **not** cache the chat history, the
    changing rest of the system prompt, or the tool results.
  - *The diff edit system exists*, as you remembered. `project_update_file`
    accepts only a unified diff, and the model wrote about 350 tokens per
    step, not whole files. The many repeated updates come from re-reads after
    each edit and from the bug that loses tool results after 20 operations.
    A full-file rewrite is not the cause.
- **What is protected today:** files at rest, database backups and logs. All
  of them hold only ciphertext or no content. **What is not:** while the AI
  works, the plaintext of the files it touches is on the server:
  - in memory;
  - in the cache (test snapshots and pending writes, 15–21 minutes);
  - in the job queue;
  - at the model provider and in the E2B sandbox.

  TLS ends at Caddy, and everything behind it is plain HTTP or plain Redis
  inside the server. **New finding:** the cache writes dump files to disk
  when it stops and keeps them. Dev has 63 dump files. Any plaintext that was
  in the cache at that moment stays on disk (Task e7ec7a72).
- **Target, hosted Projects:**
  - one AI task for the whole job;
  - the user's device keeps the Project open with the keys in memory;
  - several file operations per model step;
  - small edits;
  - history caching;
  - no repeated metadata calls.

  Expected: small fix about **35 s instead of 64 s**, multi-file feature
  about **90–100 s instead of 828 s**. Overhead outside the model drops from
  about **3.6 s to about 0.5 s per file operation**. Jobs with every device
  closed still need the opt-in per-job key, which waits for your decision.
- **Target, connected machine:** the agent loop runs on the machine itself,
  like Claude Code. Files and tests stay local, and only model steps go to
  OpenMates through the existing OpenAI-compatible API. Approvals become
  rules: allowed once per repo, asking only for risky actions such as delete,
  push or network. With the same model, this reaches **within a few percent
  of Claude Code**, because each tool call costs about 0.01–0.25 s, as in
  Claude Code.
- **Order:**
  1. fix the known bugs and the rate limit;
  2. fast client executor;
  3. diff edits and history caching;
  4. one task per job (largest change, main risk);
  5. local agent for connected machines.

  About 8–12 weeks of work in total. Steps 1–3 alone should halve the
  overhead within about 3 weeks.

**Decision needed from you (unchanged):** may the opt-in per-job key (option b
in the first report) be designed for jobs that run with all devices closed?
Recommendation: yes, after step 4, opt-in per job, memory only, visible
expiry.

## Corrections to the 20 Nov report

| 20 Nov statement | Correct state | Evidence |
|---|---|---|
| "No prompt caching on the default model" | Explicit Gemini cache of system prefix + tools. 57 of 66 steps hit in the hosted multi-file run, 45 of 56 in the connected one. History not cached. | `backend/apps/ai/llm_providers/gemini_context_cache.py:1-20`; dev logs `GEMINI_EXPLICIT_CACHE` during the runs; `cached_content_token_count` 10,293 of ~32–35K prompt tokens per step |
| "Edits resend the whole file" | Update takes a unified diff only; model output median ~350 tokens per step | `backend/apps/ai/processing/project_file_tools.py:286-306`; dev usage logs of chats 7bd86254, 7a2cb6ae |
| "Encryption round trips cost 1.6–3 s per op" | 1.2–1.6 s per op measured in the runs; already fixed in the deployed version | `data/timeline-*.json` |

The `cached_content_token_count: null` you saw comes from cache misses. These
happen on the first step of a new prefix and on the about 10–15 % of steps
where the prompt has no stable prefix (`status=skipped reason=no_prefix`).

## 1. How it works today, in detail

### 1.1 Hosted Projects: one file operation, step by step

What happens between "the model calls `project_read_text`" and "the model sees
the file":

1. **Server:**
   - The model step yields the tool call. The server accepts only one file
     operation per model step. A second one in the same step is rejected with
     "Do not dispatch another operation or poll"
     (`backend/apps/ai/processing/main_processor.py:9704-9716`).
   - It stores the job and the model's arguments in the cache.
     Write arguments are plaintext with a 21-minute TTL
     (`backend/core/api/app/services/project_file_operation_service.py:145-156`).
   - It publishes a WebSocket event to the user's devices and **ends the AI
     task** (`main_processor.py:12992-13003`).
2. **Device, through the Rust core:** every step below is sequential, and there
   is no cache anywhere in `packages/openmates-rust/src/work/projects/hosted/`.
   1. Claim the job over WebSocket
      (`packages/openmates-rust/src/client/project_file_job_frames.rs:411`).
   2. `GET /v1/projects/focus/current` (`project_file_job_frames.rs:453`).
   3. `GET /v1/projects/{id}` and `GET /v1/projects/{id}/settings` to resolve
      the Project (`hosted/api.rs:103`, `projects.rs:224`,
      `adoption/link.rs:7-20`).
   4. `GET /v1/projects/{id}` **again**, for the file list (`hosted/io.rs:173`).
   5. Load the policy: `permissions.yml` and every `.gitignore`, each through
      its own `GET /v1/embeds/{id}/encrypted` (`hosted/policy.rs`,
      `hosted/io.rs:190`).
   6. The operation itself, for example `GET /v1/embeds/{id}/encrypted` for
      the file, then decrypt.
   7. Send the result over WebSocket.
3. **Server:** the WebSocket handler settles the job and starts a **new**
   `skill_ask` task:
   - The result arrives in `backend/core/api/app/routes/handlers/websocket_handlers/project_file_operation_handlers.py:147-296`.
   - `dispatch_async_skill_continuation` takes over
     (`backend/apps/ai/tasks/async_skill_continuation.py:564`).
   - It copies about 60 request fields, appends the tool result as a
     user-role message and seals private results in a memory-only handoff
     (lines ~726-935).
   - The new task restores that history
     (`backend/shared/python_utils/recent_work_summary_client.py:26-60`) and
     runs the whole pipeline again: preprocessing, prompt build, model call.

**Calls per operation type.** P is the number of policy files: one
`permissions.yml` plus each `.gitignore`.

| Operation | HTTP calls from the device | Database (Directus) reads on the server |
|---|---|---|
| read text | 5 + P | about 19 + 6P |
| list | 4 + P | about 13 + 6P |
| search | 4 + P, plus one file read per candidate (up to 100, `hosted/job.rs:6,208`) | about 13 + 6 per candidate |
| update or create | about 9 + P, plus a **new WebSocket connection** per commit (`client/hosted_file_io.rs:21-45`) | about 45–60 |
| test snapshot (N files) | one listing, then a full `hosted_file_read` per file: N × (4 + P) | N × (19 + 6P) |

Where the database reads come from. Every handler calls Directus with
`no_cache=True` and re-checks access on purpose
(`project_write_authorization_service.py:104`):

| Endpoint | Handler | Reads per call |
|---|---|---|
| `GET /v1/projects/{id}` | `routes/projects.py:792` | 4: Project, key wrappers, folders, all items |
| `GET /v1/projects/{id}/settings` | `routes/projects.py:1417` | 2 |
| `GET /v1/projects/focus/current` | `routes/projects.py:1579` → `project_write_authorization_service.py:192` | 3, plus about 3 cache calls |
| `GET /v1/embeds/{id}/encrypted` | `routes/embeds_api.py:1015` | about 6: a 3-read access check, then the embed, its keys and its diffs |
| `GET /v1/embeds/{id}/revision-receipts/{id}` | `routes/embeds_api.py:1077` | about 7, plus 3–4 cache calls |

The instrumented run matches this: 138 HTTP calls for 15 operations, 76 of them
fetching the same Project data again ([report section 3](report.md)). The calls
to `/sources`, `/embeds/chats/…` and `references/availability` are not made by
the file executor. They come from source sync and tool-result embed
persistence on the same device (*exact trigger per op not verified*).

**Rate limits make this a hard ceiling.** `GET /v1/projects/{id}` allows 60
calls per minute per IP address (`routes/projects.py:791`), and
`GET /v1/embeds/{id}/encrypted` allows 120 (`routes/embeds_api.py:1016`).

- An agent doing 20 or more operations a minute calls the Project route 40–60
  times. Dev already logged six 429 errors on it in the last 7 days.
- A test snapshot of the allowed 200 files needs about 400 Project calls.
  It cannot finish inside the limit, so the 200-file cap can't actually be
  reached today.

### 1.2 Why the task ends after every operation

- The pattern was built in May 2026 for slow external skills: social media
  and web browsing (`async_skill_continuation.py`, added in `f792ebf00e`).
- A short inline wait of 10 s was added the next day, for those two skills
  only (`main_processor.py:1366-1384`, `ASYNC_SKILL_INLINE_WAIT_SECONDS`).
- When Project file writes arrived on 23 Sep (`5fe487f43d`), they reused this
  "shared async continuation" as is. The commit message says so.
- Project tools take a separate branch (`app_id == "system"`) that never sets
  an inline-wait deadline.
- Nothing technical blocks an inline wait. The continuation branch already
  seals private results the same way (`async_skill_continuation.py:~669`).
  No document records why Project operations were excluded.

The 20-result limit follows from this design. Plaintext tool results may not
go into stored history, so every new task rebuilds them from the memory-only
handoff:
- the handoff keeps the last 19–20 entries within 195 KB
  (`recent_work_summary_client.py:36`, `async_skill_continuation.py:~880-905`);
- anything older reaches the model as "content unavailable" (Task 88fc5dfb).

### 1.3 Test snapshot

1. On the first `code-run` in a hosted Project, the server asks the device for
   a snapshot and ends the task (`main_processor.py:~9631-9715`).
2. The device lists the Project once, then reads every file through the full
   per-op chain (`client/project_file_job_snapshot.rs:56`):
   - caps are 200 files / 400 KB, checked *after* each read
     (`project_file_job_snapshot.rs:5-9,70-76`);
   - non-text files cost the full chain too.
3. The server stores the snapshot **as plaintext in the cache**:
   - 900 s TTL, deleted when read (`backend/apps/ai/processing/project_test_snapshot.py:9-20,52-76`);
   - the repeated `code-run` injects it into its arguments (`:157-176`).
4. The files then go **through the job queue** as part of the Celery task
   payload (`routes/code_execution.py:1319,1334`).
5. The worker uploads them to E2B (`backend/shared/providers/e2b_project_workspace.py:262`).

### 1.4 Connected machine

- **Same loop, one more hop.** File tools and `run_command` go through the
  same branch (`main_processor.py:9703-9860`) and end the task in the same
  way.
- **The extra hop:**
  - the requests are relayed to the machine in a sealed X25519 envelope
    (`packages/openmates-rust/src/work/projects/remote_files.rs:281`);
  - the relay polls every 250 ms (`remote_file_jobs.rs:11`), so each hop
    adds up to 250 ms.
- **On the machine**, files are read from disk under the same policy, in a
  worktree per chat (`packages/openmates-rust/src/source_host/dispatch.rs:182-552`).
  Commands run in bubblewrap, AppArmor or Seatbelt, with no unconfined
  fallback (`source_host/command_sandbox.rs:1-12`).

So a connected machine pays the full per-step task restart and queueing,
although its files never need the cloud.

**Why every command asks.**
- Under the Specification, remote commands default to "Ask first"
  (`code-run.remote.explicit-approval`, `specifications/features/app-skills/code-run/specification.yml:307`).
- The server marks a command `one_run` when either:
  - its risk is not "routine": scripts such as `npm test`, `make` or
    `python file.py` count as uninspected
    (`backend/apps/code/terminal_command_risk.py:33`);
  - or the source's write mode is `always_ask`
    (`backend/apps/code/skills/run_code_skill.py:~970`).
- A user-enabled **command preset** may pre-approve an exact command:
  - presets are defined in `.openmates/permissions.yml` and activated on the
    machine with `openmates … command-presets`
    (`code-run.remote.command-lists`, `packages/openmates-rust/src/remote_command/store.rs`);
  - this only applies when the command is "routine" (`one_run_or_preset`,
    `backend/core/api/app/services/remote_command_service.py:93`).
- `--auto-approve` in the CLI covers file writes, sub-chats and memories,
  never commands. Without an interactive terminal the CLI ends the turn as
  "needs approval" (`frontend/packages/openmates-cli/src/ws.ts:1346-1349,1807-1812`).

So `python -m unittest` in the benchmark could never run without a person,
by design.

## 2. Prompt caching, per provider

| Provider / model | System prompt | Tools | History | Source |
|---|---|---|---|---|
| Gemini 3.8 Flash (AI Studio host) | **fixed prefix only** (~10.3K tokens), explicit cache, TTL 900 s | yes, in the same cache | **no** | `gemini_context_cache.py`, wired at `backend/apps/ai/llm_providers/google_client.py:1053-1066` |
| Gemini 3.8 Flash (Vertex failover host) | no | no | no | not wired for Vertex |
| Gemini 3.5 Flash-Lite | skipped, no stable prefix | no | no | dev logs: 569 `no_prefix` skips |
| Anthropic Claude 5.5 (direct host) | automatic | by order | automatic | `backend/apps/ai/llm_providers/llm_utils.py:104-107,184-204` |
| Other Anthropic models | `cache_control` marker | no marker | last 3 long messages (4 markers max) | `anthropic_shared.py:91-113,255-305`; TTL 5 min (`backend/providers/anthropic.yml:76`) |
| OpenAI gpt-5.6+ / gpt-6 | explicit breakpoint on system prefix | by order | provider-side | `openai_client.py:55-74` |
| Older OpenAI | implicit only | implicit | implicit | no `prompt_cache_key` sent |
| Mistral, Cerebras, Together, Baseten, OpenRouter | provider-implicit with `prompt_cache_key` | provider-implicit | provider-implicit | `llm_utils.py:2445` |
| Groq | none found | none | none | — |

**Measured on dev (48 h, Gemini 3.8 Flash on AI Studio):**
- 271 of 440 calls hit the cache (62 %);
- 3.25M of 13.16M prompt tokens were cached (24.7 %).

In the benchmark chats, every logged step cached 10,293 of 32–35K tokens. The
model saw about 20K system-prompt tokens per step, and only about half of them
are the fixed prefix (`main_processor.py:4411-4425`).

**Why history is not cached.**
- Gemini 3.8 Flash never hits implicit caching, as the module's own docstring
  notes. So only what is explicitly put in `cachedContent` counts, and today
  that is only the fixed prefix plus the tools.
- The changing part of the system prompt (time, memory, focus, per-turn
  context) comes **before** the history. A cache cannot cover the history
  without also covering that part.
- The cache key includes the tool list, so a step with different tools starts
  a new cache.
- Every step runs in a new task that rebuilds the prompt. Nothing guarantees
  that history and tool results come out byte-identical, given PII
  placeholders, embed references and the private-result restore.

**What is needed for system prompt, tools and history on every step:**

1. **Order the prompt as fixed → slow-changing → history → per-step tail.**
   - fixed: base instructions and tools;
   - slow-changing: Project focus and memory, once per job;
   - per-step tail: time and current-turn context, at the end only, as the
     last user content.

   This is the precondition for every provider.
2. **Freeze one sorted tool set per job**, so the cache key stays stable.
3. **Gemini:** cache the prefix plus the history up to the previous step.
   - When the uncached tail grows past a threshold (for example 8K tokens),
     create the next cache in the background.
   - Pre-warm the first cache when the chat opens, so step 1 also hits.
   - Wire the same for the Vertex host.
4. **Anthropic:** put a marker on the last tool and on the last history block.
   Use the 1-hour TTL for agent jobs.
5. **OpenAI and others:** send a stable `prompt_cache_key` per chat to all
   models.
6. **One AI task per job (section 6).** It keeps the history in memory and
   byte-identical, which makes caching reliable.
7. **Log cached versus prompt tokens per step for every provider.**

**Expected effect.**
- Cached share goes from 30 % to about 85–90 % of input tokens.
- Gemini bills cached input at a tenth of the normal input price
  (`backend/providers/google.yml`).
- Time to first token should fall from about 3 s to about 1–1.5 s per step
  (*estimate, not measured*).

## 3. Diff edits

**The requirement:**
- *Embed diff editing*, 3 May 2026: "Instead of regenerating full content on
  every edit, the assistant outputs unified diffs"
  (`docs/architecture/messaging/embed-diff-editing.md:52`).
- *Exact patch*, 23 Sep 2026: a patch must apply exactly to its checked base,
  with no fuzzy matching and no silent whole-file overwrite
  (`projects.files.exact-patch`, `specifications/features/projects/specification.yml:427`).

**The implementation exists end to end:**
- **Model tool:** `project_update_file {path, expected_base (SHA-256), patch}`,
  with no full-content field (`project_file_tools.py:286-306`).
- **Server check:** `invalid_update_file_arguments` when `path` or `patch` is
  missing or `expected_base` is not a 64-character hash
  (`project_file_operation_service.py:600-610`).
- **Device:**
  1. `stale_base` if the file changed since the read;
  2. exact apply;
  3. repair of wrong `@@` line counts by locating the old lines verbatim;
  4. the repaired patch is stored as the revision.

  Code: `hosted/job.rs:~425-478`, `hosted.rs:237-267`, `hosted/patch_repair.rs`.

**Why the model still needs many update calls:**
- Writing a correct unified diff by hand is hard for Flash-class models. They
  get context lines or counts wrong, or send a malformed call: the connected
  multi-file run ended on `invalid_update_file_arguments`.
- Every successful update changes the file's hash. Without that new hash the
  next edit needs a fresh read, so edits come in read → update pairs.
- The tool description says only "read first, use the exact base". It gives
  no guidance on small hunks and no example (`project_file_tools.py:397-411`).
  Error codes are generic and give the model no hint how to fix the call.
- After 20 operations the earlier results are lost (Task 88fc5dfb), so the
  model re-reads and re-applies edits it has already made.

**What makes small edits the default:**

1. **Add `project_edit_file {path, expected_base, edits: [{old_text, new_text,
   replace_all?}]}`.** This is the exact-replace form that models produce
   reliably, the same idea as Claude Code's Edit tool.
   - The device turns it into an exact unified diff against the base and
     stores it through the existing revision path.
   - A missing or ambiguous `old_text` is a clear, recoverable error, never a
     fuzzy match, as the Specification requires.
2. **Keep `project_update_file` for multi-hunk diffs.**
3. **Return the new hash and the changed lines in every edit result**, so the
   next edit needs no new read.
4. **Distinct error codes with a fix hint:**
   - `missing_patch`;
   - `bad_expected_base`;
   - `content_sent_to_update`;
   - `old_text_not_found`;
   - `old_text_ambiguous`.
5. **Tool text:** prefer small edits, create whole files only for new files,
   include one short example.
6. **Let `apply_changes` take edits too.** It is the whole-file route used for
   cloud command sync-back (`project_file_operation_service.py:~672`).

## 4. Parallel and batched file reads

There is no fixed file count. Each limit below comes from a real constraint,
and the design keeps every privacy property: the device decrypts, and the
server sees only ciphertext at rest.

**Design:**

1. **The model may request several file operations in one step:**
   - reads, lists and searches;
   - writes to *different* files.

   The server sends them to the device as one job group and returns all
   results to the same task. Today the second operation is rejected
   (`main_processor.py:9704-9716`).
2. **One batch endpoint for ciphertext.** `POST /v1/projects/{id}/files/encrypted`
   takes N file ids and returns their ciphertext and wrapped keys:
   - the access check runs once per request (about 3 reads), plus one embed
     read per file;
   - today that costs about 6N reads and N HTTP calls;
   - the endpoint returns only ciphertext, as `/encrypted` does now.
3. **Job-scoped metadata on the device.** Fetch the Project, settings, focus,
   listing and policy once per job and reuse them, keyed by the Project
   revision. Refetch only when a write changes the revision or the server
   answers "stale".
4. **Results stream back one file at a time** as they finish, so a slow large
   file doesn't hold up the others.

**Limits and why:**

| Limit | Value | Why it is real |
|---|---|---|
| Per-file result size | 512 KB (existing `PROJECT_FILE_OPERATION_RESULT_MAX_BYTES`, `project_file_operation_service.py:27`) | The model can't use more per file, and it bounds a single WebSocket frame. Larger files are read by range. |
| Tokens returned per step | about 25 % of the model's *remaining* context, recomputed each step (Gemini 3.8 Flash: 1,048,576 tokens, `google.yml:69`) | Every returned token is re-sent on each later step. With history caching that costs a tenth, so the real limit is context room for the rest of the job, not a file count. |
| Bytes in flight on the device | from device memory: for example 64 MB on desktop, 8–16 MB on phones (`navigator.deviceMemory` on web, the platform equivalent on Apple) | Ciphertext plus plaintext copies held at once. It must never push a phone app into a memory kill. |
| Concurrent requests | adaptive: start at 8, double while latency stays flat, halve on 429 or rising latency | HTTP/2 through Caddy multiplexes many streams on one connection. The real limits are round-trip time, bandwidth and server rate limits, which differ per user. |
| Server rate limit | raise the per-IP limits for authenticated Project file calls, or count a batch as one call | Today's 60/min and 120/min per IP are below what one agent needs, and users behind one office NAT share them. |

**Expected effect:**
- **Search** over 100 candidates: from 100 sequential reads (about 20 s on
  dev) to a few batch calls (about 1 s).
- **Test snapshot** of 200 files: from about 1,000 sequential calls (not even
  possible within the rate limit) to about 3 calls plus local decryption.
- **Reads in one model step** run in parallel, so the step costs the slowest
  read, not the sum.

## 5. Where plaintext travels and where it rests

**Transport:**

1. Device → server is a WebSocket message `project_file_operation_result`
   over WSS (`routes/websockets.py:179-183`, handler `:147-160`).
2. **TLS ends at Caddy** (`deployment/prod_server/Caddyfile:5,77`).
3. Caddy → api is **plain HTTP on loopback** (`reverse_proxy localhost:8000`,
   `Caddyfile:272,377`, port bound to `127.0.0.1`,
   `backend/core/docker-compose.yml:39`).
4. **Inside the Docker network everything is plain:**
   - worker → api for the private handoff:
     `http://api:8000/internal/recent-work/…` with an internal token
     (`recent_work_summary_client.py:205-225`);
   - api and workers → cache and job queue: `redis://…@cache:6379`, password
     only, no TLS (`backend/core/api/app/tasks/celery_config.py:328-329`).
5. Outbound:
   - to the model provider over HTTPS
     (`https://generativelanguage.googleapis.com/…`);
   - to E2B through its official SDK, HTTPS by default
     (*SDK setting not checked*).

**Where file plaintext exists:**

| Data | Where | How long | Protected by |
|---|---|---|---|
| File at rest | Directus (database) | permanent | client-side encryption: ciphertext only |
| Model's write arguments (the new content or patch) | cache key `project_file_operation:payload:*` | until settled, at most 21 min | cache password; **plaintext** (`project_file_operation_service.py:150-154`) |
| File read results handed to the next task | api process memory (`TransientContextHandoffStore`) | 20–90 min | encrypted with the user's Vault key; only a reference goes through the queue (`backend/shared/python_utils/recent_work_summary_cache.py:287-355`) |
| Same results while a task runs | worker process memory | the task's run | process isolation only |
| Test snapshot | cache key `project_test_snapshot:*` | at most 15 min, deleted when read | cache password; **plaintext** (`project_test_snapshot.py:9-20`) |
| Test snapshot as code-run payload | Celery job queue (in the same cache) | until a worker takes it, normally under a second | cache password; **plaintext** (`routes/code_execution.py:1319`) |
| **Cache dump files** | `/data` volume of the cache container | **indefinitely** | file permissions only. Dragonfly's default dump-on-shutdown is active: no `--dbfilename` override in `docker-compose.yml:1150-1172`. Dev holds 63 dumps, 2 GB, from 9 Aug to 5 Sep (Task e7ec7a72). |
| Model request | model provider | per the provider's retention | HTTPS; provider terms |
| Test files | E2B sandbox | sandbox lifetime (≤ 60 min) | sandbox isolation; E2B terms |
| Logs | Caddy access logs, OpenObserve | — | **no content logged**. Handlers log codes and sizes only (`project_file_operation_handlers.py:160-164`); WebSocket spans read only the trace header from the payload (`backend/shared/python_utils/tracing/ws_span_helper.py:68-110`). |

**In plain words:**
- **Protected:**
  - a stolen database or database backup reveals no file contents;
  - logs reveal no file contents;
  - nobody at OpenMates can open a Project the AI is not working on.
- **Not protected:**
  - anyone with root on the live server can read the files the AI is
    currently working on: in memory, in the cache, in the queue, and on the
    plain internal network;
  - a copy of the cache taken during a job reveals that job's pending writes
    and test snapshot;
  - because of the dump files, such a copy also exists on disk after any
    cache restart.

  This is inherent to "the server-side model reads the file", and the privacy
  promise should say so in plain words.
- **Narrowing it further, without weakening the encryption:**
  - stop cache dumps, or encrypt those two cache values with the user's Vault
    key, as the handoff already does (Task e7ec7a72);
  - pass the snapshot to the worker as an encrypted reference, not as a queue
    payload;
  - with one task per job (section 6), results stay in that task's memory
    only.

## 6. Target architecture and user flow

### 6.1 Hosted (cloud) Projects

**Flow for the user:**
1. They ask for a change in a Project chat.
2. Their open app (web, desktop, phone in the foreground) shows
   "Working in *Project name*".
3. Edits appear live as diffs, and the job finishes in one turn.
4. If they close the app, the job pauses with a clear "continue on any
   device" notice. It does not fail silently. Once you decide on it, a job
   could instead run on with the opt-in per-job key.

**How it works:**

1. **One AI task per job.**
   - The task stays alive while it waits for the device. File results come
     back to *that* task in memory, with no rebuild, no handoff and no
     20-result limit.
   - This extends the existing inline-wait mechanism
     (`main_processor.py:1366`) to Project operations, with a longer
     deadline.
   - Waiting must not block a worker slot. The wait has to be async in the
     worker, or the job needs its own pool. This is the main engineering risk.
   - If the device disconnects for longer than a grace period (for example
     60 s), the task saves its state once, through the existing continuation,
     and pauses.
2. **The device keeps the Project open for the job:**
   - keys and metadata in memory, fetched once;
   - one WebSocket for the whole job instead of one per commit.
3. **Several operations per step**, with the batch endpoint and the limits in
   section 4.
4. **Small edits** with `project_edit_file`; every result returns the new hash.
5. **History caching**, as in section 2.
6. **Tests:**
   - the snapshot is built with one listing and batched reads;
   - it reaches the sandbox as an encrypted reference;
   - later test runs in the same job send only the changed files.

**Expected speed against the benchmarks** (same Gemini model, estimates from
the measured split):

| Run | Today | Target | Where the gain comes from |
|---|---|---|---|
| Small fix (4 ops, 5 steps) | 64 s | about 35 s | setup 7.9 → 1.5 s, client 6.5 → 2 s, model 39.6 → about 20 s (cache, 4 steps), answer post-processing ~10 s unchanged |
| Small fix under load | 389 s | about 35–40 s | no new task per operation, so no queue wait between steps |
| Multi-file feature (53 ops, 48 steps) | 828 s | about 90–100 s | no 20-result loss, so about 15 steps instead of 48; parallel reads; edits without re-reads |
| Test-and-fix loop | did not finish | about 60–80 s | snapshot about 3 calls; changed files only on reruns |
| Overhead outside the model per tool call | about 3.6 s | about 0.5 s | — |

### 6.2 Connected machine

**Flow for the user:**
1. They run `openmates remote-access` (or later a desktop app) on their
   machine.
2. They chat from any device.
3. The machine works on the files directly, runs tests locally and shows
   progress.
4. The first time a repo is attached, the user approves its rules: which
   commands are allowed. After that it asks only for risky actions.

**How it works:**

1. **The agent loop runs on the machine:**
   - in the Rust CLI core, with local tools: read, search, edit, run;
   - tool calls cost about 0.01–0.25 s, as in Claude Code.
2. **Model steps go to OpenMates** through the existing OpenAI-compatible
   `/v1/chat/completions`. It already returns client tool calls without
   running OpenMates skills, and is documented for "external SDKs and agentic
   tools" (`backend/core/api/app/routes/openai_compat.py:1-7,573`).
   - OpenMates still provides model choice, billing, PII handling and the
     system prompt, through a coding-agent profile on that route.
   - The server sees the prompt for each step, exactly as today.
   - It stores nothing in plaintext: the chat is saved client-encrypted
     through the existing sync.
3. **One loop for the whole job**, with no task restart and no queue between
   steps.
4. **Rule-based approvals**, extending the existing exact-match command
   presets (`code-run.remote.command-lists`):
   - The user enables command classes once per repo, for example "tests",
     "linters" or "build".
   - These always ask, every time:
     - deleting files outside the worktree;
     - `git push` and other remote writes;
     - network access beyond the declared package registries;
     - writing outside the repo or its worktree;
     - anything the risk check calls non-routine.
   - Each rule records who enabled it and can be revoked.
   - Repo files can only *propose* rules, never activate them, as the
     Specification already requires.
5. **Tests run locally** in the existing sandbox (bubblewrap, AppArmor,
   Seatbelt).

**Expected speed:**
- Small fix: about 25 s on Gemini Flash. Overhead per tool call is about
  0.01–0.25 s, as in Claude Code.
- Test-and-fix loop: about 50–70 s. Local test runs take about 0.3 s each, as
  in Claude Code.
- On the same model as Claude Code, total time should be within a few
  percent, because both run the same kind of loop.

### 6.3 Implementation plan

| Step | What | Effort | Risk | Expected gain (benchmarks) |
|---|---|---|---|---|
| 1 | Known bugs: 20-result loss (88fc5dfb), wait email (2d967ff7), CLI not returning (763dc27d), cache dumps with plaintext (e7ec7a72), Project route rate limit vs agent load | 1 week | low | multi-file 828 s → about 250–300 s (no repeated work) |
| 2 | Fast client executor: job-scoped metadata cache in the Rust core, no duplicate settings/focus/listing calls, one WebSocket per job, batch ciphertext endpoint, snapshot with one listing | 1–2 weeks | low; client-only plus one read-only endpoint, no key changes | client time per op 1.2–1.6 s → about 0.3–0.5 s; snapshot feasible at 200 files |
| 3 | Edits and caching: `project_edit_file`, new hash in results, error hints, prompt order fixed → slow → history → tail, frozen tool set, Gemini history cache, Anthropic tool marker, cache logging | 1–2 weeks | low–medium (prompt changes need AI quality checks) | about 30 % fewer steps; time to first token about 3 s → 1–1.5 s |
| 4 | One AI task per job: inline wait for Project operations, async waiting without blocking worker slots, several operations per step, results kept in task memory, grace-period pause | 3–4 weeks | **medium–high**: AI pipeline, worker capacity, streaming and recovery semantics; needs a Plan and Specification updates (`projects.files.wait-expiry`, the continuation contracts) | removes setup and queue per step; small fix about 35 s, multi-file about 90–100 s |
| 5 | Connected machine local agent: loop in the Rust CLI over `/v1/chat/completions`, local tools, encrypted chat sync, repo rules for approvals, local tests | 3–4 weeks (parallel to 4) | medium: new client surface, approval UX, keeping CLI, web and Apple status in sync | within a few percent of Claude Code on the same model |
| 6 | Opt-in per-job key for jobs with all devices closed | 2–3 weeks | high (privacy promise) | — **needs your decision** |

Steps 1–3 need no change to the privacy promise and deliver most of the
non-model gain within about 3 weeks. Step 4 is the one that changes the
architecture. Step 5 can start in parallel because it barely touches the
server pipeline.

## 7. How the architecture came about

| Date | Change | Commit / source |
|---|---|---|
| 12–13 May 2026 | Async skill continuation, built for slow social-media and browse skills; 10 s inline wait for those only | `f792ebf00e`, `06f4ed57b1` |
| 1 Sep | Remote sources plan: read-only, writes and commands "later phase", diffs as proposals | `docs/plans/projects-remote-sources/plan.yml:135-139` |
| 23 Sep | File writes and remote commands, reusing the "shared async continuation"; exact per-command approval; unified-diff update tool | `5fe487f43d` |
| 5 Oct | Memory-only, Vault-encrypted private handoff, so plaintext results survive the task restart | `e10c7f5afc` |
| 10–12 Nov | Rust hosted-file executor; test snapshot fetched from the client and kept as plaintext in the cache | `bf579b3c4e`, `170da82264` |
| 15 Nov | Explicit Gemini cache for the fixed prompt prefix | `4e214b9f90` |

**What went wrong, and how to avoid it next time:**

1. **A one-shot chat pipeline was stretched into an agent loop, one feature at
   a time.**
   - Each step was reasonable on its own: reuse the continuation, add a
     handoff, add a cache.
   - Nobody designed the loop itself. The 20-result limit, the task restart
     per operation and the uncached history all follow from that.
   - Avoid it: give agent loops their own design, with a Plan covering the
     whole loop, before adding tools to it.
2. **Each step was secured carefully, but no step had a speed budget.**
   - The readiness Plan for agentic coding (`docs/plans/native-agentic-coding-readiness/plan.yml`)
     sets latency budgets only for PII scanning. There is none per tool call
     or per step.
   - The E2E tests prove correctness, not cost.
   - Avoid it: add a per-tool-call overhead budget to the Specification (for
     example ≤ 0.5 s hosted, ≤ 0.3 s connected), plus a benchmark in CI like
     the harness in this folder.
3. **The client executor was built as independent, self-checking calls.**
   - Each operation re-resolves the Project, settings, focus and policy for
     safety. Batching was never a requirement.
   - Avoid it: make "job-scoped state, re-checked on revision change"
     the default contract for clients that execute AI jobs.
4. **Requirements that existed were not wired end to end.**
   - The diff tool exists but nothing steers the model to use it well.
   - The cache exists but covers only the system prefix.
   - Avoid it: every architecture requirement needs a check that measures
     its effect, for example "edits under 2 KB" or "cached share above
     80 %", not only that the code exists.

## Appendix

- **Benchmarks, harness and data:** [report.md](report.md), [`harness/`](harness/), [`data/`](data/).
- **Not verified:**
  - which device code path triggers the `/sources` and embed-persistence calls;
  - the E2B SDK's TLS setting;
  - production cache dumps (no prod access in this review);
  - the speed figures in section 6, which are estimates from the measured
    split, not runs.
- **Tasks from this review:** 88fc5dfb (20-result loss), 2d967ff7 (wait
  email), 763dc27d (CLI not returning), e7ec7a72 (cache dumps).
