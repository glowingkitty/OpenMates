# Speed and token waste in dev Claude chats (TASK-3619)

Research only, no code changes. Requested by Marco, Sun 22 Nov 2026.
Data: every Claude Code transcript on the dev server touched in the last 14 days
(258 main chats, 1,801 sub-agents, 133,555 model calls, activity 3–22 Nov), the
CI coordinator queue (10,810 jobs), GitHub step timings of sampled proof runs,
the chat lifecycle event log and the deploy/hook outputs inside the transcripts.
Transcripts and logs stayed on the server; this report has only counts, timings
and short chat ids.

## Summary in plain words

- **Time goes into the CI proof loop.** A single E2E spec takes a median of
  **17.5 minutes** from submit to result, even when CI is idle. The test itself runs
  for 2–3 minutes. The rest is preparation (median 6.3 min) and per-job setup
  inside the run (≈3 min rebuilding the Rust web core and the web app, ≈1 min
  installing the browser, ≈1.5 min images and backend). This explains the
  12–15 minute proof runs in chat e79c5d1b.
- **Chats use E2E as their debugger.** 51% of chat-submitted E2E jobs fail. In
  944 cases a chat reran the same spec right after a failure and it failed
  again. Real flakiness is rare (39 fail→pass reruns on identical source). The
  top loops: one slides spec ran 24 times (19 failed), voice-call 21 times (18 failed).
- **40% of deploy attempts are refused** (652 of 1,615): files not tracked,
  missing Specification trailers, the Specification gate, lint. Each costs
  ≈2.5 minutes plus several turns to fix and retry.
- **Waiting for Marco is the largest single wait for a person.** Chats sent 182 questions.
  Where Marco answered in the same chat, the median wait was **5.6 hours**. Some
  questions were already decided ("may I restart the dev API", sent 3× in one
  minute after the 21 Nov rule). Three blocking `AskUserQuestion` dialogs, which
  nobody sees in connector chats, held chats for 52 hours in total.
- **Tokens go into big contexts that get woken up often.** The average main-chat
  call carries **170k tokens of context**. 41% of main-chat token cost is spent in
  calls above 200k. 46% of main-chat cost is spent in turns started by
  background notifications (CI waits, finished sub-agents), and another 5% by
  messages from peer chats.
- **Sub-agents are about half of all tokens** (48%). Since 13 Nov they run on
  Sonnet/Haiku as intended, except the built-in `Explore` agent, which still
  runs on Opus. One Fable orchestrator chat on 8–9 Nov used **27% of all 14-day
  tokens** by itself (326 general-purpose sub-agents, 148 of them on Opus). The
  newer budget and model guards prevent this now.
- **Some suspected causes turned out small**: re-reading the same file, exact duplicate
  tool calls, huge single outputs and the dev test lock each cost little (see
  the "not worth it" table).
- **Waiters that never fire exist.** The lifecycle has tried to wake 5 chats
  11,354 times since 20 Nov ("no transcript on this host"), and every attempt
  failed. Only 38 waiter wakes succeeded in the whole period.

### Top 10 changes (detail in section 5)

| # | Change | Time saved / 14 days | Tokens saved | Effort | Risk |
|---|---|---|---|---|---|
| 1 | Faster proof pipeline: prepared build includes the web Rust core and web app, browsers pre-installed, warm preparation per source, reserved slots for chat jobs | 150–250 chat-hours; one E2E 17.5 → ≈9 min | indirect (fewer idle wakes) | M | low–med |
| 2 | Stop the E2E fix loop: after 2 failures of the same spec, require triage before another submit; one-spec warm inner loop | ≈135 CI hours | 150–250M (5–8%) | S–M | low |
| 3 | Keep contexts small: handoff to a fresh chat after a few compactions; auto-compact window 300k → 200k; orchestrators stay small | – | 200–350M (6–11%) | S | low–med |
| 4 | Fewer wake-ups: one notification per job set, peer messages to a mailbox unless urgent | small | 250–350M (8–11%) | M | low |
| 5 | Deploy first-time-right: one preflight listing every gate problem at once, auto trailers and auto tracking | ≈20 h | 40–60M | S–M | low |
| 6 | Questions to Marco: block `AskUserQuestion` in connector chats, dedupe asks, check standing decisions first, put decisions in briefs | 50+ h plus avoided 5.6 h waits | small | S | low |
| 7 | Lifecycle: expire waiters of chats without a transcript, report failed wakes | waits that never fired (5 chats) | – | S | low |
| 8 | Trim the fixed base context (≈50k tokens per call): unused generic skills, agent list, peer list once | – | 110–130M (≈4%) | S | low |
| 9 | Friendlier Bash guard: allow `cd` into the own scratchpad, block sleep polling with a pointer, fix the `submit` JSON crash | ≈7 h sleep polling | 20–40M (≈1%) | S | low |
| 10 | Route by task type: Sonnet for checks, release prep, CI babysitting, docs; Opus for encryption/sync/AI pipeline; Explore → Sonnet | – | same tokens, lower price | S | med |

Token numbers are input-equivalent units (see Method). The whole 14 days cost
3.25 billion units, ≈232M per day.

## 1. Time: where chats lose it

| Rank | Cause | Measured (14 days) | Notes |
|---|---|---|---|
| 1 | CI proof loop | 501 chat-hours with at least one CI job of the chat in flight; chat E2E median 6.3 min preparation + 11.2 min run; 51% fail; 944 fail→fail reruns | Test step itself 2–3 min. Component specs: 6.2 min run, 35% fail. Apple UI: 34 min run, 71% fail |
| 2 | Waiting for Marco | 182 asks from 60 chats; 28 answered in-chat with median 5.6 h, p75 13.7 h (278 h total); 17 asks never answered in the same chat | Includes already-decided asks (examples below) |
| 3 | Deploys | 79 h inside `sessions.py deploy` / `wait-deploy` (1,615 attempts, avg 2.5 min); 652 refused | Refusals: untracked or `--only` mismatch (72), Specification gate (35), missing trailers (24+), lint (7), others |
| 4 | Stuck tool calls | 3 `AskUserQuestion` dialogs: 52.5 h; one `Monitor`: 39 h; one shell call: 29 h | Connector chats have no one at the dialog |
| 5 | `heavy_slot` runs | 22 h (1,041 runs, avg 76 s) | Mostly queueing for E2B/memory |
| 6 | Sleep polling | 7 h (381 polling calls, 547 `sleep` commands) | Against the CLAUDE.md rule |
| 7 | Compaction | 5.3 h (523 compactions, ≈37 s each) | Token cost is larger than the time cost (section 2) |
| 8 | Waiters that never fire | 5 chats retried 11,354 times (20–22 Nov), "no transcript on this host"; 25 "typing into its pane failed"; 20 held prompts lost | Only 38 successful waiter wakes overall |
| 9 | Dev test lock | 6 refusals "DEV TEST LOCK — deploy/restart waits"; lock has no holders now | Being removed (owner, 21 Nov); small in the data |
| 10 | Flaky tests | 39 fail→pass reruns on identical source | Flakiness is not the main loop; failing fixes are |

**The 12–15 minute proof run (chat e79c5d1b, session 13ec).** Its last six E2E
jobs: preparation 5.1–13.4 min, then 10.2–18.9 min on the runner. GitHub step
timings of two of them:

| Step | Run A | Run B |
|---|---|---|
| Download prepared build | – | 24 s |
| Reuse runtime images | 42 s | 42 s |
| Build opt-in web Rust core package | 117 s | 114 s |
| Build local web app | 78 s | 61 s |
| Start isolated backend | 43 s | 45 s |
| Install browser | 58 s | 53 s |
| **Run selected checks (the test)** | **114 s** | **177 s** |
| Cleanup | 21 s | 20 s |
| Job total | 9.8 min | 10.7 min |

So ≈4 of the ≈10 runner minutes are rebuilds and installs that repeat for every
spec of the same source, and preparation adds 5–13 minutes before the run
starts.

**Queue.** Chat jobs normally dispatch quickly (median 9 min including
preparation). The p90 is 117 min, with spikes when the daily batch holds the
slots (Berlin hours 01, 04, 06 and 15 have median waits of 53–76 min, and 11 and
16 Nov medians of 39 and 58 min). The daily batch (2,707 jobs) waits a median
7.6 h, which is fine for an overnight batch.

**Already-decided or avoidable asks (examples).**
- 4b5c74d7, 21 Nov 17:22: "may I restart the dev API …" sent three times in the
  same minute. CLAUDE.md says dev restarts need no approval (owner, 21 Nov).
- b08981c4, 76c8264a, 6e6c12de: "approve the spec so I can build?" before or
  during the work. The rule is: draft Specifications without approval rounds and
  ask once after deploy.
- b8f9456e, 18693e46 (16 Nov): "this is a Marketing Week, should I start …?".
  The mechanism was later removed because it made chats push back.
- Several asks were status reports ("DONE on prod …", "send_message is fixed …")
  sent as questions. That keeps a chat "blocked" when it is not.

## 2. Tokens: where they go

Totals (14 days): 18.2 billion cache-read tokens, 531M cache-write tokens,
74M output tokens. In input-equivalent units: **3.25 billion**, of which cache
reads are 56%, cache writes 33% and output 11%. Main chats are 52% and
sub-agents 48%.

| Rank | Cause | Cost (units) | Evidence |
|---|---|---|---|
| 1 | Big contexts on every call | 692M of main-chat 1,699M (41%) in calls above 200k context; average main call reads 170k | Auto-compact window is 300k on a 1M model; long-lived chats such as 4b5c74d7 (10 days, 77 compactions, 9,064 calls, 294M with sub-agents) and d2a774d9 (8 days, 40 compactions, 224M) |
| 2 | Wake-ups of big chats | 782M (46% of main) in turns started by task notifications (2,903 wakes, ≈11 calls each); 169M in 789 turns woken by peer-chat messages | Each wake re-reads the full context several times |
| 3 | Sub-agents | 1.55B (48% of all): general-purpose 975M (421 agents), lane-worker 423M (768), Explore 62M, ci-runner 41M (329, Haiku) | general-purpose costs ≈4× a lane-worker per agent |
| 4 | One orchestrator chat | 679b50bc (Fable, 8–9 Nov): 878M = 27% of all tokens, 326 sub-agents, 148 on Opus | Before the budget/model guards |
| 5 | Fixed base context | ≈50k tokens on every first call: skill list ≈7k tokens, agent list ≈3k, CLAUDE.md and rules ≈5k, peer list ≈1.3k, tools and system | ≈29% of all cache-read volume is this base |
| 6 | Compaction | 523 compactions over 138M tokens; 268M spent in turns right after a compaction (rebuilding context) | 112 of 258 chats compacted at least once |
| 7 | Tool output kept in context | 105M characters (≈26M tokens) of tool output in main chats: grep/find 32M, cat/sed/head 27M, git 8.5M, docker 6.5M, Read 5.3M | Every kept character is re-read on each later call |
| 8 | CLAUDE.md read every call | ≈4.5k tokens × 133k calls ≈ 60M (2%) | Already short; little to gain |

**Checked and not worth it** (smaller than expected):

| Suspected waste | Measured |
|---|---|
| Re-reading the same file | 1.8M extra characters over 14 days (top: `stream_consumer.py` 30 reads, `FOCUS.md` 23) |
| Exact duplicate tool calls | 272 of 125,438 calls |
| Huge single outputs (>20k chars) | ≈100 results, ≈3M characters |
| Sub-agent prompt cache TTL 1h vs 5m | 3.2% of sub-agent call gaps are 5–60 min; with 5m TTL their cache rewrites (≈245M) would exceed the saving (≈75M) |

## 3. Round trips that could be skipped

| What | Count | Fix |
|---|---|---|
| Calls blocked by PreToolUse hooks | 631: `cd` outside the repo 390 (mostly into the chat's own scratchpad), nested shell 77, local pnpm/npx 46, `git stash` 38, local Playwright 14, raw `git worktree` 10 | Allow `cd` into the own scratchpad; show the allowed form in the block message |
| Refused deploys | 652 (≈2,000 follow-up calls) | One preflight with all gate problems at once (rec. 5) |
| Stop hook "CI jobs running with no waiter" | 205 refused turn ends | Make `ci_coordinator submit` register the background waiter by default |
| Refused CI submits | 57 (24 are a `JSONDecodeError` crash in `submit`) | Fix the crash |
| Sleep polling | 547 `sleep` commands | Block in bash-guard with a pointer to `Monitor` / `ci_coordinator wait` |
| Duplicate asks | e.g. 3 identical asks in one minute | Dedupe in `agent_question.py` |
| Tool errors overall | 1,843 | – |

## 4. Models

| Scope | Model | Chats / agents | Calls | Units | Share of scope |
|---|---|---|---|---|---|
| Main | Opus | 153 | 57,268 | 1,414M | 83% |
| Main | Sonnet | 63 | 5,981 | 143M | 8% |
| Main | Fable | 26 | 5,543 | 142M | 8% |
| Main | Haiku | 8 | 9 | 0.3M | 0% |
| Sub-agent | Opus | 440 | 28,822 | 808M | 52% |
| Sub-agent | Sonnet | 1,020 | 31,644 | 698M | 45% |
| Sub-agent | Haiku | 336 | 4,188 | 42M | 3% |
| Sub-agent | Fable | 4 | 96 | 2.5M | 0% |

Trend: until 12 Nov most main chats ran on Sonnet. Since then nearly all run on
Opus, which follows the "new chats default to Opus" rule. Opus sub-agents were
common until 12 Nov (up to 180M units per day) and are near zero since 13 Nov.
Since 13 Nov: lane-worker on Sonnet 351, ci-runner on Haiku 108, but built-in
**Explore still on Opus (60)**, because it ignores `CLAUDE_CODE_SUBAGENT_MODEL`.

Prices differ per model, so moving work from Opus to Sonnet lowers cost even
when the token counts stay the same.

**Opus where Sonnet would do** (procedural, low judgement):
- The 16 scheduled hourly production-check chats and the build-gate-queued
  PR-preparation chats (02ce5665, f788abab, 89d37d88): short, checklist work.
- Connector delivery test chats (bb4bb205, ea94e641, a9d29c57): "run this one
  command" tasks.
- Release chat 6f9e5f06: 211 h, 19 compactions, 77M units on Opus, mostly
  waiting on CI and gates. Sonnet with a strong skill would do this work.
- Built-in Explore sub-agents (110 on Opus).

**Sonnet where Opus was needed** (high risk per the CLAUDE.md record rule):
- c54d29d7: comparing how Projects, embeds and memories are encrypted. Sonnet,
  33M units, 4 compactions; encryption is on the durable-Plan list.
- 01a9c3d4: notification titles across push and email. Ran 60 h with 6 compactions
  on Sonnet.
- 046aaebc: release PR with merge-strategy decisions. On Sonnet it stopped at
  three blocking dialogs.

**Fable**: 26 main chats. Most of them were user-chosen (`/model` to Fable typed 5
times), for example the SVG/embroidery research chats bc974296 and a73b4418
(≈56M each, 11 compactions). The real outlier is the Fable orchestrator
679b50bc. Because of its Opus general-purpose sub-agents, it alone used 27% of all
tokens.

## 5. Recommendations, ranked by impact

1. **Faster proof pipeline** (CI, `isolated-tests.yml`, `ci_coordinator.py`).
   Put the opt-in web Rust core package and the web app into the prepared
   artifacts, so that each spec job restores them and does not rebuild them (≈3 min per job).
   Bake Playwright browsers into the runner image or cache them (≈1 min). Start
   preparation when `ci-source` is taken, and reuse it for every spec of that
   source (median 6.3 min now). Reserve some hosted slots for chat jobs while
   the daily batch runs. *Expected:* one E2E 17.5 → ≈9 min median; 150–250
   chat-hours saved per 14 days. *Effort* M. *Risk* low–medium: prepared bytes
   must stay bound to the exact source (keep the existing key checks).
2. **Stop the E2E fix loop** (`ci_coordinator.py submit`, testing rule, briefs).
   After two failures of the same spec in one chat, the next submit needs
   `--after-triage`: the `failures` summary or a `test-failure-triager` /
   `e2e-test-investigator` result. Offer a one-spec warm inner loop on E2B for
   iteration, and keep the isolated CI run as the final proof. *Expected:* half
   of the 944 fail→fail reruns avoided, ≈135 CI hours, 150–250M units.
   *Effort* S–M. *Risk* low.
3. **Keep contexts small** (hooks, CLAUDE.md, settings). A hook warns at the 4th
   compaction and at the 6th asks for a Task handoff and a fresh chat. Orchestrator
   chats delegate lanes and keep their own context under ≈150k. Lower
   `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from 300k to ≈200k. *Expected:* most of
   the 23k calls above 200k shrink by ≈100k, which saves 200–350M units (6–11%).
   *Effort* S. *Risk* low–medium: more compactions, which the Task handoff covers.
4. **Fewer wake-ups** (`ci_coordinator.py wait`, ci-runner agent, peer
   messages). Wait on a whole job set with one notification (all final, or the
   first failure). Have the ci-runner report once per set. Deliver peer-chat
   messages into a mailbox shown at the next turn, unless the sender marks them
   urgent. *Expected:* 30–40% fewer wake turns, 250–350M units (8–11%).
   *Effort* M. *Risk* low if the first failure still wakes the chat.
5. **Deploy first-time-right** (`sessions.py deploy`). Run every cheap gate
   first: tracking, `--only` coverage, Specification trailers, Specification
   gate, lint, feature overview. Report all problems in one short block. Fill
   the trailers from the session's tracked Specification changes, and auto-track
   files edited in the worktree. *Expected:* refusals 652 → under 200; ≈20 h and
   40–60M units. *Effort* S–M. *Risk* low.
6. **Questions to Marco** (hook, `agent_question.py`, connector briefs). Deny
   `AskUserQuestion` in connector and headless chats, with a pointer to
   `agent_question.py ask`. Drop an identical ask sent within 30 minutes. Check asks
   against a short standing-decisions list (dev restarts and redeploys allowed,
   Specification drafts need no approval, marketing-week gate removed,
   production needs the owner) and refuse matches with the rule. Status reports
   go out as `done`, not as `ask`. The connector adds the relevant standing
   decisions to every brief. *Expected:* the 52 h of stuck dialogs, plus 10–20% of
   asks avoided at a median 5.6 h each. *Effort* S. *Risk* low.
7. **Lifecycle: waiters that never fire** (`claude_chat_waiters.py`). After N
   failed wakes with "no transcript on this host", mark the waiter failed, list
   it in the daily briefing and stop retrying. Report "typing into its pane
   failed" and lost held prompts the same way. *Expected:* the 5 chats whose
   waits never fired get noticed; 11k useless events stop. *Effort* S. *Risk* low.
8. **Trim the fixed base context** (settings, agents, `peer-chats.sh`). Disable
   generic skills this repo never uses (Office files, morning brief, memory
   import, Google Workspace, desktop and browser control). Shorten agent
   descriptions. Inject the peer list at startup only, top 3 peers. *Expected:*
   −8–10k tokens per call ≈ 110–130M units (≈4%), and faster sub-agent starts.
   *Effort* S. *Risk* low.
9. **Friendlier Bash guard** (`bash-guard.sh`, `ci_coordinator.py`). Allow `cd`
   into the chat's own scratchpad. Block `sleep N` and until-loops with a
   pointer to `Monitor` and `ci_coordinator wait`. Fix the `JSONDecodeError` in
   `submit`. Register a waiter automatically on submit, which removes most of the
   205 Stop-hook refusals. *Expected:* ≈1,400 wasted round trips and ≈7 h
   of polling, 20–40M units. *Effort* S. *Risk* low.
10. **Route models by task type** (connector launcher, agent definitions). Use
    Sonnet for scheduled checks, release and PR preparation, CI and deploy
    babysitting, docs-only work and test chats. Use Opus for encryption, sync,
    the AI pipeline, architecture and new features. Add an `Explore` override
    on Sonnet. Fable stays explicit-only. A Sonnet chat moves itself to Opus
    after two failed attempts at the same step. *Expected:* same token count,
    lower price on ≈10–20% of current Opus main-chat work. *Effort* S.
    *Risk* medium: misrouted hard tasks, which the escalation rule limits.

**How chats should be briefed** (connector and daily meeting): one bounded
deliverable per chat, the exact specs that prove it, the cheapest proving check
to run first, the standing decisions that apply, and "hand off to a fresh chat
instead of continuing past a few compactions".

## Method and limits

- Transcripts: `~/.claude/projects/-home-superdev-projects-OpenMates*`, files
  modified in the last 14 days, with their `subagents/` folders. Assistant usage
  was deduplicated by message id.
- Input-equivalent units: uncached input ×1, cache write ×2 (1h TTL), cache read
  ×0.1, output ×5. These are relative token weights and are not adjusted for model price.
- Tool time: from tool call to tool result. Parallel calls overlap, so the hours
  are an upper bound. "Chat-hours with CI in flight" is the union of each
  session's job intervals in `logs/ci-coordinator/queue.sqlite3`.
- A turn is attributed to the message that started it. Peer-chat messages are
  meta messages and were counted in a separate pass, so the 46%
  task-notification share includes some peer turns (≈169M).
- "Connector chats" could not be cleanly separated by their first message:
  66 chats start with a connector header, and many others were opened by Marco
  through the same connector. The numbers cover all dev chats.
- Not measured: time Marco spends reading pushes; whether a failed E2E rerun
  included a real code change (the source changes on every snapshot).
