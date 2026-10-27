# Mercury 3 evaluation — 2026-10-20

**Completed native benchmarks favor Mercury low for transcript correction and
Mercury instant for a scoped workflow-authoring pilot. Preserve general Gemini
defaults.** All 54 fast-suite requests and 48 workflow rows completed through
direct APIs after the earlier intermittent 429s. The actual nonstreaming correction
facade then passed all six synthetic transcript cases using direct Mercury low.
Dev activation and shared-runtime verification are recorded below.
No account, chat-model or automatic-routing defaults were changed.

Mercury is already published for manual selection through **model selector →
More providers → Inception → Mercury 3**. Manual selection is separate from its
disabled automatic-routing gate.

## Native benchmark identity and scope

Both completed reports use published harness revision
`7fb52e4ad35cf31190abc80ec30f8345721229e3` against product runtime
`0cbcf2c715b49c83424f028659948683b4dbc94e`. Runtime sidecars establish that the
only backend differences were the two benchmark modules and their tests; product
dependencies were identical. The published harness loaded in disposable child
processes, without shared runtime mutation. API image:
`sha256:6161df56fb6801d796e05c263a84aa8d8efa93358fc11f70b87bab92663e4a1f`.

Private receipts are archived under the dev checkout’s
`logs/mercury-fast-inference/acad-2026-10-20/`; original paths are
`/tmp/mercury-acad-native-fast.json` and
`/tmp/mercury-acad-native-workflow.json`, with corresponding `-runtime.json`
sidecars. Both reports record `partial: false` and zero skipped results. Inputs
are synthetic; the workflow evaluation compiles in memory without creating or
executing real workflows.

Fast-suite Gemini is **Gemini 3.8 Flash low**, compared with direct `mercury-3`
**instant** and **low**. Streaming timings exclude credential loading, ASR,
persistence and UI. They are not production nonstreaming correction timings.
Workflow authoring uses the same three reasoning configurations, native logical
schemas and production parser/compiler/retry loop. Its wall time includes
correction attempts; shared Jev preselection is measured separately.

## Transcript correction: low preserves meaning better than instant

Six multilingual cases, repeated twice per arm; **36 HTTP 200 responses**.
Strict scores are finite required/forbidden-pattern checks. Manual review checks
the retained text's meaning independently of those patterns.

| Configuration | Strict pass | Manual semantic pass | Median complete response | Mean uncached supplier estimate per transcript |
| --- | ---: | ---: | ---: | ---: |
| Gemini 3.8 Flash low | 12/12 | 12/12 | 3.302 s | $0.00135131 |
| Mercury instant | 5/12 | 5/12 | 0.507 s | $0.00009697 |
| Mercury low | 12/12 | 12/12 | 0.750 s | $0.00015976 |

Instant's speed came with unacceptable meaning-preservation failures. Low had
no material manual semantic concern across these twelve outputs. On this small
set, low is the justified Mercury correction candidate; instant is not.

The prices are uncached token-based supplier estimates using the current
promotional Mercury rates, not actual charges or customer-credit totals.
Repeated synthetic cases and provider caching affect timing; twelve outputs per
arm do not establish production reliability, p95 or universal language coverage.

## Bounded writing: automated passes overstate Mercury quality

Three tasks, repeated twice per arm; **18 HTTP 200 responses**.

| Configuration | Strict pass | Manual semantic pass |
| --- | ---: | ---: |
| Gemini 3.8 Flash low | 4/6 | 6/6 |
| Mercury instant | 5/6 | 4/6 |
| Mercury low | 6/6 | 5/6 |

Gemini's German approval wording caused two regex false negatives. Instant had
one email-pattern false negative but also made two unsupported claims about an
incident investigation. Low's summary introduced unsupported claims that no
progress had occurred and no reason had been provided. Preserve these distinctions:
a correct-looking schema or strict pass is not evidence that every fact is grounded.

Across transcripts and writing, manually accepted outputs were **18/18 Gemini,
9/18 instant and 17/18 low**. This supports a specific correction pilot, not a
general replacement of Gemini for low- or medium-complexity generation.

## Workflow authoring: instant earns a scoped pilot

Eight requests repeated twice per author; **48 completed rows, zero HTTP 429s**.
All 48 compiled plans received manual review. Full validity and intent fidelity
are separate outcomes.

| Author | Full valid graph | Valid plus strict intent match | Median wall time including retries | First header / first node median |
| --- | ---: | ---: | ---: | ---: |
| Gemini 3.8 Flash low | 16/16 | 16/16 | 4.294 s | 2.535 / 2.983 s |
| Mercury instant | 16/16 | 16/16 | 1.426 s | 1.128 / 1.140 s |
| Mercury low | 15/16 | 14/16 | 2.571 s | 1.854 / 1.859 s |

Low failed `events_free_text`, repeat 1: two HTTP 200 responses placed forbidden
`capability: "ai.ask"` on an `ask_ai` node. Correction repeated the schema error;
only the validated search prefix survived. This was a model/schema failure,
not transport rejection. In `mixed_create_update`, repeat 1, low added an
unrequested existence Check and “no matches” notification. Its price filter
remained correctly structured; the oracle's “filter became a Check” wording
overstates that particular defect.

Manual review found four Gemini graphs with invented historical `starts_at`
dates. They precede the evaluation date and currently do not postpone execution,
but are unsupported configuration despite strict passes. All authors' subjective
news plans deliver the whole search list after an aggregate relevance decision;
this does not prove per-item relevance filtering. No additional major
Mercury-instant defect was found in these sixteen plans.

| Author | Known uncached supplier-cost subtotal, all attempts | Rows with complete cost estimates | Median cost on complete rows |
| --- | ---: | ---: | ---: |
| Gemini | $0.09899850 | 14/16 | $0.00488175 |
| Mercury instant | $0.01401070 | 13/16 | $0.00084375 |
| Mercury low | $0.01695140 | 14/16 | $0.00104543 |

These **incomplete subtotals are not final charges or directly comparable full
run totals**. Missing/prematurely terminated usage remains unknown. Estimates
include reported reasoning once and use uncached promotional prices. Instant
reported 69 and 129 reasoning tokens on two calls; do not assume its reasoning
usage is always zero. Reported cached input among metered author attempts was
23.0% Gemini, 54.6% instant and 78.9% low, affecting observed timings.

Common Jev selection was measured once for eight cases: estimated **$0.00430134**
in total, median **$0.000535565 per case** and **0.423 s**. It is separate from
author timing/cost and must not be silently attributed to only one author.
Eight synthetic requests repeated twice cannot establish production p95 or
broad workflow quality.

## Availability context and public evidence

Earlier direct and gateway probes intermittently received HTTP 429; the gateway
partial suite is availability context, not the completed native benchmark.
Its private receipts remain `/tmp/mercury-acad-fast-partial.json`,
`/tmp/mercury-acad-fast-runtime.json`, `/tmp/mercury-acad-gateway-smoke.json`,
`/tmp/mercury-acad-gateway-backoff.json` and `/tmp/mercury-acad-smoke-runtime.json`.
Gateway timing cannot establish direct performance. Product Mercury routing
remains direct Inception only; OpenRouter was authorized for synthetic evaluation.
Harnesses stop at their first 429 and record skipped work without a quality verdict.

Inception documents **429 as rate limit reached**, whereas **503 means engine
overloaded**. Earlier 429s do not establish a broad outage or show that our few
requests overloaded their infrastructure. The completed native runs demonstrate
usable capacity during those runs, not an availability guarantee.
[Official errors](https://docs.inceptionlabs.ai/resources/error-codes).
Published free-tier limits are 1,000 RPM, 1M input TPM and 100K output TPM;
pay-as-you-go lists 3,000 / 3M / 300K. Exact admission-limit cause remained
unverified. [Official rate limits](https://docs.inceptionlabs.ai/get-started/rate-limits),
[documentation export](https://docs.inceptionlabs.ai/llms-full.txt).
No accessible October 19–20 official incident notice was found in the
[launch post](https://www.inceptionlabs.ai/blog/introducing-mercury-3) or
[LinkedIn feed](https://www.linkedin.com/company/inception-labs-ai); X could not
be retrieved and no verified official public status board was located.

See [the cited public comparison](public-benchmarks.md): AA Gemini 3.8 Flash
scores 33/40/41 for low/medium/high effort on Index v4.3.2. No matched Mercury 3
AA result was verified. Inception's medium-effort chart has no Gemini column;
its 1,068 tokens/s is throughput, not complete-task latency. Public scores do
not supersede the native task-specific defects above.

## Product state, verification and next decision

- **Transcript:** select Mercury **low**, retaining the five-second deadline,
  zero correction retries and Gemini fallback. Native nonstreaming tool responses
  legitimately return `finish_reason: stop`; the helper now accepts `stop` and
  `tool_calls` while rejecting truncated/blocked/missing finishes and malformed
  tools. Published helper `7953961367c28d3de00db6f4bd9e1079448456dd` passed six
  synthetic cases through the actual facade, with no fallback, in 0.737–1.547 s
  (median 0.918 s). All six retained outputs were also manually reviewed. Private
  receipts in the private archive: `mercury-acad-correction-helper.json` and its `-runtime.json`
  sidecar. The published helper loaded only in the disposable child process;
  the shared gate was still OFF during this preliminary proof.
  The first enabled-service check then stopped at case five: the corrected date
  was present but the retracted date remained too (4/5 strict passes). This is a
  cleanup defect, retained in `correction-deployed-initial-cleanup-miss.json`
  under the private receipt archive. The benchmark's twelve transcript passes
  were therefore insufficient to establish consistent cleanup. Revision
  `e27304e2c31f76c5b23714c094ca3a7e7f89fbd7` clarifies that explicit replacements
  retain only the final intended version, while preserving intentional contrasts
  and treating quotations as data. This refined actual facade passed twelve
  repeated direct cases (all manually reviewed), median 0.706 s, with no fallback.
  Its prompt differs from the earlier paired benchmark; its timing is a separate
  nonstreaming observation, not a new paired Gemini comparison. Refined receipts:
  `mercury-acad-correction-refined-helper.json` and its `-runtime.json` sidecar.
  **Enabled and verified on shared dev:** coordinated configuration operation
  `docker-4baf58cc` set the opt-in flag after the initial facade proof. Source
  refresh `docker-a2fe2078` then applied the refined helper; all services passed
  health checks. Runtime and helper both matched `e27304e2c31f76c5b23714c094ca3a7e7f89fbd7`.
  The final actual-module check asserted the source bytes and shared gate, using
  no test-only gate override or helper injection: all six direct corrections
  passed (manually reviewed), no fallback, median **0.795 s**, range 0.766–1.057 s.
  Receipts: `mercury-acad-correction-deployed.json` and its `-runtime.json` sidecar
  in the private archive. This enables ordinary batch/realtime audio correction;
  workflow speech correction and production configuration remain unchanged.
- **Workflow:** Mercury **instant** is the stronger candidate for a scoped pilot.
  Workflow defaults remain Gemini; the sample does not authorize a broad switch.
- **General requests:** preserve Gemini and existing automatic routing. Complexity
  tiers and reasoning effort are different axes; these results do not establish
  general medium-tier parity or justify a blanket low-tier replacement.
- **Manual selection:** published direct-only entry exists. Isolated browser CI
  passed on source `4a71c76d9d7f25979609540dd81ad73429d1926f`, run `39405570105`,
  request `f79efd519e5dfe7aa7bd403ad2465d969923026617d6e2c7a1b1e49e47a3df28`.
  It verifies provider/model icons load, medium capability, exact draft selection,
  checked selection on reopening and return to Auto, without inference or account
  defaults changes. The latest successful recording was uploaded through its
  `codex-evidence.json` receipt. This proves selector behavior, not inference quality.

The direct provider adapter, privacy disclosure and launch customer discount
were published in `1891f7aa7700b9998b36530ba6121e839968f53e`. Customer allowances
remain 3,300 input / 950 output tokens per credit during the promotion, versus
regular 1,650 / 475. Supplier launch prices are $0.10 input / $0.35 output /
$0.01 cached input per million tokens, versus regular $0.20 / $0.70 / $0.02.
No published promotion expiry was established. The account owner confirmed on
October 20 that “Improve the model for everyone” is OFF on the direct account.
No unconditional zero-retention promise follows from that setting.

Focused checks passed: 33 benchmark tests, 29 provider/metadata tests, and 20
correction tests after the terminal-reason fix, plus Ruff and diff checks.
The deployment helper's pytest gate skipped because its backend venv was absent;
the focused local tests above ran separately. Earlier isolated audio UI CI passed
13 checks (one retry), source `a08010f4a12e3db18d36f0bffe1159d3a0fba10e` / run `39391718999`; it verifies the ordinary
audio path with controlled provider responses, not live Mercury quality.
