# Mercury 3 reasoning comparison and Jev routing recommendation

Measured on 2026-10-22 for TASK-2719, using direct Inception requests from the
development API runtime at `5a2b038f62f59588304af76f609f91fded1dbe29`.
This evaluation changes no product routing, saved model preferences, or accounts.

## Result

MEDIUM is the strongest candidate for Mercury's ordinary main-answer setting in
this small experiment. HIGH is too variable to promote automatically for every
medium-complexity request based on these measurements. Choose reasoning effort
separately from the model tier, with supported per-route controls and bounded
time/token budgets.

The main comparison used one identical synthetic incident-analysis and billing
request, temperature 0.5, three rotated repeats per level, and the same 32,768-token
completion allowance for all levels. The allowance includes reasoning and visible
answer tokens. All nine responses identified themselves as `mercury-3`.

| Effort | Median total time | Total-time range | Median reasoning tokens | Complete answers | Mean supplier cost per 1,000 attempts |
| --- | ---: | ---: | ---: | ---: | ---: |
| LOW | 2.370 s | 2.154–2.374 s | 1,001 | 3/3 | $0.469 |
| MEDIUM | 4.206 s | 3.952–4.975 s | 1,929 | 3/3 | $0.782 |
| HIGH | 23.907 s | 4.351–50.868 s | 13,595 | 2/3 | $5.664 |

Failed requests remain in time, token, and cost statistics. The unsuccessful HIGH
request generated 32,040 reported reasoning tokens and no answer before native
`finish_reason: length`; its estimated supplier cost was $0.0112338. The other
HIGH requests completed in 4.351 and 23.907 seconds. No HTTP failures, timeouts,
rate limits, gateway substitutions, or automatic provider retries occurred.

Median first visible-answer time was 2.076 s for LOW and 3.923 s for MEDIUM.
For HIGH, the two visible answers started at 4.115 and 23.898 seconds; the third
request never produced visible content. Excluding that request would misstate
the operational cost and reliability of HIGH.

MEDIUM cost approximately 1.67 times LOW; HIGH cost approximately 12.08 times
LOW and 7.24 times MEDIUM across these attempts. This is generated-token demand,
not a higher per-token tariff for the reasoning setting.

## Cost accounting and evidence

The [official pricing](https://docs.inceptionlabs.ai/get-started/models), checked
2026-10-22, lists promotional rates of $0.10/M ordinary input, $0.01/M cached
input, and $0.35/M output. Regular rates are twice these amounts. No promotional
end date was established. Rates do not establish whether the account actually
paid cash or consumed an allowance.

Costs above are usage-based estimates, not supplier invoices or OpenMates wallet
charges. The [official usage contract](https://docs.inceptionlabs.ai/resources/faq)
includes cached input in `prompt_tokens` and reasoning in `completion_tokens`.
The calculation subtracts cached input before applying its discounted rate and
never adds reasoning to completion totals again.

Native cache reuse differed across calls. With all input normalized to the
ordinary-input rate, mean cost per 1,000 attempts would be $0.507 LOW, $0.800
MEDIUM, and $5.681 HIGH. The conclusion does not depend on the small observed
cache savings. All 18 requests across both experiments were valued at $0.03184679
in total using the promotional rates and reported cache counts.

The first experiment used a common 8,192-token allowance. LOW and MEDIUM completed
3/3 requests each; HIGH completed only 1/3. Those results were retained rather
than silently replaced. The second experiment raised the common allowance for
all three levels, preserving the exact same prompt and temperature. It still
did not produce a complete HIGH answer on every attempt.

The finite oracle checks JSON shape, factual conclusions, arithmetic, uncertainty,
safe recovery constraints, and an 80-word recommendation. In the main experiment,
MEDIUM passed 3/3, HIGH passed 2/3 with one budget failure, and LOW passed 2/3
with one recommendation exceeding 80 words. All three complete LOW responses
preserved the checked facts and arithmetic. These are narrow checks on one
synthetic request, not evidence of general model quality or Gemini parity.

Original raw answers and original per-attempt assessments remain intact. Reviewed
assessment accepts case differences in effort enum values because the prompt
did not prescribe their JSON casing. No numerical, factual, or word-limit
requirement was relaxed. Reviewed summaries include failed attempts, correcting
the initial harness summary's completed-only aggregation.

- Reusable script: [benchmark_mercury_reasoning.py](../../backend/scripts/benchmark_mercury_reasoning.py).
- Local raw and reviewed evidence: `logs/benchmarks/mercury-reasoning-2026-10-22/`.
- Prompt identity is recorded in both reports and checked equal across budgets.
- Reports are synthetic-only, mode 0600, and excluded from source commits.

## Recommended internal preprocessor design

Keep two independent outputs in the existing Jev preprocessing flow:

```json
{"complexity": "medium", "reasoning_level": "high"}
```

Complexity selects the allowed model chain. Reasoning recommends the deliberation
level for an attempt. It must not change an exact model choice, introduce premium
fallback models, or become a signal that an explicitly selected model is automatic.

The internal recommendation can be LOW, MEDIUM, HIGH, or EXTRA_HIGH. Resolve it
against verified capabilities of the selected model and actual serving route
immediately before every attempt. Unsupported EXTRA_HIGH clamps to the route's
highest supported level. Do not infer support from an adapter-wide enum or from
the catalog's `reasoning: true` flag alone. Nonconfigurable routes keep their
documented native behavior; fixed-effort model variants retain their selected
configuration. Missing or invalid recommendations retain the approved profile
without invalidating otherwise usable Jev routing.

Both [Gemini 3.8 Flash and Gemini 4 Argon](https://ai.google.dev/gemini-api/docs/thinking)
currently document LOW/MEDIUM/HIGH, with HIGH as the ceiling. Neither advertises
MAX or EXTRA_HIGH. Mercury's native ceiling is also HIGH; its separate INSTANT
setting need not become an additional general reasoning level.

Ask Jev for effort in its existing decision flow with applicable model/route
context; avoid another mandatory classifier round trip solely for this field.
Carry the recommendation separately from current routing-provenance fields and
resolve it again when a fallback model changes. Preserve safety, modality,
disabled-model/server, credit-reservation, and explicit-selection restrictions.

Use MEDIUM as the normal Mercury answer setting; reserve LOW for an explicitly
chosen fast/very-simple policy and HIGH for work that needs it. These data do not
justify switching all medium-complexity primary requests from Gemini to Mercury
HIGH. A matched broader quality evaluation would be needed for that switch.
Changing effort must also revise the current five-second Mercury first-substantive
deadline and consider reasoning/output budget fit; merely replacing the LOW
constant would cause healthy higher-effort requests to fall back prematurely.

The implementation must remove the transport-level LOW override as well as the
routing helper override. Preserve auxiliary Mercury settings for transcription,
workflows, postprocessing, and Jev generative recovery unless separately approved.
The product change needs a new version of `feature.ai-model-routing`: version 8
explicitly promises Mercury LOW and fixed automatic tier profiles.
