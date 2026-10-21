# Direct image references: implementation and verification

Task: TASK-7471. Complete with an accepted known limitation. Direct-reference
implementation and timing verification are complete; the final live answer retains
the narrow visual-grounding finding documented below. On 2026-10-21, after reviewing
the results and disclosed limitation, the user said, "Improvement sounds good
enough to deploy and end this task." This accepts task closure with that limitation;
it does not turn the failed strict narrative check into a pass. The proposed
per-requirement visual-evidence extension is deferred.
Approved contracts: architecture.app-skill-execution@1, feature.ai-model-routing@7,
and feature.app-skill.shopping-search@2.

## Implemented

- A usable text query plus image references goes directly to the consuming skill.
  The assistant initially receives exact references and metadata, without eager
  pixel loading or an unnecessary `images.view` prerequisite.
- Genuine visual questions and photo-only identification retain the viewer.
  Historical uploads do not make an unrelated question a visual task.
- Shopping and reverse image search share owner-bound exact-reference resolution,
  supported encrypted-image decoding, and expiry checks before provider work.
  Fresh-upload recovery preserves the original 24-hour expiry.
- Shopping preserves and displays all photos supplied by search providers. Jev
  compares up to three photos per product with up to three reference images.
  Extra paid Amazon gallery enrichment remains deferred.
- Relevance searches request forty candidates before filtering, subject to
  availability. The requested final cap remains independent. Visual scores use
  0–4 with a floor of two; unavailable comparisons remain explicit.
- The main assistant's complexity reflects its own work, independently of the
  forty-product comparison delegated to Shopping. Current automatic profiles and
  explicit user preferences remain authoritative.
- Persistent tool guidance requires catalogue evidence for composition,
  manufacturer and identity claims, labels partial alternatives, and forbids
  invented rejection causes or unseen image details. It survives restored history.

## Evidence

| Required check | Result |
| --- | --- |
| Routing, ownership, expiry, decoding, ranking and grounding | 561 focused backend checks passed; four dependency warnings |
| Actual upload producer/parser and owner-reference roundtrip | Two positive and six rejection cases passed |
| Browser gallery, direct Shopping/reverse search, forty-candidate cap, inaccessible reference, owner and reference-limit checks | Seven passed; none failed, skipped or flaky |
| Browser environment cleanup and recordings | Verified; all seven selected recordings uploaded |
| Final direct real-AI Shopping | Routing, forty-candidate comparison, material uncertainty and score scale passed; strict visual-narrative grounding failed narrowly; 19.813 seconds |
| Genuine image question | Passed on 8bdbae4: correct five circles, one viewer call, Gemini 3.8 Flash LOW, 9.306 seconds |
| Unrelated follow-up in the same image chat | Passed on 8bdbae4: 42, no viewer or Shopping call, Gemini 3.8 Flash LOW, 8.612 seconds |
| Disposable live Project/chat/credential cleanup | Four owned chats absent from authoritative inventory; owned Project absent; isolated credentials and state removed after evidence preservation |

The final browser run used exact source
`889104572955e31455f0d4764fc16b86ea0ffcc9`:
[isolated CI run](https://github.com/glowingkitty/OpenMates/actions/runs/39486197197).
The implementation was published as `6728671`, with initial grounding guidance as
`8bdbae4` and the trusted Shopping system policy as `1807f82`. The final live case
ran on runtime `cfb1d6b`, which contains that policy. The API and AI worker both
read the exact persistent instruction from the shared metadata cache after the
coordinated healthy refresh. The
accepted image and unrelated-follow-up flows did not select Shopping; their
main-model, viewer and Math paths are unchanged by the Shopping-only policy.
Browser fixtures verify real processing and serialization; live inference is a
separate quality check. All live OpenMates requests use current Auto without
model/provider/account overrides.

The earlier Qwen selection was a routing bug: the uploaded-image guard excluded
all Google models, making the configured Gemini choice ineligible and allowing
Qwen as the next eligible fallback. Compatibility and multimodal tool handling
were corrected while preserving genuine image inspection. The three latest live
flows all selected Gemini 3.8 Flash LOW automatically. Correct routing did not by
itself eliminate the unsupported visual explanation described below.

## Timing and cost

The prior viewer-first trace took 59.300 seconds from API receipt to final
persistence. It made three Gemini 3.8 Flash HIGH calls. The final optimized trace
took 19.813 seconds with two Auto-selected Gemini 3.8 Flash LOW calls and no viewer.
This was a 39.488-second, approximately 67% reduction in those observations; the
different thinking profiles and single observations are not a controlled latency
distribution or a service guarantee.

| Optimized stage | Seconds |
| --- | ---: |
| Setup | 3.429 |
| First assistant call | 3.061 |
| Shopping and bookkeeping | 6.955 |
| Final assistant call | 5.603 |
| Finalization | 0.764 |

Actual Shopping execution took 5.822 seconds. Nested measured stages were 0.804
resolving references, 1.360 searching and normalizing, 1.967 preparing product
photos, and 1.320 in parallel Jev batches; the remaining time was local overhead.
All forty products were evaluated, using 107 prepared product photos. One secondary
photo failed; no product comparison was unavailable. The old Shopping work took
6.930 seconds. The major improvement therefore came from assistant orchestration:
main-model wall time fell from 43.262 to 8.664 seconds, with the unnecessary viewer
round trip removed.

The eight visual Jev calls reported 58,376 input and 712 output tokens, costing an
estimated $0.002452 at the configured tariff, about $2.45 per thousand equivalent
forty-product comparisons. All eleven correlated Jev calls cost about $0.003307.
The two main Gemini calls have a configured-tariff upper estimate of $0.020596;
the first call's cache accounting was incomplete. Known AI estimates, including
asynchronous metadata and translation, total about $0.027990. This is a partial
subtotal, not a whole-request upper bound: one failed auxiliary Mercury 3 metadata
attempt has unknown usage before its Gemini Lite recovery. It was not a main-model
failure or a Mercury Decide call. These are provider estimates, not an invoice.
The 90.861-second CLI capture includes setup, uploads and readback; it is separate
from the 19.813-second API-to-final response measurement.

## Quality and limits

The final optimized request retained the strong Stoffe.de fabric match
SKU 68090083 at 3.02/4, and a broader lemon-themed alternative, SKU 68090790,
at 2.01/4. The latter does not meet a strict stripe requirement. The approved floor
of two permits partial alternatives; it was not silently raised.

Independent review found unsupported rejection reasons and visual details in the
first answer, despite correct counts, score scale and composition caveats. A second
live Gemini run took 23.284 seconds and correctly limited its rejection explanation
to the threshold count, but still invented unreturned visual details and extended a
brand into a seller claim. This demonstrates a grounding issue beyond the earlier
Qwen routing selection. The new Shopping policy is retained in trusted system
prompts across initial, synthesis and recovery calls, with actual provider-message
regressions. The final run kept material composition unconfirmed, used the correct
0–4 scale, retained Brand without inventing a seller, labelled the weaker result
as an alternative, and explained filtering through the returned threshold count.
It nevertheless described that alternative as lacking a prominent striped element
and having a beige ground. Those details were not returned as visual observations;
a title lacking the word "striped" does not establish absence of stripes. Strict
visual-narrative grounding therefore remains a narrow failure. This is explicitly
not presented as three wholly passing real-AI quality cases.

The reference-forwarding and comparison implementation is verified, and the
requested material/score corrections held in this sample. The quality assessment
does not establish universally grounded assistant descriptions. Jev currently
returns scores with a generic legend, not per-feature observations. A further
wording-only retry would not close that evidence gap. Richer explanations should
first receive bounded, per-requirement observed/conflicting/unknown evidence with
candidate/photo provenance; that output needs its own implementation and measured
quality coverage. Until then, catalogue facts and similarity scores are the
available evidence, and the remaining free-text extrapolation is a known risk.
Only retained products were independently reviewed; the aggregate filtered count
does not establish precision, recall or correctness for every rejected candidate.

## Provider and next-step recommendations

Keep Jev 1.14. In the small paired categorical benchmark Mercury Decide answered
29/29 valid paired cases correctly versus Jev's 27/29. Its paid OpenRouter route
then returned two HTTP 503 responses; the repeat matrix is incomplete. Median image
latency was 591 ms on that route versus 289 ms for direct Jev. Route, serialization
and token accounting differed. Actual 0–4 Shopping ranking and full forty-product
Mercury throughput remain untested. See the [benchmark](../../apis/mercury-decide-jev-comparison.md).

No SubQ fallback was added. Current Project selection shortlists at most 24 metadata
records and selects four references before content hydration; a larger context
window alone does not repair candidate discovery. TypeSafe is not established as
categorically better on public retention promises: no training does not imply zero
retention, no fixed public maximum is promised, and enterprise zero retention is a
separate offering. English/German privacy disclosures reflect this. SubQ's newer
sixty-day terms conflict with its indefinite-retention API documentation. See the
[processing assessment](../../apis/typesafe-subq-data-handling-assessment.md).

Prioritize explicit visual evidence for answer grounding, then main-model prompt
and final-answer latency. A future strict-match
mode could separate hard requirements from preferences and unknown evidence. It
needs explicit product semantics and representative labels, rather than an
unmeasured threshold change. Obtain account-specific retention commitments before
adding another decision provider. Bounding boxes could support a future crop of one
item in a multi-item reference photo; they are not required for this implementation.

## Safe cleanup

Disposable caches and all completed test-build copies were removed,
as were two obsolete task-owned worktrees. Recovery archives and test evidence were
preserved. Seven legacy worktrees with pending work or ownership records were
retained. No other task's source or persistent Docker data was deleted.
