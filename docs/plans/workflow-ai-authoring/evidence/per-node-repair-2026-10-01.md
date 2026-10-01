# Per-node correction and advisory Jev selection

Product revision: `7c7e9e1b209604c37fd2c4b8a0bef0faea1f2813`, deployed to dev.
The runtime coordinator restarted dependent services together under lease
`docker-7c315caf`; all were reported running and healthy.

## Changes

- Each rejected node position gets one corrected continuation. A later rejected
  node gets its own allowance. Changing a rejected node ID does not reset it.
  Accepted headers and nodes remain frozen. Header validation has an independent
  allowance; repeated completion failures or stalled continuations stop safely.
- Jev's Check and chat-delivery hints select relevant context. Gemini chooses the
  nodes the instruction needs. An unused candidate no longer rejects completion.
  Registered capability schemas, ownership, references and canonical readiness
  remain authoritative.
- On Jev outage, an existing workflow selected from the owner-scoped overview is
  loaded before transport header validation; a foreign target is rejected.
- Nonrecoverable provider request/auth/schema HTTP errors are not retried as node
  failures. Known usage survives callback errors; each continuation has a distinct
  provider step and billing identity.

## Focused verification

| Check | Result |
| --- | --- |
| Planner, compiler, Gemini adapter and billing local cohort | 110 passed in 5.24 seconds |
| Normal deployment gate | Four affected pytest files passed; Specification, lint and translation gates passed |
| Real adapter with scripted provider responses | Two different bad nodes repaired in three calls; correct frozen prefixes and cumulative usage |
| Retry boundary | Same slot fails twice and stops; changed rejected ID cannot evade limit; a later failure gets its own correction |
| Jev advisory context | Valid price filter without Check; required rain Check despite a `none` hint; false delivery hint does not forbid chat |
| Fallback edit | Owner's saved graph loaded once before validation; foreign target never loaded |
| Retry billing | Three distinct Gemini charge identities, including metered failed attempts |
| Browser repeated corrections | Isolated run 36855517388: two passed, no skips or flakes; candidate `5c5c5ff3`, equivalent test source published as `93a3c160` |

The browser case uses a controlled fragmented SSE response. The backend retry
algorithm is exercised separately through the actual adapter/compiler with
scripted HTTP responses; paid requests below do not force model errors.

The initial browser run 36853497342 passed one case and failed the new assertion
expecting a correction label while this view displays its active Processing
message. The focused fixture correction observes two distinct `retrying_node`
phase transitions, separated by `validating`, without removing pending-state or
completion checks. Its graph grows from the trigger to two distinct action nodes;
the final persisted workflow retains all three cards and one landing-page entry.
The rerun tested these assertions against immutable candidate `5c5c5ff3`.

## Real OpenMates CLI requests

Disposable CLI state and workflows only. No workflow was enabled or executed;
both were deleted after verification. Costs below are recorded provider estimates,
not a provider invoice or a conversion of billed credits.

| Request | Saved output | Total CLI time | Billed credits | Estimated provider cost |
| --- | --- | ---: | ---: | ---: |
| Headphones | Friday 18:00 UTC → shopping search, EUR marketplace `de`, maximum price 150 → matching results in chat; no Check | 8.067 s | 14 | $0.00499873 |
| Conditional weather | Weekdays 08:30 Europe/Berlin → tomorrow's Berlin forecast → exact `rain_expected` Check → requested rain/dry messages | 5.123 s | 15 | $0.00540667 |

Exact headphone input:

> Every Friday at 18:00 UTC, find noise-cancelling headphones costing no more than 150 euros and send me the matching products in chat. Name it Headphone Billing QA 9eca167a.

Exact weather input:

> Every weekday at 08:30 Berlin time, check tomorrow's weather in Berlin. If rain is expected, send me 'Take an umbrella in Berlin tomorrow' in chat; otherwise send me 'No rain expected in Berlin tomorrow' in chat. Name it Conditional Weather QA b11e059b.

| Timing | Headphones | Weather |
| --- | ---: | ---: |
| Jev selection | 0.872 s | 0.729 s |
| Gemini generation | 4.132 s | 2.337 s |
| First Gemini component, measured from Gemini call start | 3.572 s | 1.446 s |
| Validation-inclusive planner | 5.538 s | 3.516 s |
| Backend service | 7.307 s | 4.552 s |

Each request used one Jev call and one Gemini call, with no correction. Both saved
disabled. The headphone proof independently reconciled catalog credits with the
wallet debit and two Billing settings history rows (Jev 1, Gemini 13 credits).
An identical idempotency-key replay returned the same workflow in 0.877 seconds
and made no new inference, charge or history entry. Weather's recorded 15-credit
charge also matched the wallet debit.

Private synthetic receipts: `/tmp/workflow-per-node-headphones3e12.json` and
`/tmp/workflow-per-node-weather3e12.json`. They contain no credentials.

## Limits

These are focused regression proofs and two real requests, not an all-skill
accuracy benchmark. Provider generation latency remains variable. The callback
timing does not measure web delivery or actual audio transcription. Real browser
AI timing, real interrupted-model edits and completion after a clarification
reply remain outside this focused correction.
