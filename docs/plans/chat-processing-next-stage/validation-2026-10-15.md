# Chat timing and foreground notifications — 15 October 2026

## Acceptance

For both new chats and same-chat follow-ups, selected Mate feedback must arrive within 2,000 ms of Send; 1,500 ms remains the aim. Simple no-tool authored answers must start within 2–3 seconds. Verify real automatically routed Gemini inference using the personal development test account, first on TUI and then web. No model or provider override is permitted. Audit request-related client and backend errors as well as answer correctness.

## Retained real TUI baseline

The isolated personal-account run used the deployed processing flow and normal automatic Gemini routing. These are individual observations, not a percentile or acceptance result.

| Milestone from Send | Spain, new chat | France, same-chat follow-up |
| --- | ---: | ---: |
| Optimistic user row | 31 ms | 27 ms |
| Selected Mate | 1,427 ms | 29,380 ms |
| First authored text | 6,616 ms | 32,986 ms |
| Authoritative response terminal | 8,209 ms | 34,310 ms |
| SDK final presentation | 18,917 ms | 46,441 ms |

The follow-up spent 28.0 seconds before server admission while account-wide recovery and phased synchronization ran. The terminal-to-final gaps included unrelated recovery reads; they must not be labelled only as required persistence. The first provider call spent about 3.44 seconds before authored output, with a 7,327-token prompt. A follow-up provider call spent about 2.06 seconds with 7,582 prompt tokens. These boundaries distinguish client preparation, orchestration and provider inference.

## Scoped corrections and verification

- Send preparation reads fresh authorized metadata and message windows for the current chat, carrying the exact ciphertext, key wrappers and message version into the send. Account-wide recovery remains separate from current-turn required recovery.
- Optional Task discovery is bounded to one fresh page of at most100 rows, with independent current-chat linkage and exact dependency reads. The retained first-send trace had six discovery pages costing2,495 ms and26 CMS Task reads; the public exhaustive Task listing remains available.
- Only selected or explicit related work blocks optional prompt reduction. Unselected discovery rows no longer silently force the larger prompt. Required ethics and privacy instructions remain included.
- Google SDK client cleanup releases references after the worker event loop stops, preventing destructor-created pending close tasks. Shared embed-type metadata resolves its real container path.
- Fresh per-connection foreground web and interactive TUI presence suppress both chat email and push, including new chats before active-chat selection. Gates run before queueing and at delivery. Background, closed, expired, headless and other users' sessions do not claim human presence. Apple application code is outside this change.
- Recovery retains authority and cryptographic checks while allowing one fenced transient retry, and defers known children until their matching parent is canonically verified and acknowledged. The exact composite browser case passes first attempt with11 ready/typed ACK/ACKNOWLEDGED outputs, reload and fullscreen checks, and zero recovery console errors (run 38734294283).

Focused verification:178 CLI client tests,45 Task/preparation tests,24 merged web recovery tests, and359 related backend tests pass. Retained Mailpit integration passes without retry (run 38728559354); both combined CLI privacy/terminal-streaming integration cases also pass (run 38736188315). Five corrected-transcript recording cases pass on their first attempt with zero skips or flaky cases (run 38738168927). These provider-free checks do not certify latency.

Deployment, provider-free integration success and real latency acceptance are distinct. None of the proposed corrections alone certifies the targets.


## Deployed checkpoint and latest real measurements

The measured deployed revision is `ba8654432f0a4476e6c71b7c9b4bfd5b10ddbe8c`; the installed CLI release is alpha79. The admission proof, independent client preparation, pending viewer/auth ownership and Workflow delivery event-loop corrections are deployed at this checkpoint. They preserve authoritative context and privacy checks. The later CLI overlap candidate `e7e60` is not published: its isolated CI failure remains under diagnosis. A further web guard correction is in progress and is not part of these measurements.

Actual inference used existing automatic routing without model, provider or thinking overrides. Required ethics and mandatory privacy instructions remain unchanged. The personal development test-account credit fixture was restored before web v7 after its balance became negative; this is development-only test setup, not a production balance, budget or permission exemption. Fresh spending/authorization gates remain enforced.

### Actual product TUI v6

| Milestone from Send | Initial factual turn | First factual follow-up | Second factual follow-up |
| --- | ---: | ---: | ---: |
| Optimistic user row | 31 ms | 26 ms | 29 ms |
| Selected Mate | 1,417 ms | 2,395 ms | 2,704 ms |
| First authored text | 3,988 ms | 4,502 ms | 5,018 ms |
| Authoritative response terminal | 5,333 ms | 5,940 ms | 6,812 ms |
| Required reply persistence | 5,493 ms | 6,179 ms | 7,043 ms |
| SDK final presentation | 5,493 ms | 6,179 ms | 7,044 ms |

All three expected answers were visible. The initial Mate meets the 2,000 ms hard limit and 1,500 ms aim; both follow-ups miss the hard limit. All three simple authored-text results exceed 3,000 ms. The raw audit fails on two client HTTP-error records across 924 records / 94 observed request identities, with zero related backend errors or capture gaps; correct answers do not make this a clean acceptance run.

### Instrumented ordinary web v7

| Milestone from Send | Initial factual turn | First factual follow-up | Second factual follow-up | Initial Events turn |
| --- | ---: | ---: | ---: | ---: |
| Optimistic user row | 249 ms | 4,200 ms | 667 ms | 201 ms |
| Composer clear | 44 ms | 30 ms | 61 ms | 26 ms |
| Selected Mate | 1,925 ms | 4,545 ms | 2,489 ms | 1,866 ms |
| First authored paint | 4,191 ms | 7,697 ms | 5,784 ms | 12,641 ms |
| Captured source final | 5,542 ms | 9,100 ms | 7,683 ms | 19,310 ms |

Only the two initial Mate observations meet the 2,000 ms hard maximum; neither reaches the 1,500 ms aim. Both factual follow-up Mate observations and all three simple authored-text observations miss acceptance. Events requires tool work and is reported separately; a harness authored_target_met flag on this tool case does not certify the simple no-tool 3-second target. Source-final events are not independent proof of required encrypted persistence.

The Events follow-up failed the visible optimistic-row assertion. Server logs prove admission and typing began for that turn; the retained evidence does not establish whether the row was removed or outside the viewport. Its response completion therefore has no accepted web timing. Capture overflow at 2,000 records leaves a gap. The raw audit fails with 185 client-error records, two correlated backend errors and 38 backend errors requiring correlation; these are audit records, not distinct root-cause counts. The harness still reports low-thinking verification incomplete. Visible model identity alone cannot establish provider thinking policy.

Web v6 also remains a failed raw audit despite three correct factual answers. Its six wrapper ambiguity logs concern two historical client-encrypted embeds created over 37 hours earlier, not current factual outputs. Read-only inspection finds eight rows: two master and two chat wrappers per embed, with differing ciphertext in every duplicate pair. Do not autoheal, choose the first row, delete account data or weaken crypto/owner fences. Reconciliation requires explicit cryptographic validation and an approved migration. The current-chat message-window404 is a separate pre-admission new-chat request; it must not be conflated with old recovery or hidden by generic404 suppression. Web v7 additionally exposes an optional stale composer-suggestion persistence result incorrectly surfaced as a generic error; its source/authority fences remain required.

### Events TUI v6 critical path

The initial Events turn paints its Mate at 1,315 ms, tool progress at5,533 ms and authored answer at 12,514 ms; terminal is18,606 ms and required persistence 29,564 ms. The request audit passes across1,156 records with zero client/backend faults or capture gaps. Correctness and timing remain separate.

The following nonoverlapping intervals sum to approximately12,514 ms; nested provider spans are not added again:

| Critical interval | Duration |
| --- | ---: |
| Send through first main-provider SDK request | 3,290.6 ms |
| First SDK request through Events dispatch | 2,213.3 ms |
| Events search and finalist enrichment | 3,159.9 ms |
| Safety/formatting/provider lookup/skill billing | 874.4 ms |
| Embed preparation, durable CMS batch and ordered publication | 637.2 ms |
| Continuation setup | 441.4 ms |
| Second SDK request through authored provider text | 1,740.4 ms |
| Provider text through TUI paint | approximately 157 ms |

Search providers run concurrently; their individual durations must not be summed. Ten children plus parent use two CMS recovery RPC completions, versus 33 in the historical design trace. This establishes a call-count improvement, not a controlled latency comparison. Selected Workflow hydration contributes a 777 ms branch during overlapping initial setup, including an approximately 506 ms credential-refresh component. It reads selected Workflow identities, not all account Workflows; an empty selected list returns without hydration.

The 10,958 ms terminal-to-persistence tail is client result recovery: approximately 2,119 ms for 11 serial store_embed operations, followed by 8,659 ms for 11 serial sealed-output read/verify/ACK cycles. Those cycles include 32 serial canonical embed HTTP reads totaling 7,599 ms; that nested duration is not added again. Answer recovery is already persisted by 18,717 ms. Postprocessor metadata arrives at 22,487 ms while output recovery continues and does not cause the remaining tail. Required ciphertext, parent scope, wrapper, identity/digest and acknowledgement checks cannot be omitted to shorten it.

The Events follow-up does not execute another Events search. Mate is 3,301 ms, first authored paint 12,914 ms, terminal 19,409 ms and required persistence 19,668 ms. Detailed Jev runs 12 questions / 4,584 input tokens in 459 ms. Default routing selects medium complexity and MEDIUM thinking; approximately7,732 ms of the main-provider call precedes authored text. This is the recorded automatic policy, not an override to LOW. No recovery parallelization or policy override is activated for this checkpoint.

These are individual observations, not percentile guarantees. Focus and remote Project summary real-inference scenarios remain pending because ordinary initial/follow-up targets failed; they cannot be marked accepted from unrelated unit or integration checks.

## Retained isolated integration evidence

| Scope | Successful run | Bounded result |
| --- | --- | --- |
| CLI privacy and terminal streaming | [38736188315](https://github.com/glowingkitty/OpenMates/actions/runs/38736188315) | Two cases pass; the previous pending-CLI statement is superseded. |
| Composite recovery | [38734294283](https://github.com/glowingkitty/OpenMates/actions/runs/38734294283) | 11 outputs ready, typed-ACK and acknowledged; reload and fullscreen assertions pass, zero recovery console errors. |
| Foreground chat notifications | [38728559354](https://github.com/glowingkitty/OpenMates/actions/runs/38728559354) | Retained Mailpit/foreground notification integration passes without retry. |
| Corrected-transcript audio input | [38738168927](https://github.com/glowingkitty/OpenMates/actions/runs/38738168927) | Five cases pass on attempt zero, no errors/skips/flaky cases; editable corrected text and notes are explicitly sent without permanent recording embeds or upload storage. |

The audio test-only source differs from the combined product candidate only in its test file, and reused prepared web/CLI bytes plus API/CMS/setup/schema runtime images. Its 81.656-second browser suite and successful evidence upload do not imply faster inference or zero-wait CI: the request still waited 507.786 seconds for preparation. Retained verification remains specific to the tested source; pending follow-up repairs need their own final activation and acceptance results.

## Final acceptance and freeze

Status: **Task acceptance incomplete**. Ordinary TUI and web follow-ups miss selected-Mate targets; all measured simple authored responses miss 3 seconds; latest factual/web error audits fail. Focus and remote Project summary real-inference tests remain pending in the required order. Existing isolated correctness evidence does not close these gaps. Any unpublished CLI overlap or web guard candidate needs its own passing checks, publication and comparable default-routed measurements before being described as deployed or faster.

Required encrypted reply persistence, authoritative terminal completion and optional late metadata remain separate milestones. Mandatory ethics/privacy, encryption, fresh authority, selected-resource and spending checks remain unchanged. Historical duplicate crypto wrappers are not eligible for automatic healing.

The explicit deployment/testing freeze is **15 October 2026 at 17:00 Europe/Berlin (15:00 UTC)**. All deployments and runtime mutations must finish before that cutoff so subsequent manual web testing sees a stable revision. This document records the ba865/alpha79 checkpoint; no Apple application code is in scope.

## Resumed development after the testing freeze

The user explicitly authorized completing and deploying the remaining work after the earlier freeze. Preserved client changes were published as `dd1544f5cb99a5f54c0e68c5b7492065e3221904`; application inputs matched the prior passing integration source, with only six supporting test annotations added. The deployed API remained the earlier ba865 checkpoint.

A subsequent real default-routed TUI factual sequence had correct Madrid/Paris/Berlin answers, no app skills and unchanged mandatory instructions/default Gemini LOW policy. These individual observations still miss latency acceptance:

| Milestone | New factual chat | First follow-up | Second follow-up |
| --- | ---: | ---: | ---: |
| Optimistic user row |29ms|26ms|25ms|
| Selected Mate |1453ms|2210ms|2542ms|
| First authored text |4476ms|6424ms|5247ms|
| Required persistence |6161ms|8288ms|7416ms|

The request audit passes across913 captured records, with two mechanically identified owned-viewer cancellations, zero client faults, zero related/unattributed backend faults and no capture gaps. Its nonzero benchmark status represents missed latency targets, not failed answers or a clean-audit waiver. All three turns skip detailed preprocessing with a complete empty-context proof and use zero tools. Provider SDK-to-authored times were2444/3220/2092ms; the first follow-up's additional latency is predominantly provider time, not a new serialized discovery branch.

The account-key gateway issue is separately confirmed and repaired: the configured app Origin receives200 credentialed preflight over HTTP/1.1 and HTTP/2, an untrusted Origin receives400 without Allow-Origin, and unauthenticated GET reaches API authorization and receives401. No account key, permission or crypto validation was bypassed. The active Caddy route restoration uses an exclusive native lease and full-config ETag; repository configuration already contained the route. Startup-file drift remains detectable through the mandatory host preflight verifier.

The resumed combined increment includes saved-follow-up phased admission, context-binding-before-ACK, historical encryption batching, bounded CLI output recovery and source-correlated stale composer-suggestion results. Focused checks prove their correctness boundaries; final exact-source integration, activation and real latency measurements remain distinct. This checkpoint does not certify the2s Mate or3s authored targets.


## Final request-error correction

The user accepted the measured processing times and made absence of request-related client/backend errors the immediate priority. Earlier timing tables remain observations; they are not the current completion gate.

Saved web follow-ups classify creation metadata using the acknowledged canonical predecessor version, even when the local message counter is stale. The expected version, immutable retry journal, history and encryption checks remain required; the backend still rejects attempts to replace existing immutable metadata.

An explicit, trusted, inactive non-Project Focus activation is a control turn without an answer profile. Speech preparation begins on its resolved answer continuation. Ordinary answers retain on-demand speech preparation and genuine profile failures remain visible. Recent-work active/read/completion/write calls across the continuation use the original admitted inference authority, while their revision retains the actual executor identity. Owner, latest source-turn, active-task and completion-permit checks remain unchanged.

Focused checks cover stale local web counters, Focus speech activation/continuation and recent-work root/child identity with stale-root and stale-source denial. Real-inference audits are recorded separately after deployment. Historical duplicate encrypted wrappers require cryptographic reconciliation; they must not be arbitrarily selected, deleted or excluded from raw error evidence.
