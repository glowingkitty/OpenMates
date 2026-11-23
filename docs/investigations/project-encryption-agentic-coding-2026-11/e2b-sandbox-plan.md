# Cloud Project agent jobs in an E2B sandbox: plan for approval

Plan for Marco, 21 Nov 2026 (evening), following his direction after the
[follow-up report](follow-up-target-architecture.md). Research and planning
only, no product code changed. Code was read at dev `fa3134998b`. New
measurements were taken on dev on 21 Nov with synthetic data
([`data/e2b-measure-2026-11-21.json`](data/e2b-measure-2026-11-21.json),
script [`harness/e2b_measure.py`](harness/e2b_measure.py)). E2B facts come
from E2B's own pages, linked where used. Estimates are marked as such.

## Summary

- **Your design solves speed and scale.** The agent works on a normal file
  tree inside the sandbox:
  - a file operation costs milliseconds instead of 1–4 s;
  - tests and builds run where the files are;
  - nothing limits the Project size except the sandbox disk (20 GiB on E2B
    Pro).

  Measured today: a sandbox starts in **0.6–0.7 s**, and it writes 18,000
  files in **0.85 s**.
- **Expected speed, same Gemini model** (estimates from the measured split):

  | Task | Today | With the sandbox |
  |---|---|---|
  | Small fix | 64 s | about 25–30 s |
  | Multi-file feature | 828 s | about 80 s |
  | Test-and-fix loop | did not finish | about 60 s |

  On the same model, the gap to Claude Code shrinks to about 2 s of job start
  plus about 0.15 s per model step.
- **Large repos.** The whole OpenMates repo (18,532 files, 425 MB, 162 MB
  packed) would get into a fresh sandbox in about **15–20 s** from our
  current storage in Germany, or about **5 s** with the encrypted pack stored
  near E2B. A follow-up message in the
  same chat takes 0 s. Today such a repo cannot be loaded at all.
- **Encryption at rest stays as strong as today, with one exception.**
  Everything stored is still ciphertext: the database, object storage and
  backups. The one change is to the key rule: the Project key leaves the
  user's devices for the first time. It goes sealed to one sandbox for one
  job, our server only relays a sealed blob, and the key is never stored. The
  Specification rule `projects.keys.client-wrapped` ("no surface exposes raw
  Project keys") has to change for that. Your direction is that change.
- **Honest limits:**
  - while a job runs, E2B (a US company) holds the plaintext Project and its
    key; the sandbox I measured ran in **Oregon, USA**;
  - code from the Project's own dependencies runs in the same sandbox;
  - our server still sees whatever the model reads, as today;
  - an operator who controls our servers could change the sandbox code. This
    is no worse than today's web app, which our server also delivers.
- **Devices closed:** once the key is in the sandbox, the job keeps running
  with every device closed, until it idles out or hits the time limit. This
  replaces most of the open per-job key question. What remains is how long
  that limit may be: I propose **4 h**, opt-in up to 24 h.
- **Lifetime:**
  - deleted **15 minutes** after the last activity;
  - **4 hours** at most;
  - never paused, because a paused E2B sandbox keeps its memory and files on
    E2B's disk with no expiry.
- **Cost:**
  - about **$0.05–0.11** of E2B time for a typical job (2 vCPU / 4 GiB or
    4 vCPU / 8 GiB, including the 15 idle minutes);
  - about **$0.40** for a 1-hour job;
  - at most **$1.32** for a 4-hour job;
  - plus the E2B Pro plan ($150 a month), and more concurrency once more than
    100 sandboxes run at once.
- **What happens to today's design:**
  - the client executor loop and the one-task-per-job rebuild are no longer
    needed for agent jobs;
  - still needed: history caching, the cache dump fix (e7ec7a72), and
    job-based rather than per-IP rate limits;
  - the same agent program serves connected machines.
- **Effort:** about 12–15 weeks in total. The first fast version (sandbox,
  key handover, agent loop, write-back) takes about 8 weeks.

**Decisions for you (each with my recommendation):**

1. **Key rule:** approve handing the raw Project key, sealed, to one sandbox
   per job. *Recommendation: yes*, with the safeguards in section 3.
2. **Location:** accept that Projects are processed in E2B's US region, or
   first ask E2B for an EU region. *Recommendation:* ask E2B now; launch in
   the US with that said plainly in the consent if no EU option exists.
3. **Time limit with every device closed:** *Recommendation: 4 h default*,
   opt-in up to 24 h per job.
4. **Users who decline E2B:** keep today's slow device path for them, or
   offer only a connected machine. *Recommendation:* keep it frozen as a
   fallback for small chat edits, with no further investment.

## 1. The flow, step by step

### 1.1 Job start

1. The user sends a message in a chat on a hosted Project. Every message in a
   Project chat counts as a job, so short questions are covered too.
2. **Consent.** If the account has no current E2B consent, the existing
   in-chat consent card asks first (`code-run.e2b.upload-consent`,
   `backend/core/api/app/services/e2b_upload_consent.py`).
   - The wording changes: "this Project is opened inside an E2B sandbox
     during the job, including the key that unlocks it; files are processed
     in [region]".
   - The service versions its wording (`E2B_UPLOAD_CONSENT_VERSION = 1`).
     Any meaningful change becomes v2, which asks every user again, as the
     module requires.
3. **Sandbox.** The server finds the chat's live sandbox, or creates one:
   - template with the agent program;
   - 4 vCPU / 8 GiB;
   - `secure=True`, public traffic off, as the code-run sandboxes already do
     (`backend/shared/providers/e2b_code_runner.py:568-574`);
   - outbound network limited to our API, the object store and package
     registries (E2B `allowOut`/`denyOut`,
     [internet access](https://docs.e2b.dev/sandbox/internet-access)).

   The server gives the sandbox a **job token**:
   - scoped to this user, Project and chat;
   - allowed to read ciphertext heads, commit revisions, and call the model
     step and progress endpoints;
   - with no access to history, other Projects or account data;
   - expiring with the sandbox.

   Measured start: 0.57 s with E2B's default template, 0.72 s with our
   code-run template.
4. The sandbox's agent generates a fresh **X25519 key pair in memory** and
   reports the public key to the server. The private key never leaves the
   agent process.

### 1.2 Key handover, without the server seeing the key

1. The server forwards a request to the user's open devices: "sandbox
   *S* for job *J* needs the key of Project *P*", with the sandbox public key.
   This uses the same WebSocket that file jobs use today.
2. Any one device that holds the Project key does the following:
   1. It checks the request against what the user just did: the same Project
      and chat, a job it started in the last few minutes.
   2. It **seals** the Project key to the sandbox public key. The sealing
      binds `sandbox_id`, `job_id`, `project_id` and an expiry as
      authenticated data.
   3. It sends the sealed blob back.

   This is the same sealed X25519 envelope pattern the remote-machine relay
   already uses (`packages/openmates-rust/src/work/projects/remote_files.rs:281`),
   in the shared Rust core, so web, CLI and Apple get it at once.
3. The server passes the blob on to the sandbox. It only ever sees ciphertext
   it cannot open. The blob is not stored. It is not logged, beyond its size
   and a success flag.
4. The agent opens it, keeps the key in process memory only, and wipes the
   private key.

**Why not connect the device straight to the sandbox?**
- E2B ends TLS at its own proxy and re-encrypts to the sandbox
  ([public URL](https://docs.e2b.dev/network/public-url)), so a direct
  connection still needs the sealed layer.
- A direct connection would also need a traffic token per sandbox
  ([restrict public access](https://docs.e2b.dev/network/restrict-public-access)).
- So relaying the sealed blob through our server gives the same protection
  with fewer moving parts.

What neither path can prove is *which code* runs in the sandbox (section 3).

**The device must be online once, at job start.** That holds for every job a
user starts by typing. Jobs that start with no device online, such as
scheduled Tasks or workflows, cannot get a key under this design.

### 1.3 Sync in: getting a big Project in fast

Today each file is its own encrypted record, fetched one by one. For a
sandbox that would mean 18,500 requests for the OpenMates repo. The plan
instead:

1. **Encrypted pack.** A Project keeps one packed copy of all current files:
   tar + zstd, then AES-GCM with a pack key wrapped by the Project key. It
   lives in object storage as ciphertext only, and records the revision it
   reflects.
   - The sandbox writes a new pack at the end of a job that changed many
     files. It holds the plaintext and the key then anyway.
   - Small jobs append a small delta pack instead.
2. **Delta since the pack.** One batch request returns the ciphertext of every
   file revised after the pack's revision. A device may have edited files
   since. This needs a new batch read endpoint, first-party only and job-token
   scoped, as the backend rules require for encrypted routes.
3. **Unpack.** Decrypt, decompress and write the tree, then `git init` a local
   baseline. The agent can then use `git diff` and `git status`, and
   write-back knows exactly what changed.
4. **Dependencies.**
   - A cold `npm`/`pip` install of a large repo takes minutes (*not measured
     here*).
   - Cache the installed dependencies per lockfile hash as another encrypted
     pack. Lockfiles and private package names are not public, so the cache
     stays encrypted.
   - Restore it in seconds, and install only when the lockfile changed.

**Measured building blocks** (21 Nov, sandbox in Oregon):

| Step | OpenMates repo (18,532 files, 425 MB) | Source |
|---|---|---|
| Pack size (zstd -3) | 162 MB, packed in 2.6 s | `git archive HEAD \| zstd -3` on the dev host |
| Download from our storage region (Hetzner Nuremberg), one connection | 10.6 MB/s → about 15 s | sandbox `curl` of a public 100 MB test file |
| Same, 6–8 parallel ranges | about 4–6 s (*estimate*) | — |
| Same, ciphertext pack stored next to E2B (US) | about 2–3 s (*estimate*) | — |
| Decrypt (AES-256-GCM) | under 0.1 s at 4.4 GB/s | `openssl speed` in the sandbox |
| Write 18,000 files | 0.85 s | measured in the sandbox |

The pack holds only ciphertext, so placing it next to E2B weakens nothing at
rest. It is simply a second storage location, and it should be an EU or US
bucket that we control.

### 1.4 The agent loop inside the sandbox

1. **One agent program for both modes.** The connected-machine agent from the
   last plan, in the Rust core, runs here as a Linux binary in the template.
   It has the normal coding tools:
   - read, search (ripgrep), edit (exact replace), write;
   - run commands;
   - several tool calls per model step, run in parallel.
2. **Model steps go to OpenMates.** Each step is one request to a model-step
   endpoint with the job token. That endpoint adds:
   - the OpenMates system prompt;
   - model choice and failover;
   - billing;
   - PII handling;
   - streaming to the user's devices.

   It starts from the existing OpenAI-compatible route
   (`backend/core/api/app/routes/openai_compat.py:1-7`), extended with job
   tokens and streaming. The history lives in the agent's memory and stays
   byte-identical between steps, so provider prompt caching works as it does
   for Claude Code (section 4).
3. **Round trip per step:** about 0.15 s of network from Oregon to our API in
   Germany, plus model time. Measured: time to first byte was 0.51 s on a
   *new* TLS connection (3 round trips). A kept-alive connection pays one.
4. **Commands run in the sandbox without approval by default.** It is a
   disposable machine with only this Project. These still ask the user:
   - network access beyond the allow-list;
   - deleting more than a set number of tracked files;
   - anything that writes outside the Project.
5. **The user sees progress and edits live**, through the same streaming path
   as today's assistant replies. They can stop the job at any time.

### 1.5 Sync back: encrypted write-back and conflicts

1. **When:**
   - after every agent step that changed files (debounced to a few seconds);
   - before the sandbox is deleted.

   If a sandbox dies, at most the last few seconds are lost, and devices see
   edits as they happen.
2. **What:** files that differ from the baseline and are not ignored by the
   Project policy (`.gitignore`, `permissions.yml`). Build output and
   `node_modules` never go back.
   - Each changed file becomes one encrypted revision with its expected base
     revision, exactly as today (`projects.files.hosted-ciphertext-commit`,
     `.expected-base`).
   - New files get a fresh file key wrapped by the Project key.
   - A new batch commit endpoint sends many files in one request.
3. **Conflicts.** If another device changed a file since the sandbox read it,
   the commit is refused as stale, as today. Then:
   1. The sandbox fetches the new head and tries a three-way merge
      (`git merge-file`: base = what the sandbox read, ours = agent, theirs =
      other device).
   2. A clean merge is committed.
   3. A real conflict is handed to the agent as a tool result ("this file was
      changed on another device; merge"), while the job runs.
   4. If the job has already ended, the other device's version stays. The
      agent's version is offered in the chat as a proposed change, using the
      existing proposal path. Nothing is overwritten silently, as the
      exact-patch rule requires.
4. **Live remote edits.** While the job runs, the sandbox listens for
   revision events on the Project:
   - files the agent has not touched are updated in place;
   - files it has touched go through the conflict path.

### 1.6 Deletion

| Rule | Value | Why |
|---|---|---|
| Idle timeout | **15 min** after the last agent step or user message | People usually reply within minutes. Installed dependencies and running dev servers stay warm for the follow-up. 15 idle minutes cost $0.04–0.08. It matches today's workspace rule (`WORKSPACE_IDLE_TIMEOUT_SECONDS`, `e2b_project_workspace.py`) and the Gemini cache TTL (900 s). |
| Hard maximum | **4 h** per sandbox | Long agent jobs fit: 1–2 h is long for Claude Code-style work. It caps how long plaintext and the key live outside the user's devices, and stays well under E2B Pro's 24 h cap ([sandbox lifetime](https://docs.e2b.dev/sandbox)). At 4 h, if a device is online, it hands the key to a fresh sandbox and the job goes on seamlessly. If not, the job writes back, pauses and tells the user. |
| Opt-in long run | up to 24 h for one job | For "run this while I sleep". The user chooses it per job and sees the expiry. |
| Pause | **never** | A paused E2B sandbox stores memory and files on E2B with no expiry ([persistence](https://docs.e2b.dev/sandbox/persistence)). The key and plaintext would then rest at E2B. Timeouts are set to kill (`onTimeout: kill`). |

**Deletion order:**
1. final write-back;
2. new pack (if needed);
3. revoke the job token;
4. kill the sandbox.

Per E2B, a killed sandbox "is permanently deleted"
([persistence](https://docs.e2b.dev/sandbox/persistence)). The server also
kills sandboxes whose job record is gone, so a crash never leaves one running
past its hard maximum.

## 2. Speed and scale

The estimates use the same Gemini model as the benchmarks and the
per-step model time measured in the first report. Claude Code ran Claude
Sonnet, so the fair comparison is the overhead, not the total.

| Task | Claude Code (measured) | Today hosted (measured) | Previous plan (estimate) | Sandbox (estimate) | How it adds up |
|---|---|---|---|---|---|
| Small fix | 13–14 s | 64 s | ~35 s | **25–30 s** | start + key + sync about 2 s; 4–5 model steps of ~5 s; tool calls ~0.1 s each |
| Multi-file feature | 27–35 s | 828 s | 90–100 s | **~80 s** | about 15 steps, with parallel tool calls and no lost results |
| Test-and-fix loop | 53–64 s | did not finish | 60–80 s | **~60 s** | tests run in the sandbox in about 0.3–1 s each, as locally |
| Overhead per tool call | ~0.01–0.25 s | ~3.6 s | ~0.5 s | **~0.01–0.3 s** | local disk and processes |
| Overhead per model step | — | queue + task restart | ~0.3 s | **~0.15 s** | one round trip Oregon ↔ Germany on a kept-alive connection |

**Large repo (OpenMates itself):**

| Step | Today hosted | Sandbox, first job | Sandbox, follow-up in the same chat |
|---|---|---|---|
| Get the Project ready | impossible: 200-file / 400 KB cap; a full read would need ~37,000 calls to a route limited to 60 a minute (about 10 h) | about 15–20 s (pack from Nuremberg) or about 5 s (pack next to E2B) | 0 s |
| Dependencies | — | seconds from the encrypted cache; minutes on a cold install (*not measured*) | 0 s |
| Search the whole repo | about 20 s per 100 candidate files | under 1 s (ripgrep on local disk, *estimate*) | same |
| Write back 20 changed files | about 9 calls each | one batch call, about 1 s | same |

**About 1 million changed lines a week.** The OpenMates repo itself had 2,481
distinct files changed in 7 days (358 commits). Two things scale with that:
- Sync-in reads only the delta since the last pack.
- Write-back sends only what the agent changed. Re-packing after big jobs keeps
  the delta small.

Neither depends on the total repo size, so churn at this level is fine.

**Remaining limits:**
- **The model.** On the same model the gap to Claude Code is about 2 s at job
  start plus about 0.15 s per step, roughly 5–10 % on these tasks.
  Matching Claude Code overall depends on model speed and step count, as the
  first report showed.
- **Sandbox capacity.** E2B Pro allows 100 concurrent sandboxes (600 or 1,100
  with add-ons, [pricing](https://e2b.dev/pricing)). Our own cap is
  `CODE_RUN_MAX_ACTIVE_E2B_RUNS` = 100 (`backend/core/api/app/routes/code_execution.py:56`).
  With 15 idle minutes, every recently active Project chat holds a slot.
  Capacity has to grow with usage.
- **Region.** Each model step crosses the Atlantic once, a small cost. Data
  location is the bigger issue (section 3).

## 3. Security, honestly

### 3.1 Who can see what

| Party | Today (hosted Projects) | With the sandbox |
|---|---|---|
| Stolen database or backup | ciphertext only | ciphertext only (unchanged) |
| Stolen object storage (packs) | — | ciphertext only |
| Our logs | no file content | no file content; key handover logged as size and status only |
| Our server, running honestly | plaintext of files the model reads, in memory and briefly in the cache (pending writes, test snapshots) | plaintext of what the model reads, in memory only. The loop's history lives in the sandbox, so no plaintext handoff or snapshot in our cache. Never the key. |
| Our server, actively malicious (attacker with control of our deployment) | can ship web code that steals keys, as for any web app with client-side encryption | the same, plus it chooses the sandbox code, which could leak the key. The device cannot verify the sandbox code: E2B states no attestation. **No worse than today, and no better.** |
| E2B | plaintext of the files sent for a test run, while it runs | **the whole plaintext Project and its key**, while the job runs, in E2B's US region. E2B keeps sandbox logs 7 days ([internet access](https://docs.e2b.dev/sandbox/internet-access)); what they contain must be kept free of file content and checked with E2B. |
| Compromised sandbox (malicious dependency, prompt injection) | sees the snapshot files | sees the plaintext Project and can read the key from agent memory. Egress allow-listing limits where it can send them. |
| Model provider | what the model reads | what the model reads (unchanged) |

### 3.2 What a stolen key means

The Project key unlocks every file key in that Project
(`packages/openmates-rust/src/work/projects/hosted/io.rs:126-160`, file keys
wrapped with `key_type: "project"`). It also never changes today. So a key
taken from a sandbox opens:
- all current files;
- all past versions;
- all future versions;

but **only together with the ciphertext**, which an attacker would also have
to take from our database or storage. Each half alone is useless. That is the
point of keeping ciphertext at rest even while sandboxes hold keys.

Safeguards:

1. **The job token is limited.** It reads heads only, not history, and dies
   with the sandbox. A stolen key cannot fetch more ciphertext through it once
   the job ends.
2. **The key exists only in the agent process.** It is not in environment
   variables or files. User commands run as a separate Linux user, and
   `ptrace` between processes is blocked. This *reduces*, not removes, the
   chance that a malicious dependency reads it from the same VM.
3. **Outbound network is allow-listed:** our API, the pack storage and
   package registries. Anything else asks the user (section 1.4).
4. **Key rotation**, later and optional: re-wrap file keys under a new
   Project key after a job, or on request. This is cheap because only the
   small wrappers change. To fully protect future versions, files that the
   job touched would also need new file keys.

### 3.3 Compared with today and with other platforms

| | Code at rest | Code during a job | Environment kept after the job |
|---|---|---|---|
| OpenMates today (hosted) | ciphertext | plaintext on our server and E2B, for files touched | test snapshot in our cache up to 15 min |
| **OpenMates sandbox plan** | **ciphertext** | **plaintext in a sandbox at E2B, whole Project, with key** | **nothing: killed, never paused** |
| Claude Code on the web | the GitHub repo (plaintext at GitHub) | VM on Anthropic infrastructure; repo cloned in ([docs](https://code.claude.com/docs/en/claude-code-on-the-web)) | VM reclaimed after inactivity |
| OpenAI Codex cloud | the GitHub repo | VM per task ([docs](https://learn.chatgpt.com/codex/environments/cloud-environments)) | saved VM state recoverable up to 7 days |
| GitHub Copilot coding agent | the GitHub repo | GitHub-hosted sandbox or Actions runner ([docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent)) | stopped sessions keep a snapshot |
| Connected machine (planned) | the user's disk | the user's machine | the user's choice |

All the large platforms run jobs on plaintext in a vendor VM, and none keeps
the repository encrypted at rest. With this plan OpenMates matches them
during a job and stays stronger at rest. The difference: it uses a separate
vendor (E2B) instead of its own infrastructure.

### 3.4 The open per-job key decision

- The earlier option (b) was a key the *server* could use while all devices
  are closed. It is no longer needed. The sandbox already holds the key for
  its lifetime, so **jobs keep running with every device closed**, up to the
  hard maximum.
- What is left to decide is that maximum (decision 3): 4 h by default, opt-in
  up to 24 h.
- Two cases still need a device online once:
  - starting a job;
  - rolling over to a new sandbox after the maximum.

### 3.5 Rules to change

| Rule | Change |
|---|---|
| `projects.keys.client-wrapped` | Allow one sealed handover per job to a sandbox key, bound to sandbox, job, Project and expiry; never stored, never logged. |
| `code-run.cloud.workspace` | Sandbox per Project chat, with the new lifetime rules and no pause. Replaces "the sandbox receives file contents only, never keys" (`e2b_project_workspace.py` header). |
| `code-run.e2b.upload-consent` | Wording v2: whole Project, key, region. Asks everyone again. |
| New | Write-back and conflict rules; job token scope; pack format. |

## 4. What happens to today's design and the planned steps

| Item | Status with the sandbox | Why |
|---|---|---|
| Client executor loop (device reads and writes files per operation) | **Not used for agent jobs.** Kept frozen as the fallback for users who decline E2B and for small chat edits (decision 4). | The sandbox does all file work locally. |
| Test snapshot (plaintext in our cache, 200-file cap) | **Removed.** | Tests run in the sandbox on the full tree. |
| One AI task per job (main processor inline wait) | **Replaced.** | The loop runs in the sandbox, so the server only answers model steps. No more task restart or result handoff per operation. |
| Bug: tool results lost after 20 operations (88fc5dfb) | Needed only for the fallback path: fix cheaply or leave. | The sandbox loop keeps its own history. |
| Wait email (2d967ff7), CLI not returning (763dc27d) | Fallback path only, low priority. | — |
| Rate limit vs agent load | **Still needed, in a new form.** Every sandbox calls us from shared Google Cloud addresses, so per-IP limits would throttle all users together. Limit by job token and user instead. | Measured exit address: Google LLC, Oregon. |
| History caching | **Still needed.** Model steps are now most of the time. The stable in-memory history makes it straightforward: cache markers on tools and history, Gemini cache including history. | Section 2 of the follow-up report. |
| Exact-replace edit tool | Built into the agent as a local tool. The exact-patch rule now applies at write-back. | — |
| Batched reads | Become the delta read and the pack (section 1.3). | — |
| Cache dump files with plaintext (Task e7ec7a72) | **Still needed now.** The dumps are on disk today. The sandbox plan removes most plaintext from our cache, but not dumps that already exist. | — |
| Connected-machine local agent | **Same agent program.** Building it once serves both modes. | — |
| Opt-in per-job key (option b) | Replaced by the sandbox lifetime decision. | Section 3.4. |

## 5. Cost, effort, risks and order

### 5.1 E2B cost per job

E2B charges $0.000014 per vCPU-second and $0.0000045 per GiB-second; disk is
free ([pricing](https://e2b.dev/pricing)). That makes 4 vCPU / 8 GiB
**$0.33 an hour**, and 2 vCPU / 4 GiB **$0.17 an hour**. The 2 vCPU / 4 GiB
default on the pricing page differs from the 473 MB sandbox measured, so the
template must set the size explicitly.

| Job | Active | + idle | 4 vCPU / 8 GiB | 2 vCPU / 4 GiB |
|---|---|---|---|---|
| Quick question or small fix | 2 min | 15 min | $0.09 | $0.05 |
| Multi-file feature | 5 min | 15 min | $0.11 | $0.06 |
| Long job | 60 min | 15 min | $0.41 | $0.21 |
| Hard maximum | 4 h | — | $1.32 | $0.66 |

Fixed costs:
- E2B Pro is $150 a month;
- more concurrency costs $650 a month (600 sandboxes) or $1,150 a month
  (1,100 sandboxes).

For comparison, the model cost of the benchmark multi-file job:
- today: 48 steps × about 34K input tokens plus about 1.25K output and
  thinking tokens each ≈ $2.20 at Gemini 3.8 Flash prices ($1.50 per million
  input tokens, $0.15 cached, $7.50 output;
  `backend/providers/google.yml:445-452`);
- with 15 steps and history caching: about $0.30.

The sandbox costs about as much as the model on such a job, and less on long
ones. A shorter idle timeout (for example 5 minutes) would cut the idle share,
but follow-ups would then often start cold.

Two settings follow from this. The template sets 4 vCPU / 8 GiB for Project
jobs, and builds may need more on large repos (Pro allows custom sizes). We
bill users per minute, as code runs already are (`backend/apps/code/app.yml`:
3 credits per minute today).

### 5.2 Steps

| # | Step | Effort | Risk | What it unlocks |
|---|---|---|---|---|
| 0 | Now, independent: cache dump fix (e7ec7a72); ask E2B about an EU region and the content of their logs; Specification drafts for the rule changes | 1 week | low | Removes the existing at-rest leak; settles decisions 1–2 |
| 1 | Sandbox job service: per Project chat, job token, egress allow-list, idle 15 min / hard max 4 h / never pause, capacity limits by job and user | 1–2 weeks | medium | Builds on `e2b_project_workspace.py` |
| 2 | Key handover in the Rust core (web, CLI, Apple) with the sealed envelope; consent v2 | 1–2 weeks | **high**: key handling; needs careful review and tests that the server never sees the key | Encrypted Projects can open in a sandbox |
| 3 | Sync in: batch delta read endpoint, then the encrypted pack and dependency cache | 2 weeks | medium: new encrypted routes and pack format | Large Projects in seconds |
| 4 | Agent program (shared with connected machines) and the model-step endpoint with streaming, billing and job tokens | 3–4 weeks | medium–high: new client surface, streaming and stop semantics | The fast loop; connected machines get it too |
| 5 | Write-back: batch commit, debounced checkpoints, three-way merge, live remote edits, proposals for unresolved conflicts | 2 weeks | **high**: risk of losing user edits; needs strong tests | Safe edits from many devices |
| 6 | History caching on the model-step endpoint; per-step cache logging | 1 week | low–medium | Most of the remaining model time |
| 7 | Freeze the client executor as a fallback; remove the test snapshot and the one-operation-per-step pipeline for agent jobs; rate limits by job | 1 week | low | Less code, fewer slow paths |

**Order:**
1. Step 0.
2. Steps 1–2 together.
3. Steps 3 and 4 in parallel.
4. Step 5.
5. Steps 6–7.

**Timeline:**
- about **8 weeks** to a first fast version (steps 0–2, the basic delta read
  from 3, 4 and 5);
- about **12–15 weeks** with the pack, dependency cache, caching and
  clean-up.

**Biggest risks and how to handle them:**

| Risk | Handling |
|---|---|
| Losing edits on write-back | Checkpoints after every step; never overwrite on conflict; end-to-end tests with two devices editing at once. |
| Key exposure inside the sandbox | Separate Linux user for commands; egress allow-list; key only in agent memory; optional rotation. |
| E2B outage or price change | The frozen device path still works for small edits, and connected machines don't depend on E2B. |
| Data location (US) | Decision 2; the consent says it plainly. |
| Capacity and cost growth | Per-user limits; shorter idle when capacity is tight; usage billing per minute. |

## Appendix

- **Measurements (21 Nov):** [`data/e2b-measure-2026-11-21.json`](data/e2b-measure-2026-11-21.json):
  - sandbox start 0.57 s (default) and 0.72 s (code-run template);
  - default size 2 vCPU / 473 MB RAM / 22 GB disk;
  - location Oregon, US (Google Cloud);
  - time to first byte to the dev API 0.51 s on a new connection;
  - download 10.6 MB/s from Hetzner Nuremberg and 1.9 MB/s from Falkenstein,
    one connection each;
  - 18,000 file writes in 0.85 s;
  - AES-256-GCM at 4.4 GB/s.
- **Repo size:** measured on the dev checkout at `09cb86031a`. Weekly churn
  from `git log --since="7 days ago"`.
- **E2B pages read:** [pricing](https://e2b.dev/pricing), [sandbox](https://docs.e2b.dev/sandbox),
  [persistence](https://docs.e2b.dev/sandbox/persistence), [internet access](https://docs.e2b.dev/sandbox/internet-access),
  [public URL](https://docs.e2b.dev/network/public-url),
  [restrict public access](https://docs.e2b.dev/network/restrict-public-access),
  [sandbox lifetime FAQ](https://docs.e2b.dev/faq/sandbox-lifetime).
  They don't state:
  - start time;
  - an EU region;
  - SOC 2;
  - attestation.
- **Not measured:**
  - cold dependency installs for a large repo;
  - parallel-range download speed;
  - downloads from a bucket in E2B's region;
  - end-to-end job times. Every speed figure in section 2 is an estimate
    from measured parts.
- **Tasks:** e7ec7a72 (cache dumps), 88fc5dfb, 2d967ff7, 763dc27d.
