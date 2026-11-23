# Client-side encrypted Projects and agentic coding: speed, security, options

Research report for TASK-1063, 20–23 Nov 2026. Measured on dev with synthetic
repositories and throwaway accounts. No product code was changed. The raw
numbers, the harness and how to rerun it are in [`data/`](data/) and
[`harness/`](harness/).

> **Correction, 21 Nov.** Two statements in the first version were wrong:
> prompt caching *is* on for the default model (system prefix and tools, about
> 30 % of tokens, history not cached), and edits *are* unified diffs (about
> 350 output tokens per step). Details and the target design:
> [follow-up-target-architecture.md](follow-up-target-architecture.md).

## Summary

- **Today, a coding task in an OpenMates hosted Project takes 4–25 times as long
  as the same task in Claude Code.** Small fix: 64 s vs 13–14 s. Multi-file
  feature: 828 s (hosted) and 696 s (connected machine) vs 27–35 s. The
  test-and-fix loop did not complete in either OpenMates mode from the CLI
  (hosted: the test snapshot is never answered; connected machine: each command
  waits for a person to approve it), against 53–64 s in Claude Code.
- **Encryption round trips are not the main cost.** The wait for the
  user's device to decrypt or encrypt a file is about **1.2–1.6 s per file
  operation** (about 9 HTTP calls), or **5–15 % of the wall time** in our runs. Claude Code needs
  about 0.01 s for the same local file operation. Running tests from a hosted
  Project costs more: about **7 s per command**, because the device has to
  decrypt a snapshot of the whole Project first.
- **Most of the time goes to things that work the same with or without
  encryption:**
  - each file operation ends the AI task and starts a new one, which rebuilds
    the 24–33K-token prompt (about 1.5 s per operation);
  - prompt caching covers only the fixed system prefix and tools (about 30 %
    of each step's tokens), not the history (about 3 s to the first token);
  - edits are diffs, but the model re-reads after each edit and retries
    malformed diffs;
  - only one file operation runs per model step.
- **Under load the step-by-step design gets much slower.** Every file
  operation queues a new AI task. With about 15 other chats on dev, those
  queue waits grew to 5–39 s each and took 19–45 % of the time (a small fix:
  389 s instead of 64 s).
- **Two bugs make long tasks much slower and partly explain the 828 s run.**
  - After about 20 file operations, the AI loses its earlier private file
    results. It then repeats edits it has already made (Task 88fc5dfb).
  - The 10-minute "still waiting" email never goes out (Task 2d967ff7).
- **Recommendation: keep client-side encryption as the default, and fix the loop
  and the client executor first (option a).** This removes most of the
  non-model overhead (from about 4.5 s to under 1 s per file operation) without
  changing the privacy promise. Treat the user's own connected machine as the
  main mode for serious coding.
- **What option (a) cannot fix:** jobs that keep running while every device is
  closed (overnight, phone in pocket). The only credible ways to do that are a
  time-limited key the user hands over for one job (b) or server-held keys (c).
  Both weaken today's promise and need Marco's explicit decision. I recommend
  (b) as an opt-in per job if that use case is needed for launch, and never (c)
  as a default.
- **"Within a few percent of Claude Code" is reachable only for the
  non-model overhead, not for total time.** Total time is dominated by the
  model (step speed, prompt size, how many steps it takes). That differs between
  Gemini Flash and Claude Sonnet whatever the encryption design. I propose
  measuring the target as *non-model overhead per tool call ≤ 0.3 s* on the same
  model.

**Decision needed from Marco:** may option (b), a time-limited per-job key
handed to the server, be designed as an explicit opt-in for long or overnight
jobs? It means the server can decrypt that Project's files while the job runs.
Recommendation: yes, but only after option (a) ships, opt-in per job, memory
only, with a visible expiry. Until then, long jobs need an open device or a
connected machine.

## 1. How it works today, end to end

Verified in code at `e8f9f6fc33` (dev, 20 Nov).

### Keys and storage

Each Project file is an embed. Its content is encrypted with a per-file embed
key, and that key is wrapped by the Project key. The Project key is wrapped on
the client. The server stores only ciphertext and has no decryption authority
(`projects.files.no-server-decryption-authority`).

### What one AI file operation does

The AI cannot read a file itself, so every file tool call becomes a job for the
user's device:

```
model step ──tool call──▶ main processor (Celery task)
                            │ creates operation in Redis, 90 s lease
                            │ pushes  project_file_operation_available ──▶ client
                            │ ENDS the AI task ("yielding to client completion")
client ── claim ─────────────▶ server ── request (arguments) ──▶ client
client: resolve Project ─ GET /v1/projects/{id}           (all items, decrypt)
        settings        ─ GET /v1/projects/{id}/settings  (decrypt)
        list            ─ GET /v1/projects/{id}           (again, decrypt metadata)
        policy          ─ GET .gitignore chain + .openmates/permissions.yml heads
        the op itself   ─ read:  GET /v1/embeds/{id}/encrypted, decrypt
                          write: GET focus, [POST approval], chat key, GET receipt,
                                 GET head, encrypt, POST commit
client ── result (plaintext for the model) ──▶ server
server: settles the result, then starts a NEW skill_ask Celery task with the whole
        history, rebuilds the system prompt (~79K chars), tools and context,
        then calls the model again
```

Sources:
- `packages/openmates-rust/src/client/project_file_jobs.rs` (frame protocol);
- `src/work/projects/hosted/api.rs:108` (`hosted_run`);
- `hosted/job.rs`, `hosted/io.rs` and `hosted/policy.rs`;
- `backend/apps/ai/processing/main_processor.py` (dispatch and break after the op);
- `backend/apps/ai/tasks/async_skill_continuation.py` (`dispatch_async_skill_continuation`).

The web Worker (Rust core via wasm), the native CLI (Rust) and the npm CLI (old
TypeScript executor, kept as a fallback) all follow this pattern.

### Sequential requests per operation

Counted from the code. The client makes no parallel calls within one
operation.

| Operation | WebSocket hops | HTTP requests | At 25 ms RTT (home) | At 120 ms RTT (mobile) |
|---|---|---|---|---|
| list, read | 3 | 4–6 | ~0.2 s | ~1.0 s |
| search (content) | 3 | 4–6 + one per examined file, up to 100 | ~0.2 s + 25 ms × files | ~1 s + 0.12 s × files |
| create / update | 3 | 9–12 | ~0.3 s | ~1.5 s |
| snapshot for a test run (N files) | 3 | ~5 per file, sequential | 200 files: ~25 s | 200 files: ~2 min |

The network time comes on top of the server-side time measured below. Our runs
were on the dev host itself, so network RTT there was about 0.

### Running tests from a hosted Project (`code-run`, target E2B)

1. The model asks to run a command.
2. The server first sends a `snapshot` job to the client. The client decrypts
   every text file, at most 200 files / 400 KB (`project_file_job_snapshot.rs`).
3. The client calls `hosted_file_read` once per file, and every call lists the
   whole Project and reloads the policy again. That is N full listings, so the
   work grows with N².
4. The server parks the snapshot **as plaintext in Redis** for up to 15 minutes,
   read once (`backend/apps/ai/processing/project_test_snapshot.py`).
5. A new AI task starts and the model repeats the call.
6. The E2B workspace syncs only changed files and runs the command. It is kept
   per user + chat + Project, 15 minutes idle / 60 minutes in total.
7. Changed files go back through an `apply_changes` job (at most 20 files,
   256 KB each), followed by another new AI task.

So for tests, plaintext of the Project already exists on server-side
infrastructure: in Redis, and in E2B for up to 60 minutes.

### What the protection actually covers today

- **A breach of stored data** (database, S3, backups) exposes no file content.
  This holds today, and it is the main value of the design.
- **Someone with live access to the running server** sees everything the AI reads
  or writes during jobs (tool results are plaintext for the model), test
  snapshots in Redis, and E2B workspaces. They do not see files the AI never
  touched.

Every alternative below should be judged against this real baseline, not
against "the server never sees plaintext".

## 2. Where the time goes (real dev traffic)

Source: OpenObserve logs on dev covering 197 file operations in 23 chats over
the last 3.5 days, and 485 dispatches over 7 days. Analysis script:
`harness/analyze_logs.py`.

| Stage of one file-operation cycle | Median | p90 | Depends on encryption? |
|---|---|---|---|
| A. Op dispatched → client result settled → next task queued | 2.9 s | 7.7 s | **yes**: only the device can read or write |
| B. Celery pickup of the new task | 0.01 s | — | no |
| C. New task setup before the model call (history, private context, prompt, tools) | 0.5 s + ~0.8 s | — | no: comes from ending the task per op |
| D. Model step until the next tool call (includes C) | 4.6 s | 8.1 s | no |
| **E. Full cycle per file operation** | **7.0 s** | **12.4 s** | |

Client round trip (A) by operation type:

| Operation | n | Median A |
|---|---|---|
| list | 97 | 1.6 s |
| read_text | 70 | 1.8 s |
| search | 15 | 2.5 s |
| update | 10 | 3.0 s |
| commit | 15 | 3.2 s |
| create | 67 | 3.2 s |
| snapshot (test run) | 76 | 7.3 s |

Even with zero network latency, a read takes 1.6–1.8 s. The cost is the 4–6
sequential API calls, each doing its own Directus lookups (we saw about 10
`GET /items/projects` per second during one read). It is not the cryptography.
AES-GCM over a few kilobytes takes microseconds.

One traced continuation (model step) breaks down as:
- restore of the private context: 0.22 s;
- app instructions: 0.56 s;
- agentic context: 0.5 s;
- model request sent 1.36 s after the step started;
- time to first token 3.05 s for 24K input tokens; this step missed the
  prompt cache (`cached_content_token_count: null`). Most steps hit it for
  about 10K tokens (see the correction note at the top).

## 3. Benchmarks

### Setup

- **Repository:** the same synthetic repo for all runs, `textstats`: 6 files with two
  planted bugs (`harness/seed/`, stored with a `.seed` suffix so the repo gates do not collect its tests).
- **Tasks:**
  - **small fix:** `count_words` miscounts newlines;
  - **multi-file feature:** add `top_words` across 4 files, with tests;
  - **test-and-fix loop:** run the tests, fix what fails, run again.
- **OpenMates:**
  - dev, throwaway account (deleted after the run), npm CLI as the client
    executor on the dev host, `@Gemini-3.8-Flash` as the project rules require;
  - *hosted*: files in a client-encrypted hosted Project;
  - *connected machine*: the repo on the dev host, attached with
    `openmates remote-access --enable-commands`.
- **Claude Code:** CLI 2.1.220, Claude Sonnet, `claude -p` in a git copy of the same
  repo, two runs.

The models differ, so totals are not directly comparable. The fair comparisons
are the time spent outside the model and the number of steps.

### Results

| Task | OpenMates hosted | OpenMates connected machine | Claude Code (Sonnet) |
|---|---|---|---|
| Small fix | **64 s**, 4 file ops, 5 model steps | **edits done in 78 s**, 8 ops; final answer then failed (see below) | **13–14 s**, 3–5 tool calls |
| Multi-file feature | **828 s**, 53 tool calls (24 reads, 15 updates, 11 searches, 3 lists), 48 model steps | **server done after 696 s**, 35 tool calls (17 reads, 10 updates, 6 searches), 30 model steps; the last edit was rejected (`invalid_update_file_arguments`) and the CLI never returned (stopped at 960 s) | **27–35 s**, 10–14 tool calls |
| Test-and-fix loop | **did not finish**: the first test run asks the client for a Project snapshot, the npm CLI never answers it, and the turn hung until the harness stopped it at 960 s | **stopped after 43 s waiting for a person**: `--auto-approve` does not approve commands on a connected machine, so each test run needs an interactive approval (`ws.ts`, `remote_command_review_deferred`) | **53–64 s**, 13–14 tool calls (3–4 test runs) |

Where the time went:

| Run | Model | Setup per new task | Client round trips | Server dispatch | Other / tail |
|---|---|---|---|---|---|
| Hosted small fix (64 s) | 39.6 s (62 %) | 7.9 s (12 %) | 6.5 s (10 %), 1.6 s per op | 0.3 s | ~10 s answer post-processing |
| Connected small fix (edits, 76 s) | 53.4 s (70 %) | 9.2 s (12 %) | 11.5 s (15 %), 1.4 s per op | 0.6 s | — |
| Hosted small fix, 2nd run under load (389 s) | 137 s (35 %) | 24 s (6 %) | 21 s (5.5 %), 1.4 s per op | 1 s | **queue 176 s (45 %)**: waiting for a free AI worker |
| Connected multi-file (696 s) | 463 s (66 %) | 37 s (5 %) | 42 s (6 %), 1.2 s per op | 2.4 s | queue 135 s (19 %) |
| Hosted multi-file (828 s) | 655 s (79 %), 13.6 s per step | 70 s (8.5 %) | 62 s (7.5 %), 1.2 s per op | 3.4 s | ~22 s answer post-processing |
| Claude Code small fix (13 s) | ~12 s | — | **0.1 s in total** for all tools | — | — |
| Claude Code multi-file (27 s) | ~26 s | — | **0.2 s** | — | — |
| Claude Code test loop (53 s) | ~49 s | — | **2.2–2.5 s**, 0.25 s per test run | — | — |

What the numbers show:

1. **Encryption round trips cost 5–15 % of a file-editing task.** Removing
   them entirely, with the server reading files itself in about 50 ms, would save
   6–11 s of a 64–78 s small fix. Every slow-network second per operation comes
   on top (see the table in section 1).
2. **Restarting the AI task for every operation costs about as much as the
   encryption round trip**, 1.3–2.5 s per step. This restart does not depend on
   encryption.
3. **The model steps are long, about 8 s, against about 3 s in Claude Code.**
   Contributing factors:
   - the prompt is large (24–33K input tokens per step) and only about 30 %
     of it is cached;
   - edits are unified diffs, but each one needs a fresh read first;
   - the model often repeats `update_file`: five times in the connected small
     fix and many times in the multi-file run.
4. **The multi-file run spiralled because of a bug, not because of
   encryption.** After 20 file results, the continuation hands over only the
   first 20 private tool results (`recent_work_summary_client.py:36`,
   `entries[:20]`, plus a 195 KB budget). Later results reach the model as
   "Private Project tool content is unavailable", and it redoes its edits. This
   warning appeared 22 times on dev from 14 to 20 Nov.

   The bug does come from the encryption design: plaintext tool results may not
   be stored in server history, so every new task rebuilds them from a capped,
   memory-only handoff. Keeping one AI task alive across operations (option a)
   removes the need for that handoff.

5. **Under load, the task-per-operation design adds queueing.** The second
   small-fix run (15 file ops) took 389 s instead of 64 s. Each new continuation
   task waited 5–39 s for a free AI worker, growing over the run, while the
   other benchmarks and about 15 agent chats ran on dev. Claude Code keeps one
   loop and never re-queues.

### HTTP calls per operation (instrumented run)

The npm CLI was run with a `fetch` logger (`harness/fetchlog.mjs`) for the
second small fix: 15 file ops, **138 HTTP calls, 27.6 s of sequential request
time** (median ~190 ms each, dev host to dev API).

| Request | Calls | Time | What it is |
|---|---|---|---|
| `GET /v1/projects/:id` | 21 | 4.6 s | Project resolve and file listing, fetched again for every op |
| `GET /v1/projects/focus/current` | 23 | 3.4 s | focus check before writes |
| `GET /v1/projects/:id/settings` | 17 | 3.2 s | write policy, every op |
| `GET /v1/projects/:id/sources` | 15 | 3.0 s | source lookup, every op |
| `GET /v1/embeds/:id/encrypted` | 20 | 3.9 s | the encrypted file itself |
| `GET /v1/embeds/chats/:id/embeds/:id` | 12 | 3.1 s | embed key and metadata |
| `GET /v1/embeds/:id/revision-receipts/:id` | 9 | 2.0 s | write receipts |
| other (availability, auth, tasks, apps, …) | 21 | 4.4 s | |

So **about 9 calls and 1.8 s per op**. More than half (76 calls, 14 s) fetch the
same Project metadata again on every op. That metadata could be cached for the
length of a turn without touching the keys or the privacy promise. Only the
encrypted file and its key (about 3 calls) are needed per op.

### Baseline "without encryption round trips"

This baseline is modelled from the measured split, because no build of
OpenMates reads files on the server.

| Task | Measured | Encryption round trips replaced by ~50 ms server reads | Also no task restart (inline wait) | Also prompt cache + diff edits (estimate) |
|---|---|---|---|---|
| Hosted small fix | 64 s | ~58 s (−10 %) | ~52 s (−19 %) | ~35–40 s |
| Connected small fix (edits) | 76 s | ~65 s (−15 %) | ~57 s (−25 %) | ~40 s |

Even with no encryption at all, the same loop and model would still take
about 4× as long as Claude Code. The encryption design is a real but secondary
cost. The loop design and the model step dominate.

## 4. Edge cases

Verified in code and the Projects Specification
(`specifications/features/projects/specification.yml`).

| Situation | What happens today | Severity |
|---|---|---|
| **Tab closed** | No executor, so the next file op waits. After 10 min, one reminder email is due (`projects.files.wait-email`). After 20 min, the run pauses and needs an explicit resume (`wait-expiry`). Waiting spends no model tokens. **Bug:** the reminder email never goes out on dev. Its Celery task goes to the `email` queue, but only the `persistence` worker imports it: 567 `TASK_UNKNOWN` errors in 7 days, 0 sent (Task 2d967ff7). | High for long jobs |
| **Phone in the background** | The Apple app runs file jobs only for the active chat on an open socket (`ProjectWorkspaceReviewRuntime.swift`). iOS suspends the socket within seconds, so this is the same as a closed tab. | High on mobile |
| **Slow network** | Every operation makes 6–15 sequential round trips (section 1). At 120 ms RTT that adds about 1 s per read and 1.5 s per write. A 200-file test snapshot takes about 2 minutes. Nothing is batched or parallel. | Medium (desktop), high (mobile) |
| **Several devices** | Only one client claims each job (90 s lease). Another logged-in device is **not** automatically an executor (`executor-wait`), so with the laptop asleep, an open phone in another chat does not help. | Medium |
| **Large repos** | Content search examines at most 100 files in name order and marks the result `truncated` (`job.rs:214`). On a 1,000-file repo, most files are never searched. Listing caps at 500 entries. Test snapshots cap at 200 files / 400 KB, so tests on a bigger repo run on a partial copy, with confusing failures. Sync-back caps at 20 changed files. Snapshot cost grows with N². | High for real repos |
| **Long jobs overnight** | Impossible unless a device stays awake and online with the chat open. The 20-minute pause stops the run. E2B workspaces end after 60 minutes. | Blocker for "agent works while I sleep" |
| **Connected machine offline** | Jobs for that source are answered `waiting_for_executor` (`source_offline`), and the same 10/20-minute deadlines apply. Files stay on the machine. Nothing else can take over. | Expected |
| **Two chats on one Project** | Writes are checked per file against the base revision. A stale write must re-read, with a recovery budget of 3 (`concurrent-chat-safety`). There is no isolation across files: chat A can read a mix of files from before and after chat B's edits. Connected machines use a worktree per chat, which isolates better. | Medium |
| **More than 20 file ops in one turn** | Earlier private results are lost and the model repeats its work (Task 88fc5dfb). | High |
| **Final answer contains a code block** | Once on the connected-machine run, the final answer failed (`Finished embed recovery save failed`). The CLI then kept waiting past its own 15-minute timeout (Task 763dc27d). 3 occurrences in 48 hours. The CLI also never returned after the connected multi-file turn ended on a rejected edit. | Medium |
| **Commands on a connected machine, unattended** | Every command needs a person to approve it; `--auto-approve` covers file writes only. A test-and-fix loop cannot run unattended from the CLI. | High for agentic test loops |

## 5. Alternative architectures

Scores: speed per file operation (non-model overhead); breach security against
(i) a dump of stored data and (ii) a live attacker on the server.

### (a) Current design, optimised (no change to keys)

Changes, all within today's promise:

1. **Keep the AI task alive while the client works.** Wait inline in the main
   processor, as `web.browse` already does with a 10 s inline wait
   (`ASYNC_SKILL_INLINE_WAIT_SECONDS`), instead of ending the task and starting
   a new one. This saves about 1.5 s per operation, keeps tool results in memory
   (removing the cause of the 20-entry bug) and makes prompt caching effective.
2. **Turn cache in the client executor (Rust core).** Resolve the Project and
   load settings, listing and policy once per turn, then invalidate on the
   Project's revision. This takes a read from 4–6 calls to 1. Writes still
   validate the base revision, so concurrent-chat safety is unchanged.
3. **Decrypted file cache for the job, in memory only and zeroized at turn
   end, plus prefetch** of the tree when the Project is focused. Search and
   snapshots then become local: full-repo search with no 100-file cap, instant
   snapshots with no N² listings, and parallel fetches instead of sequential
   ones.
4. **Batching.** Run several read-only tool calls from one model step together
   (the model already emits several), and use one `apply_changes` for
   multi-file writes.
5. **Not encryption-related, but needed for the target:** prompt caching on the
   default model extended to the history, and an exact-replace edit tool next
   to the existing unified-diff tool.

| | |
|---|---|
| Speed | Non-model overhead from ~4.5 s to ~0.5–1 s per op (dev host). Slow-network penalty from ~1–1.5 s to ~0.1–0.3 s per op. Test snapshots go from N² to near zero after prefetch. |
| Security (i) stored-data breach | Unchanged: safe. |
| Security (ii) live server attacker | Unchanged. |
| Privacy promise | Unchanged. |
| Still impossible | Jobs with every device closed. |
| Effort | Medium: core executor cache and prefetch, about 1–2 weeks; inline wait in the main processor, about 1 week; prompt cache and diff tool, a few days each. |
| Risk | Low to medium: cache invalidation, memory on large repos (bound it), web Worker memory budget. |

### (b) Time-limited per-job key handed over by the client

The client creates a fresh job key and re-wraps the embed keys of the
Project's files under it. It hands the job key to the server's job runner for a
fixed time (for example 2 hours), memory-only, through the existing transient
IPC and never Redis or the database. Files stay encrypted at rest.

For new or changed files, the server encrypts with new embed keys sealed to a
per-Project **write-only public key**. The server can create files it cannot
read back after the job, and the client re-wraps them on its next visit.

| | |
|---|---|
| Speed | Best: file ops become local server reads (~5–50 ms). Works with the tab closed, the phone in the background and overnight, within the key's lifetime. |
| Security (i) stored-data breach | Still safe if the key never touches storage. |
| Security (ii) live server attacker | Worse: during a live job they can decrypt **every** file of that Project, not only what the AI reads. The exposure is bounded by job duration and scope. |
| Privacy promise | Changes from "the server can never decrypt your Project files" to "only while a job you started runs, with a key that expires". **Breaks `projects.files.no-server-decryption-authority`**, so it needs a Specification change and Marco's consent. |
| Effort | High: delegation protocol, expiry and revocation, write-only key, re-wrap on return, audit log, consent UI, tests. About 3–5 weeks. |
| Risk | Medium to high: new crypto protocol, key in server RAM, scope creep from "one job" to "always". |

### (c) Server-held keys, explicit opt-in per Project

The Project key is also wrapped for a server KMS key, so the server can decrypt
whenever it needs to.

| | |
|---|---|
| Speed | Best, with no expiry: background agents, schedules and overnight work all possible. |
| Security (i) stored-data breach | Opted-in Projects are exposed if the KMS or its credentials are compromised along with the data. |
| Security (ii) live server attacker | Full access to opted-in Projects. |
| Privacy promise | Those Projects become "server-encrypted", like most coding tools. They need a clear label, and must never be the default. |
| Effort | Medium: about 2 weeks. |
| Risk | High product and brand risk. Users mix up modes, and "temporary" opt-ins spread. |

### (d) Other options

- **d1. Connected machine as the main coding mode.** This already exists. The
  repo stays on the user's machine, commands run there sandboxed (bubblewrap or
  Seatbelt), and the server stores nothing, much like Claude Code.
  - Today it has the same loop overhead (1.4 s per op measured).
  - With (a) applied, it reaches about 0.3–0.6 s per op.
  - It works overnight if the machine is on.
  - Effort: low (loop fixes plus onboarding).
- **d2. Attested enclave executor.** The client releases the Project key only to an
  attested confidential VM or enclave (for example AMD SEV-SNP or AWS Nitro) that
  runs the file executor next to the agent.
  - Speed and availability are like (b), and the operator cannot read memory if
    attestation holds.
  - Effort: very high. It also brings infrastructure lock-in and a trusted
    computing base to review.
  - E2B commands still need plaintext outside the enclave.
  - A long-term option, not for launch.
- **d3. Smaller encryption scope.** Encrypt file content but not names or
  metadata, so listing and search by name run on the server. This saves only a
  part of one round trip and leaks repo structure. Not recommended.

### Comparison

| Option | Non-model overhead per op | Works with all devices closed | Stored-data breach | Live server breach | Promise change | Effort |
|---|---|---|---|---|---|---|
| Today | ~4.5 s (+1–1.5 s mobile) | no | safe | sees what the AI touches | — | — |
| **(a) optimised** | **~0.5–1 s** | no | safe | same as today | none | medium |
| (b) per-job key | ~0.1 s | yes, for the job's lifetime | safe | whole Project during the job | yes, consent | high |
| (c) server keys, opt-in | ~0.1 s | yes | exposed for opted-in Projects | whole Project | yes, consent | medium |
| d1 connected machine + (a) | ~0.3–0.6 s | if the machine is on | nothing stored | same as today | none | low |
| d2 enclave | ~0.1 s | yes | safe | safe if attestation holds | small | very high |

## 6. Recommendation and what it means for launch

1. **Keep client-side encryption as the default. Do not adopt (c).**
2. **Before production launch of agentic coding, fix in this order:**
   1. the 20-result loss (Task 88fc5dfb). Without it, any task over about 20
      operations spirals;
   2. inline wait instead of a task restart per file op;
   3. the turn cache and memory-only file cache with prefetch in the Rust
      executor, which also fixes the 100-file search cap and the N² snapshot;
   4. batching read-only ops, a diff edit tool and prompt caching;
   5. the wait email (Task 2d967ff7) and the failed-answer timeout (Task 763dc27d).

   After these, the remaining encryption cost is about 0.3–0.5 s per file op on
   a good connection. That is the honest price of the privacy promise, and it is
   small next to an 8 s model step.
3. **Present the connected machine as the recommended mode for real repos.**
   It has no size caps, runs commands locally and stores nothing on the server.
4. **Overnight or "close the laptop" jobs: decide on (b).** If launch needs them,
   design (b) as an explicit opt-in per job after (a). Otherwise launch with the
   honest limit: hosted Projects need an open device, and connected machines
   need the machine on.
5. **Speed target:** measure "within a few percent of Claude Code" on non-model
   overhead with the same model, using a budget of ≤ 0.3 s per tool call (Claude
   Code: 0.01–0.25 s). Total time also depends on model choice and prompt size,
   which this review does not cover.

## Appendix: method, limits, reproduction

- **Dev logs:** OpenObserve through `backend/scripts/debug.py logs --o2`.
  Timeline per chat with `harness/chat_timeline.py <out> <chat-id>`.
- **Hosted and connected runs:** `harness/run_openmates.py` and
  `harness/run_remote.py` (throwaway accounts through `scripts/dev_test_account.py`,
  isolated CLI state, deleted afterwards). Claude Code baseline:
  `harness/run_claude_code.py`.
- **Which client ran:** the installed `openmates` on the dev host is the npm CLI
  (Node launcher). The native Rust CLI, now the default, was not installed there
  and was not benchmarked.
- **Not covered:**
  - the web Worker and native CLI executors were not benchmarked separately.
    They use the same protocol and per-op call pattern as the npm executor, and
    the dev-log numbers include web traffic;
  - the installed npm CLI 0.30.0 cannot execute `snapshot` jobs, so hosted test
    runs from the CLI depend on it (see the loop result);
  - real network latency was modelled, not measured;
  - same-model totals were not run, because project rules fix the dev model.
- **Synthetic data only.** No production data was read.
