# TypeSafe and SubQ: retention and long-context assessment

Verified against public documentation on 2026-10-19. This records public promises;
the OpenMates accounts' negotiated agreements and retention settings are unverified.

## Recommendation

Keep Jev for current decisions. Do not add automatic SubQ fallback or an oversized
request route yet. Public retention evidence does not establish that TypeSafe is
categorically better, but adding another provider creates another disclosure,
failure mode and integration cost without a demonstrated current requirement.

## Retention correction

- [TypeSafe privacy policy](https://typesafe.ai/legal/privacy-policy) states that
  submitted input is not used to train or fine-tune models. Its
  [processing agreement](https://typesafe.ai/legal/data-processing) describes
  purpose- and law-based retention without a fixed maximum.
  [Enterprise zero data retention](https://docs.typesafe.ai/legal) is separately
  offered; it is not established as active on the standard OpenMates route.
- [SubQ terms](https://subq.ai/terms), updated October 16, specify no foundational
  model training/improvement from customer content and at most sixty days for
  inputs/outputs, with flagged-content investigation and legal exceptions.
  Zero retention requires approval and retains exceptions. Its
  [API retention docs](https://docs.subq.ai/using-the-api/data-retention/) still
  describe indefinite default retention. That conflict needs an account-specific
  answer before adoption. The earlier benchmark report's blanket indefinite-default
  privacy conclusion should be read in light of these newer contractual terms.

No-training commitments and immediate deletion are separate properties. Neither
provider's ordinary public promise establishes unconditional zero retention.

## Do current Projects require a larger window?

No demonstrated need was found in the current implementation:

- `ProjectContextSelectionService` evaluates at most 24 metadata candidates,
  capped at 200 title characters and 640 characters each for description and
  when-to-use, plus an 8,000-character request. It selects at most four references
  and does not load/decrypt their full contents for selection.
- `agenticProjectContextService` discovers at most twenty `.openmates` reference
  documents plus folders up to the 24-candidate limit. Selected documents are read
  afterwards. This does not scan every arbitrary project file or embed.
- `hostedProjectFileExecutor` already supports authorized filename/content search,
  filters private/ignored paths before decryption, and examines at most 100 files.
  Search hits carry line numbers and 500-character snippets; optional full-content
  responses are bounded to eight files, 24 KiB each and 96 KiB total.
- Recommendation and focus flows also shortlist metadata before loading bodies.
  Other decision workloads use bounded candidate projections or batching.

Increasing a model window alone would not repair missed files caused by candidate
discovery limits or weak metadata. Better discovery, hierarchical summaries,
targeted content search and candidate batching should come first. They also expose
less decrypted private content to inference providers.

A future specialist route could help a small number of decisions that depend
jointly on dispersed evidence: superseded requirements across a large approved
bundle, consistency across related specifications, or dependency-complete file
selection where independent relevance scores fail. Demonstrate those failures on
representative privacy-safe cases before integrating another provider.

## What the measured benchmark supports

The existing benchmark's production-shaped routing favored Jev 1.14: median
246 ms, 222/222 labels and estimated $0.3437 per 1,000 logical calls, compared
with SubQ's 677 ms, 219/222 and $0.4180. Near 250K provider-counted input tokens,
SubQ was faster with matching simple retrieval accuracy; approximately 371K also
succeeded. Those controls test retrieval and explicit record precedence, not
corpus-wide reasoning or actual Project-selection outcomes.

SubQ's [393,216-token window](https://docs.subq.ai/endpoints/decisions-api/) comes
with a sixteen-question request cap. Many candidate decisions can therefore
repeat a large state across requests. Jev also offers an experimental
[262K context limit](https://docs.typesafe.ai/models), which the current
OpenMates adapter does not enable. A SubQ-only oversized route would need an
explicit retrieval/batching degradation path when SubQ is unavailable.

## Jev 1.14 bounding boxes

[Box](https://docs.typesafe.ai/primitives/box) is experimental and requires Jev
1.14 plus the images danger-zone header. It returns normalized rectangle edges
and confidence, and always returns a rectangle even when the object is absent;
pair it with a presence Noul. Practical uses include cropping fabric/product
regions out of a room photo or screenshot and isolating labels before OCR.
Already-cropped product thumbnails do not need object localization. Ordinary
reference-image comparison works on the existing Jev version; boxes alone do
not justify a global version change.
