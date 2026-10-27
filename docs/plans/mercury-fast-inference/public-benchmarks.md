# Public benchmarks: Mercury 3 and Gemini 3.8 Flash

Research snapshot: 2026-10-20. Primary sources only. This informs a routing
proposal; it changes no product defaults. Public results do not yet establish
that Mercury 3 matches Gemini 3.8 Flash on general medium-complexity work.
Reasoning effort named `medium` is a model setting, distinct from OpenMates'
medium request-complexity tier.

## Exact models and independent comparison

Google published `gemini-3.8-flash` on September 2, 2026, with low, medium and
high thinking; minimal is unsupported. Mercury 3 launched October 19. Do not
substitute Gemini 3.5/3.7, Mercury 2/2.5, or Mercury Decide results.
[Google model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[Inception announcement](https://www.inceptionlabs.ai/blog/introducing-mercury-3).

| Model/configuration | Independent AA Intelligence Index v4.3.2 | Output speed | Evidence |
| --- | ---: | ---: | --- |
| Gemini 3.8 Flash low | 33 | Not available | [AA low](https://artificialanalysis.ai/models/gemini-3-8-flash-low) |
| Gemini 3.8 Flash medium | 40 | Not available | [AA medium](https://artificialanalysis.ai/models/gemini-3-8-flash-medium) |
| Gemini 3.8 Flash high | 41 | 143.9 tokens/s | [AA high](https://artificialanalysis.ai/models/gemini-3-8-flash) |
| Mercury 3 low/medium/high | No verified AA result located | No independently verified comparable AA result located | AA model lookup/search did not yield a Mercury 3 evaluation on this date |

These are the operator's displayed rounded scores on the same current index,
not scores copied from older index versions. Gemini medium gains seven points
over low; high adds one over medium. AA reports medium's cost per index task as
$0.93 versus high's $1.24, and 95M versus 170M output tokens across the index.
This supports evaluating medium as a quality/cost compromise within Gemini;
it does not measure low/medium latency. No matched Mercury-vs-Gemini AA or Arena
result was verified. A missing result is unknown, not a loss or a tie.

## What Inception's launch chart establishes

The vendor's chart compares **medium reasoning for all three models**, not
Gemini. Values below are transcribed from the
[official chart](https://framerusercontent.com/images/YO5OXn25zt3KJBJkUxO2kAwmS6o.png?height=1678&lossless=1&width=1364)
linked in the [October 19 announcement](https://www.inceptionlabs.ai/blog/introducing-mercury-3).

| Vendor-reported metric | Mercury 3 medium | GPT-6 Luna medium | Claude Haiku 5.5 medium |
| --- | ---: | ---: | ---: |
| Output tokens/s | 1,068 | ~130 | ~240 |
| IFBench | 76.84 | 61.82 | 54.65 |
| GPQA Diamond | 89.23 | 86.36 | 84.51 |
| SWE-Bench Atlas | 51.08 | 33.33 | 32.26 |
| DeepSWE v1 | 46.31 | 37.76 | 51.62 |
| MRCR v2 | 75.50 | 62.72 | 78.40 |

The Haiku claim is therefore directional across selected tests, not universal:
Haiku leads the last two rows. The chart is vendor-run, without enough detail
to independently reproduce harnesses, token budgets or uncertainty. The speed
claim concerns generation throughput, not time to first answer or total task
latency. Do not divide it by AA's Gemini speed and call that a controlled speedup.

Google's own model card reports Gemini 3.8 Flash DeepSWE **v1.1** at 73.7% and
GDPVal-AA **v2** at 1545 Elo. Neither is a valid subtraction from Inception's
DeepSWE **v1** or unversioned GDPval chart. Different benchmark versions,
harnesses and unspecified effort settings prevent a clean comparison.
[Google September model card](https://deepmind.google/models/model-cards/gemini-3-8-flash/).

## Individual-suite cross-check

[Vals AI's exact Gemini 3.8 Flash page](https://www.vals.ai/models/google_gemini-3.8-flash)
reports default Google provider, high effort, 65,536 maximum output tokens and
default sampling; it warns individual benchmarks may override these settings.
Its live page does not give a per-result evaluation date in the retrieved text.

| Suite | Mercury 3 evidence | Gemini 3.8 Flash evidence | Comparison limit |
| --- | --- | --- | --- |
| GPQA Diamond | 89.23, Inception medium chart | 94.44% ±1.48, Vals model page, high default | Same suite name, different operator and effort; not a controlled 5.21-point advantage |
| MMLU Pro | No verified result located | 90.22% ±0.29, Vals high default | Missing Mercury coverage |
| IFBench | 76.84, Inception medium chart | No matched result verified | Do not substitute IFEval or equate the suites |
| Function/tool use | No matched BFCL result verified | No matched BFCL result verified | Tool support is not a tool-correctness benchmark |
| Agentic coding | SWE-Bench Atlas 51.08, vendor medium | SWE-bench 80.00% ±1.79, Vals high default | Different suites; Atlas is not interchangeable with SWE-bench |

The available GPQA row is useful context, but none of these rows supplies a
matched independent Mercury-vs-Gemini low/medium comparison. The published
Mercury speed row is **medium**, not instant/non-reasoning, and does not establish
our application's speed at a different reasoning profile.

## Independent Mercury evidence: narrow but useful

Benchmark operator Spring Prompt ran Mercury 3 through OpenRouter, hosted by
Inception, on October 19–20. Its one-minute BulletBench result is **491 Elo with
reasoning off**, versus **1068 for Gemini 3.8 Flash low**. Mercury's median
thinking-off move time was 0.42 seconds; default/low reasoning could exhaust
clocks, including a reported 105-second move. Its review also reports weak
survey/deck outcomes at API default. These are task-specific original
measurements, not an AA general-intelligence score. The chess operator describes
8–12 games per configuration; settings differ and uncertainty is material.
[Operator review](https://springprompt.com/blog/mercury-3-review),
[BulletBench methodology/results](https://springprompt.com/benchmarks/bulletbench).

## Implications for low/medium default routing

- **Low-complexity work:** Mercury merits bounded tests on short transformations,
  transcript correction and constrained tools. High generation throughput alone
  does not establish reliability; measure preservation of meaning, schema/tool
  correctness and p95 latency, including its reasoning setting.
- **Medium-complexity work:** retain Gemini pending representative evidence.
  Public data has no matched Mercury/Gemini general-quality result; the vendor
  chart cannot establish parity. If choosing Gemini effort, AA's medium result
  is materially stronger than low while close to high on this aggregate.
- **Upgrade decision:** synthetic gateway tests can inform Mercury task fit;
  paid direct-API capacity, latency and reliability require direct measurements.
  Public benchmarks and gateway results cannot resolve the observed direct
  shared-capacity 429s. Production routing remains direct Inception only.

No public source found here directly evaluates OpenMates workflow authoring,
multilingual raw-transcript correction or the full tool loop. Aggregate scores,
chess and vendor comparisons are supporting evidence, not acceptance tests.
