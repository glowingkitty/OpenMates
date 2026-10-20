# Expanded readiness evaluation — 20 October 2026

The user requested stronger quality evidence before new automatic defaults and
clarified that the audio task is transcript **correction**, not summarization.
Keep Gemini 3.5 Flash-Lite postprocessing. Do not enable the proposed low-chat or
workflow defaults on the strength of the initial twelve and sixteen outputs.

## Fixed comparison before inference

- Correction: 24 new synthetic cases, twelve German and twelve English, each
  repeated twice against native Mercury 3 LOW and native Gemini 3.8 Flash LOW:
  96 paired results. Use the existing production correction instructions and
  forced tool contract. Include longer speech, multiple speakers, uncertainty,
  self-corrections, numbers, names, negation and quoted untrusted instructions.
- Workflows: the eight existing cases plus sixteen new independent cases, each
  repeated twice against native Mercury 3 INSTANT and Gemini 3.8 Flash LOW:
  96 results. Include German requests, updates, preserved graph state, typed
  references, branches, multiple targets and corrected or negated constraints.
  Use production prompts, compilation, deterministic validation and correction
  allowance. Pair each case with the same measured Jev preselection.
- Define requests, expected outcomes and finite checks before the first call.
  Rotate arm order, save complete private outputs and actual provider identities,
  distinguish unavailable attempts, and stop the whole run at its first 429.
  Synthetic inputs only; no chat, task, workflow, schedule or wallet mutations.

## Assessment

Manually inspect every correction and compiled workflow, preserving the strict
oracle verdict separately. A fluent answer or valid graph does not prove intent
preservation. Record false-positive oracle flags explicitly rather than silently
overriding them or changing the case bank after observing responses.

Critical correction defects include changed numbers, names, dates, negations,
decisions or speakers; invented content; lost material content; and following an
instruction quoted inside speech. Critical workflow defects include the wrong
target, schedule, conditions, references or actions, lost unrelated graph state,
unrequested execution/control, and failure to return a complete valid result.
Separate cosmetic language defects from changes of meaning.

Report paired failures and German/English results, not only an aggregate score.
Show correction completions beyond the five-second primary deadline separately;
a correct response arriving too late would require fallback in the proposed
product path. Workflow timings include validation retries; report first accepted
header/node and complete latency. Account for cache reuse and missing usage.

A default switch requires no unexplained critical Mercury regression on this
bank and acceptable latency under the proposed deadlines. A baseline failure
does not excuse a Mercury defect. Repeated or serious semantic failures keep the
relevant default unchanged; consider narrower eligibility only after a separate
supported decision. This sample cannot establish a population error rate or
guarantee that future requests are regression-free.

## Execution state

The primary comparison completed 96 correction results and 96 workflow results.
Product rollout changes remain an unpublished candidate. The two presented
Specification fingerprints have not received explicit approval; this evaluation
does not record or imply approval.

## Diagnostic workflow reasoning arm

The primary workflow run returned complete valid graphs for Mercury INSTANT in
42/48 results and Gemini LOW in 46/48. Before making a model-level recommendation,
run Mercury LOW over the entire unchanged 24-case bank twice: 48 additional
results. This is a diagnostic follow-up chosen after the initial results, not an
arm of the original predeclared comparison.

Reuse the original measured Jev selections, production prompts, validators and
correction allowance. Verify the frozen selection report identity. Do not modify
cases or scoring, rerun successful baseline arms, or merge the new outputs into
the original INSTANT score. Preserve separate raw receipts and source identity.
Review all 48 outputs under the same rubric. Later execution and cache state
limit latency comparisons with the earlier arms; a favorable result would still
need a supported rollout decision and does not approve any default change.
