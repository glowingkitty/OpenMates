# Notification type + summary: model benchmark (TASK-390)

Run on the dev API container, revision 99205e3475 (new wording: workspace), 99 synthetic, clearly
labelled replies (en, de, es, fr, pt, ja; done, partial, question, long question, info, code
cases), one run per model, production post-processing prompt and tool, no retries.
Script: `backend/scripts/benchmark_notification_summary_models.py`.

| model | provider | type correct (all 99) | type correct (83 unambiguous) | valid | p50 / p95 s | cost per 1k summaries |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite, old wording | Google | 70.7% | 81.9% | 100% | 1.5 / 1.8 | $2.40 |
| **gemini-3.5-flash-lite, new wording (chosen)** | Google | 85.9% | 95.2% | 100% | 1.5 / 1.8 | $2.39 |
| Mercury 3 (low) | Inception | 92.9% | 100% | 100% | 1.6 / 3.9 | $1.55 ($0.77 promo) |
| Gemini 3.8 Flash | Google | 86.9% | 92.8% | 100% | 10.6 / 19.8 | $13.88 ($6.94 promo) |
| Gemini 4 Hydrogen | Google | 100% | 100% | 100% | 9.4 / 13.3 | $19.83 (list price unverified) |

All models: 100% valid output, 100% within 100 characters and in the chat language, 96-97% with
no number that is absent from the reply (the three misses are the same "3 of 5" cases, a checker
false positive for spelled-out numbers).

"Partial" cases (work done, but something failed or is left) are ambiguous between done and
question; they are counted as done in the all-99 column.

Decision: keep gemini-3.5-flash-lite (already the post-processing model, no new provider, no
privacy-policy change) with the tightened type definitions. Flash and Hydrogen are too slow for the
8 s hand-off window and 5-8x the cost; Mercury is cheaper and 100% on unambiguous types but would
send assistant replies to a provider not yet used for post-processing, which needs the owner's
consent and a privacy-policy mention. The summary is a platform cost: no credits are charged.
Fallback chain: the existing utility-model fallbacks, then the generic notification text.
