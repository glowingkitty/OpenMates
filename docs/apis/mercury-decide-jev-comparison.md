# Mercury Decide and Jev 1.14: bounded provider comparison

Observed 2026-10-20. Mercury answered all 29 completed paired cases correctly,
versus Jev's 27/29, but its paid OpenRouter route then returned two consecutive
HTTP 503 responses. Mercury's planned three-repeat run is incomplete. Jev was
faster on these routes. This small test supports further evaluation, not a
production provider or default change.

## Routes and contract

Jev used direct `https://api.typesafe.ai/v1/systemone`, model `jev-1.14.0`.
Mercury used paid `https://openrouter.ai/api/alpha/decisions`, requested model
`inception/mercury-decide`; every valid response resolved to
`inception/mercury-decide-20260930`, provider `Inception`.

Mercury requests required `provider: {zdr: true, data_collection: "deny",
only: ["inception"], allow_fallbacks: false}`. No free route or fallback was
used. The direct Inception credential was unavailable. Consequently these are
direct-Jev versus routed-Mercury end-to-end timings, not isolated model compute
or equivalent network-hop measurements.

Both models return native typed decisions with choice probabilities. No
generated natural-language score was compared with a calibrated Jev score.
Each question used the same three outcomes: `match` (all requirements evidenced),
`reject` (a contradiction), and `unknown` (missing required evidence without a
contradiction). Probability quality was measured using multiclass Brier loss,
the sum of squared errors across the three probabilities, averaged per case.
Native confidence fields were retained privately but not treated as accuracy
probabilities. This hand-labeled sample cannot establish calibration.

The logical evidence, questions and public JPEG bytes were paired. Jev received
UUID-referenced native image assets. OpenRouter Mercury received a top-level
state array containing a plain JSON string of the same text evidence followed
by image data-URL parts. Images nested in a state object were avoided on that
route. Serialization, provider tokenization and image accounting differ.
The native structured state and routed flat image presentation may themselves
affect performance, so this compares endpoint/protocol combinations rather than
isolated intrinsic model quality.

A separate read-only audit reconstructed all 91 request payload hashes against
the exact executed script, confirmed matching logical text/questions and image
bytes/order across routes, and found no expected labels in requests. It visually
checked all five public JPEG fixtures and independently recomputed every valid
answer's correctness and Brier loss without discrepancies. This found no image
adapter fault; it does not remove the presentation and route differences.

## Fixtures and execution

The harness is `backend/scripts/benchmark_mercury_decide_jev.py`; its native
choice contract helpers are in `backend/scripts/benchmark_decision_contract.py`,
without a dependency on unpublished prior benchmark scripts. It defaults
to dry-run, uses Vault inside the existing `api` container, has no retries,
20-second HTTP timeouts, a 15-minute run bound, a $0.25 usage-cost guard, and
stops each provider after two consecutive failures. No runtime, service, account,
model defaults or routing configuration changed. Script and public JPEG fixtures
were copied into an ephemeral container `/tmp` bundle.

The 20 cases comprise 13 text cases and seven image cases. Text cases cover
composition/weight/stock/motif constraints, unknown composition and exact SKU,
seller instructions, conflicting title/specification, German requirements,
and an authoritative record among 80 archive distractors at three positions.
This is modest long-context retrieval, not a context-window-limit test.
Image cases cover a lemon match, zebra hard negative, misleading product text,
unknown composition/certification/care, unknown exact SKU, same visible design,
and a 15-image batch. Public fabric images came from the existing Jev/SubQ
fixture collection; labels were hidden from provider image payloads.

The 15-image batch contains three reference slots and four candidates with three
photo slots each. Some slots intentionally repeat the same public photograph.
It tests input capacity and candidate association, not independent view diversity.
All fixture labels and image SHA256 hashes are recorded in private receipts.

`--asset-root` accepts any local directory containing these five prepared JPEGs;
it downloads nothing and has no dependency on the original operator's `/tmp`
paths. Without that option, the harness runs the 13 text cases. These are the
prepared bytes used in the observed run:

| Required filename | Prepared JPEG SHA256 |
| --- | --- |
| `lemon_beige.jpg` | `1514be5456ae745cba5a571fa874927c58f5f93c9ca52fc9c77a68063718e916` |
| `lemon_beige_reference.jpg` | `a225d208e144f5847afcd073fe5e38ed3bc0bf6e8d61cada9331f0d81d40d62f` |
| `blue_zebra.jpg` | `e6c8bf4043c53470d6822ab781ce023cb470f4a328d6e64d787a83f42df1dcef` |
| `green_floral.jpg` | `90449b3dbf94f40cdab4626b5074834c28ad645684cf77765eca512c16278372` |
| `dots.jpg` | `060a1b4baecdc0acd1bae1eda58dbe55a1008e344b89bd31d00dddc2b8ad26b4` |

Public original photos: [lemon candidate](https://cdn02.plentyone.com/5rtbqcd0flq3/item/images/68090083/full/Baumwoll-Popeline-Digital-Zitronen-Gestreift-Beige_2.jpg),
[lemon reference](https://cdn02.plentyone.com/5rtbqcd0flq3/item/images/68090083/full/Baumwoll-Popeline-Digital-Zitronen-Gestreift-Beige_3.jpg),
[blue zebra](https://cdn02.plentyone.com/5rtbqcd0flq3/item/images/68085736/full/Baumwoll-Voile-Enjoy-Kollektion-Zebra-Blau.jpg),
[green flowers](https://cdn02.plentyone.com/5rtbqcd0flq3/item/images/68031775/full/Baumwollstoff-Webware-Digitaldruck-Streublueten-Gruen.jpg),
[dots](https://cdn02.plentyone.com/5rtbqcd0flq3/item/images/68090110/full/Baumwoll-Popeline-Digital-Bunte-Punkte-Weiss_2.jpg).
Prepare each downloaded original with Pillow's
`ImageOps.contain(Image.open(source).convert("RGB"), (384, 384)).save(target, quality=90)`
under its required filename. Verify the resulting hashes before comparing with
this run; remote originals and JPEG encoder versions can change the bytes. The
harness records the hashes actually used, rather than silently claiming an
exact fixture match.

A four-call text/image contract smoke preceded the full run and confirmed both
schemas, the paid Mercury model/provider, and reported Mercury usage costs.
The full run planned 20 cases × three repeats × two providers = 120 calls,
alternating provider order. It made 91 calls: Jev 60 and Mercury 31. Mercury's
second-repeat `german_match` and `long_active_at_0` requests returned HTTP 503;
its remaining requests were skipped without retries. Jev completed its run.
Including smoke, 95 external requests were made.
The receipts classify both failures as HTTP 503 / `HTTPStatusError`. Error
bodies and response headers were not retained, so `Retry-After`, the upstream
versus router origin, and the underlying cause are unknown. No overload or
provider-wide reliability conclusion follows from this single bounded run.

## Results

The fairest semantic comparison uses the 29 case/repeat pairs with valid answers
from both providers. Each contains 32 individual questions because the image
batch has four questions.

| Metric, valid paired subset | Direct Jev 1.14 | Paid OpenRouter Mercury Decide |
| --- | ---: | ---: |
| Entire case correct | 27/29 | 29/29 |
| Individual questions correct | 30/32 | 32/32 |
| Mean case Brier loss, lower better | 0.073529 | 0.000063 |
| Reported input tokens | 35,300 | 19,480 |
| Cost from those usage tokens | $0.00148260 estimated | $0.00038960 reported |

These are overlapping repeated fixtures, not 29 independent random samples.
Jev's paired misses were one fully eligible text product classified as unknown
and the matching candidate rejected in the 15-image batch. Jev rejected that
batch's matching candidate in all three repeats; it correctly rejected the other
three candidates. Mercury correctly answered all four batch questions on its
single completed batch attempt. Both models abstained on the completed unknown
composition and exact-identity cases and rejected the misleading-description
image case.

Jev's incorrect decisions had low native confidence. These are retained for
review without interpreting that confidence as a probability of correctness:

| Case / repeat | Wrong outcome | Native confidence | P(match) | P(reject) | P(unknown) |
| --- | --- | ---: | ---: | ---: | ---: |
| Fully eligible text / 1 | unknown | 0.30 | 0.46 | 0.01 | 0.53 |
| Lemon photograph / 2 | reject | 0.28 | 0.40 | 0.52 | 0.08 |
| Batch matching candidate A / 0 | reject | 0.23 | 0.31 | 0.49 | 0.20 |
| Batch matching candidate A / 1 | reject | 0.27 | 0.25 | 0.51 | 0.24 |
| Batch matching candidate A / 2 | reject | 0.19 | 0.32 | 0.46 | 0.22 |

| Full-run metric | Direct Jev 1.14 | Paid OpenRouter Mercury Decide |
| --- | ---: | ---: |
| Attempted requests | 60 | 31 |
| Valid decision responses | 60/60 | 29/31; two HTTP 503 |
| Entire case correct / attempted | 55/60 | 29/31 |
| Correct questions / valid questions | 64/69 | 32/32 |
| Text latency p50 / p95 | 210 / 237 ms, n=39 | 399 / 706 ms, n=24 |
| Image latency p50 / p95 | 289 / 716 ms, n=21 | 591 / 1,188 ms, n=7 |
| Cases with identical repeated predictions | 18/20 | 9/9 repeated cases; incomplete |
| Successful-call cost | $0.00390159 estimated | $0.00038960 reported |

Latency includes client/network/route time and failures; p95 is the nearest-rank
sample percentile. Sample sizes are small and Mercury's later image repeats are
missing. First fresh-client calls were 219 ms for Jev and 394 ms for Mercury;
subsequent calls reused each HTTP client. Server cache state was unknown, so
these are not server cold/warm-cache measurements.

Jev's cost is its configured $0.042/million input-token tariff multiplied by
reported input usage. Mercury's successful `usage.cost` values exactly matched
$0.02/million reported input tokens, with no output-token charge. Jev did not
provide a verified USD cost field, so its amount is an estimate. Both failed
Mercury responses lacked usage/cost; total Mercury billing is therefore
incomplete. Successful-call costs including smoke were $0.00395892 estimated
for Jev and $0.00040074 reported for Mercury, about $0.00436 combined before any
unreported failure charges. The script never interpreted Jev's raw cost field
as USD.

## Capacity and production implications

Mercury's documented 16-image limit means three reference images plus three
photos per candidate fit four candidates (15 images), not five (18 images).
For 40 candidates at three photos each, this implies ten batches rather than
the current eight five-candidate batches, before concurrency or retries.
The batch experiment demonstrated that Mercury accepted the 15-image request;
it did not run the full 40-candidate product flow or show production throughput.

The benchmark's categorical `match/reject/unknown` contract also differs from
actual Shopping visual ranking. Production requests native ordinal scores 0–4
(clear conflict, weak unsupported similarity, plausible fit, strong fit,
exceptional fit), filters scores below 2, then orders retained candidates by
score. The present results do not validate that score scale, threshold crossings,
ranking/ties, or the production nested candidate/photo binding. In particular,
`unknown` cannot automatically be mapped to ordinal score 1. A later paired
real-catalogue score evaluation would need the actual production instructions,
explicit image/candidate association, and separate false-filter and ranking
checks; that production-style comparison was not run in this bounded benchmark. These categorical
results alone do not justify adoption.

The synthetic/public-only inputs avoided private chat or user-uploaded content.
The paid route's ZDR/provider restrictions were explicitly requested; this does
not establish a privacy conclusion for direct Inception service or the free
OpenRouter route. No routed Jev control was run, so the observed latency gap
cannot be attributed solely to the models.

## Retention and the default-model decision

Keep Jev as the production default for now. Mercury's completed paired answers
were encouraging, but this run had two HTTP failures, slower observed routed
latency, and no production-style ordinal Shopping score validation. The very
small absolute API cost saving does not by itself justify changing the default.

Privacy does not automatically rule out the paid Mercury route. TypeSafe
explicitly prohibits training on customer inputs but publishes no fixed maximum
retention period. OpenRouter lists paid Mercury as a ZDR endpoint and says its
endpoint-specific agreements can be stricter than a provider's ordinary public
policy. Routine inference-content retention may therefore be stronger on that
route, provided its explicit routing restrictions remain enforced.
[TypeSafe policy](https://typesafe.ai/legal/privacy-policy),
[OpenRouter ZDR policy](https://openrouter.ai/docs/guides/features/zdr).

This is not an exception-free end-to-end deletion promise. ZDR permits in-memory
prefix caching, and OpenRouter reserves media retention for abuse, security,
billing and legal purposes. Account-specific prompt logging and product-use
sharing settings were not inspected; the private Inception/OpenRouter agreement
was not available for review. Direct Inception and free Mercury routes must be
assessed separately and must not silently replace this paid route.
[OpenRouter privacy](https://openrouter.ai/privacy),
[data collection settings](https://openrouter.ai/docs/guides/privacy/data-collection),
[terms](https://openrouter.ai/terms).

## Official references

- [Inception native Decisions API](https://docs.inceptionlabs.ai/api-reference/decisions/create-a-decision)
- [Inception decision capabilities and image limits](https://docs.inceptionlabs.ai/capabilities/decisions)
- [OpenRouter multimodal decisions input format](https://openrouter.ai/docs/guides/community/multimodal-decisions)
- [OpenRouter provider routing controls](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter live ZDR endpoint inventory](https://openrouter.ai/api/v1/endpoints/zdr)
- [OpenRouter ZDR guarantees and routing](https://openrouter.ai/docs/guides/features/zdr)
- [OpenRouter data collection controls](https://openrouter.ai/docs/guides/privacy/data-collection)
- [OpenRouter paid Mercury model metadata](https://openrouter.ai/api/v1/models/inception/mercury-decide/endpoints)

Private raw receipts and answers remain under `/tmp/mercury-jev-d8e6-full` and
`/tmp/mercury-jev-d8e6-smoke` on the execution host and container, outside source
control. The full-run summary was regenerated offline to require valid responses
on both sides of each pair and matching question IDs. The original summary is
preserved as `summary.original.json`; original receipt bytes are unchanged, and
the replacement summary records its source receipt hash and zero new inference
requests. The executed snapshot used the prior benchmark's validator; the
published source factors that minimal choice contract into its own helper,
with no request-payload changes. All 91 request hashes were reproduced offline;
the 89 valid responses passed the factored validator/evaluator with zero
correctness or Brier-loss discrepancies. Both failed records were preserved.
An offline invariant check confirms equal paired counts (29 each),
exclusion of a successful response opposite a failed response, and rejection of
different question-ID sets. Reproduce with the public JPEG fixture directory,
Vault credentials, and a fresh output path:

```bash
docker exec api python /app/backend/scripts/benchmark_mercury_decide_jev.py \
  --execute --mercury-route openrouter --repeats 3 \
  --asset-root /tmp/public-fabric-assets \
  --output-dir /tmp/mercury-jev-new-results
```

Compilation and a separate offline HTTPX MockTransport check passed, including
40 paired synthetic responses, pinned provider/model identity, ZDR request flags,
top-level image arrays, batch-question accounting and reported-cost summaries.
