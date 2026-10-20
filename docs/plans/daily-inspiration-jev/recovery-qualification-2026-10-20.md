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
applied to Japanese copy. Current results will be added after execution.

## Recommended final decision benchmark

1. Freeze 100 previously unused, real source snapshots: five topics per each of
   20 supported locales. Produce both video and wiki copy, giving 200 cards. Include
   science, history, arts and everyday explanations, sparse evidence and difficult
   source titles. Run actual three-card batches as well as individual diagnostics.
2. Compare the Mercury/retry/Gemini chain with Gemini Flash Lite alone on identical
   evidence. Keep model, language, attempt, usage, latency and admission attribution.
   Review copy blind, preferably with native-language reviewers; mark factual
   support, natural language, misleading hooks and useful source-grounded follow-ups.
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
