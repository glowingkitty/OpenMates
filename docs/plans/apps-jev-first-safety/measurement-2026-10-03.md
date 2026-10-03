# Jev-first Apps safety measurements — 2026-10-03

The user approved both updated safety contracts. Source was published to dev as `dae1539e23644355996403e47a759a2b91b9fba0`, and the coordinated API/worker refresh completed healthy. The live container scanner hash matches the measured candidate. Production was untouched.

## Matched scanner comparison

The same public web-search response was processed through frozen baseline and candidate scanner source in isolated processes inside the dev API container. It contained 31 selected text units. There were ten measured repetitions per variant, alternating variants, after one excluded warmup per variant. Selected fields, Unicode cleanup, payload application, provider credentials, deadline and input bytes were identical. This isolates safety processing and does not include search-provider retrieval or API billing.

| Safety-processing duration | GPT-only baseline | Jev-first candidate | Reduction |
| --- | ---: | ---: | ---: |
| p50 (nearest rank) | 759 ms | 292 ms | 61.5% |
| p95 (nearest rank) | 947 ms | 405 ms | 57.2% |

All 20 measured scans completed without technical error and preserved the full cleaned response exactly. Candidate calls used `typesafe/jev-1.13-20260917`; baseline calls used `openai/gpt-oss-safeguard-20b`. There was one decision-provider call and no GPT fallback in each measured candidate sample. A temporary benchmark-harness error was corrected before this valid measurement; its failed receipt is retained separately.

The configured Jev model is `typesafe/jev-1.13`, using the existing safe threshold of 0.20, a one-second total deadline and no retry. Confident safe batches do not generate per-field verdict objects. Flagged, ambiguous, invalid or unavailable decisions retain the existing exact-span GPT classification. Caller cancellation propagates. No field-selection or delivery policy was removed to achieve the speedup.

## Deployed API and CLI comparison

The before and after runs used the same fifty-query committed `app-skill-safety-v2` manifest, six results per request, US/en/moderate settings and default protection. Calls ran sequentially through the CLI, with one excluded warmup per variant. All 100 requests returned successful results. These are live external searches, so provider response content and latency can vary between the runs; the alternating frozen-payload measurement above separately isolates the scanner.

| Duration | Before p50 | After p50 | Before p95 | After p95 |
| --- | ---: | ---: | ---: | ---: |
| Server safety phase | 1,079 ms | 323 ms | 1,304 ms | 511 ms |
| API HTTP response, including body | 2,671 ms | 2,431 ms | 3,436 ms | 3,019 ms |
| CLI process through complete response | 3,128 ms | 2,900 ms | 3,883 ms | 3,491 ms |

Safety improved by 70.1% at p50 and 60.8% at p95. Total API time improved by 9.0% and 12.1%, respectively; CLI process time improved by 7.3% and 10.1%. The scanner reduction is not the total-request reduction: the remaining provider, authorization and billing work varied between runs.

All fifty candidate requests produced one confident-safe Jev decision, no GPT fallback and no unscanned technical failure. The baseline logged two invalid GPT responses and delivered those two requests under the existing fail-open policy. Initially missed contextless scanner log lines were recovered by matching each serial HTTP interval; those baseline errors are included in the retained phase receipts.

## Quality and coverage

Seventy-two focused backend regressions passed. They cover field cleanup and selection, Jev safe decisions, exact-span fallback, ambiguous/invalid decisions, timeout cancellation, caller cancellation, invalid inputs, and shared dispatch without duplicate scanning. All four real-inference REST/CLI cases passed across the focused runs: authenticated REST web read, two-page CLI web read with protection enabled/disabled, and two benign YouTube transcript comparisons. The read checks now use the shared V2 credential splitter and assert the actual retrieved documentation text; exact page and transcript parity remains enforced. The disposable REST device was approved through the authenticated first-party session, then its key was revoked. Initial test-harness failures remain in private receipts.

Both variants passed all eight versioned real-model corpus cases on the repeat run, including indirect instructions, forged system authority, exfiltration, tool use, cross-snippet instructions, metadata attacks, and benign quoted API documentation. Benign text and skipped URL fields were preserved. Jev routed attack batches to exact-span review. The initial run had one invalid GPT classification per variant; these failures remain in `quality-first.json` and are not called successful scans. GPT fallback reliability remains a separate concern under the existing logged, fail-open policy.

GitHub run 37117204918 failed during dependency installation before any selected tests ran: backend requirements select git `toon-format` 1.0.0 while the Python SDK pins 0.9.0b1. This is infrastructure failure, not passing CI evidence. The independent CI setup was left unchanged; CI execution remains unverified.

## Deployed web walkthrough and embeds

Desktop web execution preserved the current skill route and input through login without reloading. Context/help remained collapsed by default and opened on demand. Native result cards appeared below the form without automatic fullscreen navigation, and retained graphs reached the saved state.

These are single sequential observations with live provider variation, not a statistically matched surface comparison. Browser API duration starts at the button click; REST and CLI HTTP durations start at request dispatch. Web search returned ten results. Health returned four in web/REST and three in CLI as live availability changed.

| Skill | Web click → API body | Web click → visible cards | Response → visible | REST HTTP body | CLI HTTP body |
| --- | ---: | ---: | ---: | ---: | ---: |
| Web search | 3.732 s | 4.013 s | 281 ms | 2.001 s | 2.568 s |
| YouTube transcript | 6.511 s | 6.574 s | 63 ms | 6.381 s | Provider timeout |
| Health appointments | 5.487 s | 5.708 s | 221 ms | 5.055 s | 6.649 s |

The separate transcript CLI request hit the existing 45-second provider-fetch deadline before safety scanning. Its failure is retained; it is not counted as a successful request. The two versioned benign CLI transcript parity cases passed earlier. Completed walkthrough calls spent 278–464 ms in safety for Health, 286–330 ms for transcripts and 339–361 ms for web search, each with one safe Jev decision.

Embed construction, encryption and durable local staging happen on the client. Encryption totaled 0–1 ms per web sample. The response-to-visible measurements above also include local staging, preview hydration and rendering. Remote account graph saves took 0.837–4.220 seconds and were still in the saving state when cards became visible. All three then reached saved state. Removing retained embeds would sacrifice the requested default without removing the main API delay.

## Recommended next optimizations

1. Improve provider tails first. The live YouTube CLI request timed out before producing transcript content, while the same video's web/REST calls succeeded. Earlier traces also showed several serial provider requests and a 23.7-second caption attempt. Bound/review provider attempts, reuse connections and eliminate redundant discovery/availability calls where provider contracts allow it. No transcript cache is proposed.
2. Reduce noncritical work after authoritative billing. Earlier measured billing stages took roughly 0.46–0.83 seconds. Move notifications and other noncritical work to reliable background execution; daily/monthly summaries cannot be deferred safely while API-key budget checks depend on them. Measure correctness and total latency before changing that boundary.
3. Reuse an owned HTTP connection pool for Jev. The provider client already accepts an injected async client; currently each scan constructs and closes a client. Measure the reduction before selecting a tighter deadline.
4. Consider incremental results only where the provider can produce usable groups earlier. Stream checked groups with the same credit authorization, safety context, stable IDs and durable client outbox. Streaming one complete provider response before background remote embed saves would duplicate the current behavior and provide little first-result gain. Streaming unsafe text before its safety verdict would change the approved contract and is not part of this implementation.

## Source identities and private evidence

Baseline scanner SHA-256: `aa1b6626acc4f3e8048b2c7d65f50cce3087c496a4fca96854b70b36a74b79bb`.

Candidate scanner SHA-256: `e1987776aa581790290a023bd2ce1337669682e2c5c02c6dbbae7ae65271b8bb`.

Private receipts: `test-results/apps-latency/20261003-jev-first/` contains paired corpus evaluations, per-request before/after phase timings, matched scanner timings, live REST/CLI reports and source hashes. Raw provider payloads and auth/runtime logs remain private and are not committed.
