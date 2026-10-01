# Workflow author model comparison — 2026-10-01

## Decision

Keep Gemini 3.8 Flash for workflow construction, following the user decision. No production model setting changed. GPT-OSS 120B was faster on Cerebras but did not match Gemini reliability in this bounded sample. Further model tests stopped.

## Method

Eight synthetic natural-language requests, including raw spoken self-correction, exact and AI checks, free-text Ask AI prompts, two creates and a mixed create/update. Jev decisions were measured once per case and reused identically across authors. Every candidate ran through the deployed parser, registry compiler, deterministic prefix validation and one-correction-per-failing-node loop. An independent semantic oracle and manual review checked schedules, references, predicates and preservation of existing workflow state.

Paid inference ran directly in an isolated Python process inside the dev API container. No real workflows, schedules, wallet entries or account data were written. These times measure author construction and validation, including corrections; they exclude Jev preselection, HTTP/authentication, persistence and browser rendering. Common measured Jev preselection had a median of 0.392 seconds. Full-response outputs appear only after the provider response completes.

## Paired native-instruction results

| Author | Complete valid graphs matching intent | Median author time | Range |
| --- | ---: | ---: | ---: |
| Gemini 3.8 Flash, streaming | 8/8 | 3.952 s | 2.627–7.627 s |
| GPT-OSS 120B, Cerebras, full response | 4/8 | 1.310 s | 0.781–2.264 s |
| GPT-OSS 120B, Groq, full response | 4/8 | 2.987 s | 1.869–5.637 s |

These are eight cases with one measured sample per author, not a statistical reliability estimate. Times include failed attempts and corrections. All partial outputs count as failures to fulfill the complete request even though their accepted prefix is valid.

### Gemini requests and outputs

| Exact request | Validated workflow summary | Author time |
| --- | --- | ---: |
| Every Friday at 09:00 Berlin time, search shopping for refurbished noise-cancelling headphones under 150 EUR and send matching products and prices to chat. | One Friday 09:00 Berlin shopping search constrained to refurbished noise-cancelling headphones and EUR 150; results reach chat; no Check. | 4.814 s |
| Um every day at 07:00 in Berlin—no, sorry, at 08:30 Lisbon time—check tomorrow's weather in Lisbon. If rain is expected, tell me in chat to take an umbrella; otherwise tell me it should be dry. | Daily 08:30 Lisbon; tomorrow's Lisbon forecast; exact rain Check with distinct umbrella and dry chat branches; no Berlin or 07:00. | 2.627 s |
| Every weekday at 07:30 Berlin time, get today's weather for Berlin, Paris and London. Ask AI to combine all three forecasts into one chat update and say when any city has no forecast. | Three today weather actions feed all forecast results into one Ask AI prompt; its answer reaches chat and covers missing forecasts. | 7.627 s |
| Every Friday at 16:00 Berlin time, find upcoming AI events in Berlin. Ask AI in free text to summarize those event results for a founder, then send its answer to chat. | Friday 16:00 Berlin; events.search results appear as a reference in Ask AI prompt; Ask AI answer reaches chat. | 6.711 s |
| Every Sunday at 17:00 Berlin time, search nutrition recipes for high-protein vegetarian dinners. Ask AI in free text to choose three recipes from those search results and explain why, then send its answer to chat. | Sunday 17:00 Berlin; recipe results appear as a reference in Ask AI prompt; answer reaches chat. | 2.921 s |
| Every day at 18:00 Berlin time, search news about AI policy. Use an AI check to decide whether anything matters to a small European startup. If yes, send the relevant news to chat; if no, say there is no important update. | Daily 18:00 Berlin; news results feed an AI Check with distinct yes and no chat messages; no extra Ask AI action. | 4.840 s |
| Create two separate workflows: every day at 07:00 Lisbon time remind me in chat to stretch, and every weekday at 18:00 Berlin time search AI news and send the results to chat. | Two creates: daily 07:00 Europe/Lisbon stretch reminder; weekday 18:00 Europe/Berlin AI news search delivered to chat. | 3.089 s |
| Move my existing Paris morning forecast to 10:00, keeping its Paris weather search and chat message intact. Also create a separate workflow every Friday at 09:00 Berlin time to search refurbished noise-cancelling headphones under 150 EUR and send matches to chat. | One update of the owned Paris workflow to 10:00 with its timezone and unrelated nodes intact, plus one new Friday 09:00 Berlin headphone workflow. | 2.881 s |

Gemini needed one node correction for the AI news check case; the other seven completed in one author request. All eight outputs passed independent intent review.

## Failures and bounded follow-up

The main GPT-OSS failure was confusing Ask AI with an app skill or an AI Check: adding `capability: ai.ask` to builtin Ask AI, using question/selected-input fields instead of a prompt, malformed prompt JSON, or referencing a location label instead of actual forecast results. Other failures included an incorrect weekday schedule, altered owned workflow IDs, and provider strict-schema generation failures. Invalid records were rejected; partial state was retained in memory only.

A guided transport test added closed schemas per node kind and concrete Ask AI / AI Check examples, then tested four difficult cases (three cities, events, nutrition and mixed create/update). Cerebras passed 3/4; Groq passed 2/4. Remaining failures included incomplete events output and Groq strict-schema generation errors. These follow-up numbers use different instructions and a smaller subset; they must not be combined with the eight-case results or described as an overall success rate. No additional tests followed the decision to stay with Gemini.

### Compatibility defects excluded from model-quality judgments

The first Groq run was rejected before inference because the nullable schema nested `anyOf` variants. Flattening that transport schema allowed actual model evaluation. Those rejected setup calls were excluded from the paired results.

A valid explicit `branch: default` on a root node was rejected when the accepted flat record was replayed from its compact equivalent, which omits that redundant field. The planner fix compares these representations semantically during trusted compact replay only. Actual model retries still cannot change accepted flat records. The focused planner suite passes 32 checks. This fix also prevents Gemini from suffering the same false rejection.

The oracle accepts equivalent Unicode dashes in search text and case-insensitive country codes, consistent with shopping provider normalization. Actual content omissions remain failures.

## Pricing

Published uncached USD per million tokens, checked on 2026-10-01:

| Author | Input | Output, including reasoning |
| --- | ---: | ---: |
| Gemini 3.8 Flash | $0.75 | $3.75 |
| Cerebras GPT-OSS 120B | $0.35 | $0.75 |
| Groq GPT-OSS 120B | $0.15 | $0.60 |

Gemini median observed author cost was about $0.00510 per request, before common Jev cost (about $0.00060). Seven requests completed with final usage. The corrected news case ended its first stream early, so its recorded cost may understate final provider billing. GPT-OSS full-response usage includes completion/reasoning tokens and corrections; Groq schema-generation errors did not return token usage, so totals containing those attempts are incomplete. These are provider-cost estimates, not user-credit or billing-settings verification.

Sources: [Groq models and prices](https://console.groq.com/docs/models), [Cerebras live public model/pricing API](https://api.cerebras.ai/public/v1/models), [Google Gemini 3.8 introduction/pricing](https://ai.google.dev/gemini-api/docs/latest-model?hl=en). Google rates are introductory through 2026-12-31. Advertised tokens per second do not measure request or validation latency.

## Reproduction

Use `backend/scripts/benchmark_workflow_authoring_models.py` with the corpus in `workflow_authoring_model_cases.py`. The script requires explicit `--allow-paid-dev-inference`, rejects CI, loads Vault credentials in memory, writes reports with mode 0600, and never persists or executes workflows. `--selection-report` reuses prior measured Jev choices; `--profile guided` evaluates the stricter OSS-only transport. The bridge changes provider envelopes, not the compiler or retry rules.

Private synthetic reports for this run are in the dev API container: `/tmp/workflow-model-full3e12.json` (Gemini baseline plus superseded compatibility run), `/tmp/workflow-model-oss-fixed3e12.json` (paired native GPT-OSS run), and `/tmp/workflow-model-oss-guided3e12.json` (bounded guidance experiment). Source baseline was `7c7e9e1b209604c37fd2c4b8a0bef0faea1f2813`, with the root-default replay fix injected into the benchmark process only.
