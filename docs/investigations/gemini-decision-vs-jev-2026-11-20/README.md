# Gemini Decision 1 vs Jev, re-benchmark 2026-11-20 (TASK-4784)

Question: was Gemini Decision 1's slowness in the first benchmark (TASK-1809) a launch problem, and should any
decision purpose be on Gemini instead of Jev?

**Answer: the launch-week slowness is gone, but Gemini is still slower and less reliable than Jev for every purpose.
Every purpose stays on (or moves back to) Jev.**

## Which model was measured

- Gemini: request body `"model": "gemini-decision-1"` sent to `POST https://generativelanguage.googleapis.com/v1beta/decisions`
  (`backend/shared/providers/google/decisions.py`, `GEMINI_DECISION_PROVIDER_MODEL`). That string has been the same since the
  client was introduced (single commit `cc436131d6`, 2026-11-17), and the same client and harness
  (`backend/scripts/benchmark_gemini_decision_jev.py`) produced the first benchmark, so the first run also asked for
  Gemini Decision 1. The Decisions API returns typed probabilities and `total_output_tokens: 0`, which a Flash chat model
  does not; the response itself does not echo a model name, so the proof is the requested id plus the endpoint.
  The 1.5 s / 6 s voice figures quoted from the earlier chat could not be re-checked here (no raw results of that run are stored).
- Jev: `typesafe/jev-1.14` via the production `JevDecisionClient` (no retries, 15 s timeout for both models).
- Both models receive the same state and questions, built by the production question builders (`decision_bench/` suites),
  with synthetic data only. 270 cases x 3 repeats x 2 models. Image-safety suites were not run (their image sets are private).

## Method and caveats

1. `run1_burst` (concurrency 3 per model): Gemini answered 166 of 810 calls and returned `429 rate_limited` for the rest.
   Not a fair latency or accuracy run; kept as evidence of the limit.
2. `run2_seq` (concurrency 1 per model): 107 Gemini calls (voice and app/focus routing suites) were `429`.
   Those prompts follow the routing suites, whose calls average 5,600-9,200 input tokens, so the burst used up the documented
   1M tokens per minute. A paced probe (`ratelimit_probe.py`, 2 to about 4 calls/s of a tiny prompt, 209 calls) had no 429.
3. `gj-voice` and `gj-focus`: those two suites rerun alone with a 75 s pause. They replace the rate-limited suites in the table.
   The table below is `run2_seq` + `gj-voice` + `gj-focus` (`python3 analyze.py run2_seq.rows.jsonl.gz gj-voice.rows.jsonl.gz gj-focus.rows.jsonl.gz`).
4. Latency is end-to-end from the dev server, valid answers only. Accuracy is per question on valid answers.
   Sample sizes are small (shopping 12 distinct cases, photo 8, search 19), so accuracy differences of a few points are not significant.

## Results per purpose

| purpose (default model today) | model | valid / calls | blocked | p50 ms | p95 ms | accuracy |
|---|---|---|---|---|---|---|
| routing: preprocess (Jev) | Jev | 150/150 | 0 | 193 | 220 | 98.3% |
| | Gemini | 147/150 | 3 | 373 | 547 | 99.0% |
| routing: app/focus (Jev) | Jev | 102/102 | 0 | 197 | 229 | 96.3% |
| | Gemini | 102/102 | 0 | 357 | 504 | 96.3% |
| voice end-of-turn (Jev) | Jev | 126/126 | 0 | 157 | 180 | 100% |
| | Gemini | 126/126 | 0 | 217 | 320 | 100% |
| web browsing (Jev) | Jev | 75/75 | 0 | 174 | 216 | 93.8% |
| | Gemini | 75/75 | 0 | 265 | 613 | 87.5% |
| safety: prompt injection (Jev) | Jev | 120/120 | 0 | 159 | 187 | 84.2% |
| | Gemini | 120/120 | 0 | 215 | 323 | 100% |
| postprocessing (Jev) | Jev | 120/120 | 0 | 161 | 193 | 73.2% |
| | Gemini | 120/120 | 0 | 221 | 486 | 89.0% |
| search relevance (Gemini first, 2.5 s cap) | Jev | 57/57 | 0 | 160 | 192 | 96.5% |
| | Gemini | 57/57 | 0 | 213 | 331 | 100% |
| shopping relevance (Gemini first) | Jev | 36/36 | 0 | 171 | 244 | 100% |
| | Gemini | 36/36 | 0 | 386 | 1150 | 100% |
| photo relevance (Gemini first) | Jev | 24/24 | 0 | 170 | 185 | 87.5% |
| | Gemini | 24/24 | 0 | 278 | 604 | 100% |

Gemini is 1.3-2.3x slower at the median and 1.7-4.7x slower at p95 for every purpose. The earlier 1.5 s median / 6 s p95
for the voice check is not reproduced (voice: 217 ms / 320 ms against Jev's 157 ms / 180 ms), so the worst of the first
result was a launch problem, but the remaining gap is not "comparable".

Reliability and safety findings (run2_seq harness summary):
- Gemini blocked 3 routing prompts with `prohibited_content` (Jev answered those); under bursts it returns `429`.
- Web browsing: Gemini missed 36% of the injection-style cases against Jev's 18%.
- Postprocessing harm score: Gemini gave 3 critical false negatives across the repeats (Jev none), although its overall accuracy is higher.
- Accuracy advantage for Gemini only on prompt injection (Jev flags 32% of the benign cases), relevance and postprocessing.

## Recommendation per purpose

| purpose | recommendation | change |
|---|---|---|
| routing (preprocess, app/focus) | Jev | none (already Jev) |
| voice end-of-turn | Jev | none; the voice chat builds on Jev |
| web browsing | Jev | none |
| safety (prompt injection, image safety) | Jev | none; Gemini's accuracy edge on prompt injection is worth a separate look as a second opinion, not as the primary decider |
| postprocessing | Jev | none |
| search relevance | Jev first | moved from Gemini-first to Jev |
| shopping relevance | Jev first | moved from Gemini-first to Jev |
| photo relevance | Jev first | moved from Gemini-first to Jev |

The routing mechanism (`decision_routing` in `backend/apps/ai/app.yml`) is unchanged, so a purpose can be moved to
Gemini later by one config line after a new benchmark.
