# Daily Inspiration setup decision, 2026-10-20

Deploy **Jev 1.14 + Mistral Small 4** to dev. Mercury 3 low produced more
consistent copy in the completed paired comparison, but the subsequent fresh-topic
run received HTTP 429 from direct Inception. Its remaining holdouts were stopped,
not scored as quality failures. Keep Mercury available only as the scoped writer
configuration until direct capacity and a fresh holdout are verified. Ordinary
assistant routing and account defaults are unchanged.

## Completed paired comparison

The harness `backend/scripts/benchmark_daily_inspiration_models.py` runs production
source selection, prompts, assembly and final Jev review. Search/YouTube/Wikipedia
retrieval is frozen to public synthetic metadata, while Jev and the writers use
real direct APIs without provider fallback or retries. Six English/German sources
cover bioluminescence, the water cycle and the Antikythera mechanism. Each runs as
a video and a wiki card, twice per writer, with alternating provider order.
These are repeated fixtures, not 24 independent topics or a live-feed evaluation.

| Completed paired metric | Jev + Mistral Small | Jev + Mercury 3 low |
| --- | ---: | ---: |
| Writer responses | 24/24 | 24/24 |
| Cards admitted by production review | 21/24 | 24/24 |
| All finite copy-format checks passed | 14/24 | 23/24 |
| Pipeline p50 / p95 | 2.141 / 2.570 s | 2.646 / 3.482 s |
| Writer p50 | 1.558 s | 2.087 s |
| Estimated supplier cost, including per-card Jev | $0.00757281 | $0.011557142 |
| Cost per admitted card | $0.00036061 | $0.00048155 |
| Input/output usage complete | yes | yes |

Finite checks cover phrase/title length, sentence counts, three follow-ups and
obvious language bleed. They do not establish factual correctness. Manual review
of all 48 outputs favored Mercury's restrained source paraphrases. Mistral more
often added poetic framing, extra sentences and unrelated follow-up subjects.
The rejected German history cards included unsupported historical dates and
misleading Bronze Age framing. Mercury still had a short-title miss and occasional
awkward wording; it is not a perfect-copy guarantee.

The final Jev policy controls matched all 24 labeled decisions, and factual
grounding controls matched all 16 labeled decisions. The controls include
conspiracy promotion versus debunking, misleading clickbait versus curiosity,
miracle cures, commercial promotion, untrusted instructions, invented numbers,
wrong causal explanations and unsupported historical superlatives. These small,
hand-authored samples cannot establish probability calibration or universal safety.

## Fresh topics and availability

Four untuned source topics cover photosynthesis, tides, sound and suspension
bridges, in English and German. The paired holdout stopped on Mercury's first
request with HTTP 429. No fallback was used, and failed-response usage was absent,
so its billing is incomplete. This is an observed rejection of this account/route,
not evidence of a provider-wide outage or an established quota-reset schedule.

A separate Mistral-only holdout completed eight writer requests: eight cards were
admitted, and four met every finite copy-format check. Pipeline p50/p95 were
2.118/2.719 seconds and estimated cost was $0.002801502. This follow-up is unpaired;
it does not prove Mistral's quality exceeds Mercury's. It supports Mistral as the
currently usable deployment choice, with the shared editorial gate and recovery.

## Important implementation decisions

- Jev handles eligibility, relevance ranking, categories and final policy review.
  Writers receive the exact selected public evidence and cannot select new IDs.
- Wikipedia titles and summaries are retrieved before selection and writing.
- Final review has separate policy and material-grounding questions. An earlier
  combined-policy experiment admitted unsupported specific claims. Literal
  entailment of every word then rejected ordinary explanations, so the final
  rubric permits explanatory paraphrases while targeting material unsupported
  claims. These refinements used the initial fixture outputs; the fresh topics
  were not used to tune prompts.
- Unknown, incomplete, low-confidence and failed reviews withhold new external
  cards. Partial personalized sets do not replace usable content. Existing static
  recovery remains available.
- Public video descriptions are retained in the pool for later editorial review.
  Existing rows without sufficient evidence may be withheld without deletion.

## Accounting, reproduction and evidence

Model identities are checked against direct `jev-1.14.0`, Mistral Small 4 and
`mercury-3`. Supplier estimates use $0.042/M Jev input; $0.15/$0.60 Mistral
input/output; and Mercury's current launch $0.10/$0.35 rates. Reported cached
tokens use the respective reduced rates, and reasoning tokens remain included in
completion totals. These are usage-based estimates, not verified invoices.
The paired subtotal excludes the shared policy/grounding-control calls and any
prior development probes. Mercury's launch discount has no established end date.

Run inside the dev API container with Vault credentials, using a unique output
directory; the default is dry-run:

```sh
python backend/scripts/benchmark_daily_inspiration_models.py --execute --repeats 2 --output-dir /tmp/daily-feed-comparison-new
python backend/scripts/benchmark_daily_inspiration_models.py --execute --holdout --repeats 1 --output-dir /tmp/daily-feed-holdout-new
```

The harness stops at the first HTTP 429 and has a $1/15-minute bound. It records
raw public requests/outputs, model identity, usage, latency and source hashes.
The original paired/first-holdout raw receipts were removed when another scoped
runtime operation recreated the shared API container. Their console summaries and
the manual review of all 48 paired outputs are retained in this chat; the measured
paired table above is an observation, not a newly reproducible raw-response audit.
`logs/daily-inspiration-jev/observed-paired-summary.json` explicitly records that
provenance and limitation. No missing raw receipt is represented as retained.

Follow-up output now uses persistent storage and is copied into the session's
ignored `logs/daily-inspiration-jev/` directory. The final deployed-policy holdout
retains its full `receipt.json` and `summary.json`: Mistral admitted 8/8 cards,
with 2/8 passing all format checks, pipeline p50/p95 2.137/3.881 seconds, and
estimated cost $0.00378177. Its policy and grounding controls matched 12/12 and
8/8 labels. This is a separate unpaired validation, not a replacement paired run.

The actual application adapter also completed real Brave/YouTube/Wikipedia
discovery, producing three reviewed videos in 9.63 seconds, three reviewed wiki
cards in 10.62 seconds and four static tips. That source-matched receipt is
`logs/daily-inspiration-jev/d115-inspiration-real-facade.json`; it writes no user
records or shared pool entries. A separate retained channel-policy check rejects
a company-owned channel and permits a university lecture. The deployment rubric
also explicitly preserves the prior exclusion of company/brand-owned channels.

Focused unit checks, isolated browser CI and deployment receipts are recorded with
TASK-1531 and the session evidence. Rates were checked against [Mistral pricing](https://docs.mistral.ai/inference/pricing),
[TypeSafe models](https://docs.typesafe.ai/models) and [Inception models](https://docs.inceptionlabs.ai/get-started/models).

The implementation is published to dev in `a0def9059fa52494fca903a5732c35bf19e17902`.
All 39 focused unit checks and scoped lint passed. [Isolated browser CI](https://github.com/glowingkitty/OpenMates/actions/runs/39427339752)
passed both public-feed language/navigation and withheld-inventory fallback cases,
with no skips or flakes and complete isolated cleanup. Both selected recordings
were uploaded through the receipt's evidence command; their signed links are
delivered in the final chat. Runtime activation is recorded in the final Plan evidence.

The coordinated schema and backend refresh completed successfully. The active
writer and policy were verified as `mistral/mistral-small-latest` and
`daily-editorial-v4`, and Directus exposes the new source-description field.
The reviewed public selector then successfully wrote 190 defaults for 19
languages. A final regression also ensures that an unknown video channel stays
unknown instead of being labeled Wikipedia during legacy pool review.
The complete decision regression file also passed in [isolated pytest CI](https://github.com/glowingkitty/OpenMates/actions/runs/39431748500).
