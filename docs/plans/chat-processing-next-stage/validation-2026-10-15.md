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
- Recovery retains authority and cryptographic checks while allowing one fenced transient retry, and defers known children until their matching parent is canonically verified and acknowledged. The exact composite browser case passes first attempt with11 ready/typed ACK/ACKNOWLEDGED outputs, reload and fullscreen checks, and zero recovery console errors (run38734294283).

Focused verification:178 CLI client tests,45 Task/preparation tests,24 merged web recovery tests, and359 related backend tests pass. Retained Mailpit integration passes without retry (run38728559354); the combined CLI privacy integration is pending. These provider-free checks do not certify latency.

Deployment, provider-free integration success and real latency acceptance are distinct. None of the proposed corrections alone certifies the targets.
