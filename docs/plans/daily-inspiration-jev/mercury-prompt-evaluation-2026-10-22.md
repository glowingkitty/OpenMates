# Mercury writer prompt evaluation — 2026-10-22

## Question and prior evidence

The user asked us to give Mercury 3 clearer instructions and source input, then
evaluate whether it can replace Gemini 3.8 Flash as the sole Daily Inspirations
writer. Jev 1.14 remains the decision model, including actual thumbnail review.

The previous three-source comparison did not demonstrate Mercury incapability.
Every Mercury response had valid structure; independent automated source review
found apparent false holds in all five rejected drafts across both writers.
Published general-purpose benchmarks also support trying Mercury, but do not
replace a workload-specific check. See [Inception's Mercury 3 announcement](https://www.inceptionlabs.ai/blog/introducing-mercury-3).

## Implementation

The existing video schema still assigned selection to the writer, requested a
rich three-to-five-sentence introduction and surprising details, and supplied
unrelated examples. Those conflicted with the exact-three-sentence,
source-grounded system brief. The Wikipedia schema also requested three to five
sentences. Jev already fixes source selection before writing.

The new `writer_prompt.py` builds a short role/style instruction followed by a
JSON evidence packet, an explicitly separate format example, and a final task
and grounding checklist. It follows [Inception's prompt guide](https://docs.inceptionlabs.ai/resources/prompt-guide).
Only source IDs, titles, descriptions/extracts and approved categories enter the
packet; private topics, popularity, scores and unrelated metadata are excluded.
Source values remain untrusted data. The tool retains its required fields,
types, enums and output identity; conflicting prose descriptions are replaced.
No source passage is rewritten or supplemented by another model.

The brief consistently requests two short banner sentences, a short title,
exactly three introduction sentences and three distinct short follow-ups tied
to explicit source concepts. Safety, promotion, clickbait and source-grounding
constraints remain explicit. A question may explore a source concept without
requiring the source to answer it, but cannot presume an absent fact.

## Evaluation design and verification

One cohort plans twelve source slots: video and Wikipedia for three concepts in
English and German. Source eligibility and thumbnail pixels are checked once;
all arms receive the same frozen evidence and images. Terminal discovery
shortages remain visible and are not replaced after outputs are seen.

The arms are current Gemini, original-request Mercury and clearer-request
Mercury. Both Mercury arms use LOW reasoning, temperature 0.5 and a 4,096-token
cap, isolating prompt/input changes. Each arm makes one attempt per source with
no fallback or separate LLM reviewer. Every actual draft receives unchanged
production assembly and native Jev admission checks. Raw writer quality is
reviewed separately against exact evidence, blinded to model and admission.
This review is automated, not human/native-speaker gold.

- **75 focused tests passed locally and in [isolated CI run 39744938433](https://github.com/glowingkitty/OpenMates/actions/runs/39744938433)**;
  scoped Ruff passed. Coverage includes public-evidence whitelisting, exact
  identities/categories, adversarial input serialization, no mutation, actual
  video/wiki schemas, diagnostic isolation and existing retry behavior.
- CI source: `e2b166d0641fd6604bd8a2b44eeb60bb8a2129a5`. Its receipt was
  retrieved and the evidence command completed with no unit recording inventory.
- Diagnostic candidate deployed to dev:
  `0b8885c012fbf3de81e8888210b330a15ff5527f`. Runtime operation
  `docker-9a0c3ccc` completed with all seventeen consumers healthy. Fourteen
  runtime module hashes are required before paid calls.

## Result and decision

Native comparison and blinded source-only audit are in progress. The runtime
writer remains Gemini until the comparison supports replacement. Costs are
captured supplier estimates before credits, with absent cache usage and external
retrieval/infrastructure charges reported separately; no full-refresh savings
claim follows from a small first-attempt source comparison.
