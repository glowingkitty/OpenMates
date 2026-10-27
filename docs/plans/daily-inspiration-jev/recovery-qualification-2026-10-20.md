# Mercury daily inspirations: recovery qualification

The user rejected Mistral Small because its copy was less reliable. The candidate
is Jev 1.14 plus Mercury 3 LOW, one second Mercury attempt on failure, then one
Gemini 3.5 Flash-Lite attempt. Output quality is the first selection criterion;
low price, fast responses or successful HTTP cannot compensate for bad copy.

Each attempt uses the same selected public source evidence. Missing or malformed
copy, invalid source identities, deterministic policy rejection and failed Jev
policy/grounding review can trigger recovery. Discovery is not repeated, rejected
copy is never added to evidence, and Gemini must pass the same admission gates.
There are at most three logical writing attempts, each with a 30-second writer
timeout; the Mercury adapter has no internal SDK retries. An incomplete admitted
set preserves existing delivery recovery rather than publishing a bad draft.

## Responsibilities and current language behavior

A normal generated set targets three video cards, three Wikipedia cards and four
feature tips. The writer produces the hook, sidebar title, opening assistant
explanation and three follow-up questions for each external-source card. Feature
tips use static localized content. Jev handles source eligibility, educational
ranking, categories, and separate final policy and material-grounding decisions.
Video review uses title/channel/description; it does not watch the video.

Personalized generation uses the UI language recorded with the latest qualifying
paid request. Search uses locale-specific Brave settings and the corresponding
Wikipedia edition; copy is generated directly in that language. This is not a
single English batch translated into all languages. Public inventory is pooled
and selected by language across 20 configured locales. Shortages in most locales
can borrow English pool entries; German has provenance filtering and localized
recovery. A destination language label and a count of refreshed locales do not
prove that every displayed card is in that language. Static wiki/feature recovery
and browser fallback are separate from newly generated localized cards.
The backend's static wiki and feature-tip templates currently cover English and
German only; other requested languages receive English templates on that path.
These static cards intentionally have no LLM-generated follow-up suggestions.

## Current qualification

The opt-in `backend/scripts/benchmark_daily_inspiration_recovery.py` exercises
production source selection, writing, assembly and Jev review using frozen public
retrieval fixtures and real providers. Twelve natural cases cover English,
German, Spanish and Japanese. Two separately labeled cases deliberately fail
one or both Mercury attempts to check real-provider second-attempt/fallback
behavior. Forced failures are not provider-availability observations.

Every draft, native Mercury response, native Gemini SDK response, provider usage
record and Jev decision is retained in a persistent receipt directory. Gemini's
returned model version is checked. HTTP errors with missing usage remain
incomplete accounting, not zero-cost claims. English word-count checks are not
applied to Japanese copy.

## Results and decision

Keep Mercury/Mercury/Gemini as the dev candidate; Mistral remains disallowed.
Do not treat this as final multilingual qualification.

| Metric | Observed |
| --- | --- |
| Natural cases | 12, across EN/DE/ES/JA and both source types |
| Admitted on the first Mercury attempt | 11/12 |
| All word-based format heuristics | 10/10 EN/DE/ES cases |
| Japanese | Wiki admitted; video withheld after all three attempts |
| Pipeline median / p95 | 3.187 / 6.701 seconds |
| Mercury native responses | 15 HTTP 200, observed model `mercury-3`; no 429 |
| Forced first-attempt failure | Second Mercury attempt admitted |
| Forced two-Mercury failure | Real Gemini Flash Lite draft admitted |
| Gemini returned model | `gemini-3.5-flash-lite`, verified on both calls |
| Jev labeled controls | 20 unique controls matched twice, 40/40 decisions |
| Known supplier estimate, including interrupted work and controls | $0.012283616; accounting incomplete |

The first process was interrupted by another shared API recreation after ten
completed cases and one saved Japanese draft. Persistent receipts retained all
work. A continuation ran only the remaining Japanese cases and forced-recovery
cases under the registered dev-stack test lease
`daily-inspiration-recovery-d115-continuation`. All production-module hashes match
between the two runs. The benchmark-only `--case` filter was added for this
continuation; it does not change the production chain. The interrupted draft is
excluded from completed-case success and latency, but its reported cost is retained.

Manual review of the eleven admitted natural cards found coherent localized copy
and no material unsupported factual claim. One bridge-video follow-up asks about
strong wind, absent from its source description: a miss against the stricter
source-concept instruction, even though it asserts no factual claim. This is not
a perfect-copy result or an independent native-speaker assessment.

The Japanese video failure is reproducible without another paid call: the existing
`media_coherence._topic_tokens` treats whole unspaced Japanese phrases as words.
The source title and natural paraphrases have no identical whole token, so
`no_shared_topic_tokens` rejects all two Mercury drafts and the Gemini draft before
final Jev review. Both models returned coherent Japanese text. An additional
model retry cannot resolve this deterministic admission failure. Prioritize a
language-aware coherence correction, preserving rejection of unrelated sources,
before a final multilingual rollout decision.

Raw requests/drafts, native responses, source hashes, decisions and combined
analysis are retained in `logs/daily-inspiration-jev/recovery-2026-10-20/{a,b}/`
and its `summary.json` / `japanese-coherence-diagnosis.json`, with persistent host
copies under the product runtime test-results directory. The aggregate includes
natural and forced-recovery costs; it is not a per-card price comparison with the
earlier Mistral experiment. Gemini telemetry marks supplier accounting incomplete,
so the known estimate is not represented as an exact bill. Tiny repeated controls
do not establish universal safety or calibrated probabilities.

The candidate implementation is published to dev as
`6ca5b49de24f5e6a797b17bc1b5447cc7d909634`. All 57 focused checks and scoped lint
passed. [Isolated backend CI](https://github.com/glowingkitty/OpenMates/actions/runs/39462228307)
and both [public-feed browser cases](https://github.com/glowingkitty/OpenMates/actions/runs/39465871355)
passed. The browser check preserves the existing nullable/empty follow-up contract
for static recovery; exact-three copy admission is covered by writer regressions.
Both successful browser recordings were uploaded through the receipt command.

## Recommended final decision benchmark

First correct and regress the Japanese coherence failure, and address the strict
follow-up relevance miss. Static recovery localization beyond EN/DE needs its own
coverage; English recovery must not be counted as localized generation.

1. Freeze 100 previously unused, real source snapshots: five topics per each of
   20 supported locales. Produce both video and wiki copy, giving 200 cards. Include
   science, history, arts and everyday explanations, sparse evidence and difficult
   source titles. Run actual three-card batches as well as individual diagnostics.
2. Compare the Mercury/retry/Gemini chain with Gemini Flash Lite alone on identical
   evidence. Keep model, language, attempt, usage, latency and admission attribution.
   Review copy blind, preferably with native-language reviewers; mark factual
   support, natural language, misleading hooks and useful source-grounded follow-ups.
   This means 200 cards per arm, 400 total if the full paired comparison is run.
3. Propose gates before running: zero admitted policy violations, invented source
   identities or material unsupported claims; at least 95% acceptable first-pass
   drafts and 99% acceptable complete chains. Count English borrowing, static
   recovery and unfilled slots separately, not as localized-generation success.
4. Add a labeled adversarial set in multiple languages: conspiracy promotion and
   debunking, deceptive clickbait and honest curiosity, prompt injection, commercial
   channels, invented dates/numbers and ambiguous metadata. Measure both unsafe
   admissions and needless rejection of legitimate educational content.
5. Exercise the failure matrix independently: real/simulated 429, timeout, malformed
   tools, unsupported copy and Jev outage. Verify the second Mercury attempt and
   Gemini fallback both undergo full review and never exceed the bounded chain.
6. Run a bounded dev load check at expected daily-job concurrency, then observe two
   scheduled cycles. Measure first/second/fallback shares, p50/p95 total latency,
   known versus missing costs, complete ten-card sets, source repetition and actual
   language per displayed card. No production load test is implied.

These are proposed next checks, not claims established by the small qualification
sample or authorization to launch a 200-card paid run in this turn.
