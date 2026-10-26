# Redact large-document optimization on Linux

Date: 2026-10-26. TASK-906, session 678f. Follow-up to the
[direct Rust evaluation](redact-rust-linux-evaluation-2026-10-26.md).

The user requested more optimization before considering any large-document
opt-out default. File-size defaults and the working browser implementation are
unchanged. These are private native SDK experiments, not CLI/TUI activation or
production approval. Licensing/privacy requirements remain unresolved separately.

## Changes under test

The first candidate distributes the original overlapping chunks across a bounded
pool of independent compiled models. Calling a shared model concurrently does
not help because LiteRT serializes its mutable buffers under a model lock.
Each worker owns one independent session, all initialized through the normal
licensed factory during model loading. It uses the same tokenizer, 150-character
chunk boundaries, carry-one overlap, 254-content-token windows, thresholds and
label policy. Chunk scores merge in original order; contextual cleanup and
hysteresis run once over the whole document, followed by ordinary global
placeholder creation/restoration. Increasing chunks or dropping overlap is not
part of this experiment.

A second candidate avoids unnecessary allocations in name cleanup. The original
`adjacentName` copies the entire text between two spans before rejecting a name
gap over 20 UTF-16 units. `bridgeNameGaps` similarly copies arbitrarily long gaps
that cannot qualify. The candidate rejects distances over 20 before copying,
preserving the original overlap branch and all short-gap predicates. A standalone
Swift proof passed 164,224 comparisons, including Unicode, surrogate cuts,
overlap, whitespace and boundary lengths. An independent review found no
blocking concurrency or reduction-semantic issues.

Both changes are Linux benchmark compilation guards; absent environment
overrides retain the original serial/default-gap paths. The first candidate
changes exactly `Model.swift` and `ModelLoading.swift`, with 902 other tracked
SDK files unchanged. The second additionally changes `Pipeline.swift`, with 901
unchanged. Original-relative patches and native hashes are retained. Licensing,
telemetry, deterministic detection and tokenizer source remain intact.

## Corpus and controls

`scripts/redact_large_document_fixtures.py` generates deterministic varied prose,
Markdown, TypeScript, and Python/config at approximately 32 and 128 KiB, plus
two code negative controls. Blocks vary their words and indexes; this avoids
crediting a repeated-sentence cache for large-file performance. Eight positive
documents contain 120 occurrence-specific UTF-16 annotations, including repeated
names, addresses, email, account data, a synthetic credential and multilingual
context. Values appear near the beginning, middle, end and selected boundaries.
The generator keeps annotation offsets for every repeated occurrence rather
than scoring only its first match.

Together with the original 56 quality cases, 32 context probes, 28 split-boundary
probes and the historical repetitive stress text, the full corpus contains 127
cases, 226 annotated occurrences and 880,247 input bytes. Explicit synthetic
fixtures only; no project source, account data or real user documents are read.

Each native process runs through the unchanged optimized Rust C-ABI host.
Python supervises and scores only. Model files and native libraries are verified
before load. Normal SDK licensing completes, including real ES256 verification,
then idle connections are disconnected and process-wide libseccomp TSYNC denies
network operations. Synthetic text is read only after the seal. Exact SDK output
reconstruction and original-text restoration checks remain enabled.

All matrix runs use eight allowed ARM Neoverse-N1 CPU cores at nice 10, with
workers multiplied by native inference threads capped at eight. There is no GPU.
Each profile starts one fresh process; its cases are scanned once each, without
a per-call result cache. In full profiles the quality cases precede the large
files, so the latter use an already initialized runtime. These pilot samples
are not representative percentiles, cold-launch timings or repeatability proof.
The shared development host is not an exclusive benchmark machine. RSS is
limited to 1,536 MiB and each profile has a wall-time watchdog.

## Results

The [evidence manifest](evaluations/2026-10-26-redact-parallel/manifest.json)
binds raw profiles, comparisons, source versions, build patches and probe proofs.

Times below are seconds for a complete document scan; download, model loading
and licensing are excluded. They include native result decoding and independent
Rust restoration validation. Size labels are generator targets; actual UTF-8
lengths vary by less than 1 KiB.

| Configuration, total CPU budget 8 | 32 KiB prose | 32 KiB Markdown | 32 KiB TypeScript | 128 KiB prose | 128 KiB Markdown | 128 KiB TypeScript | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Published SDK, 1 worker / 8 threads | 5.66 | 100.33 | 5.87 | 30.77 | Watchdog during this case | Not reached | 82.4 MiB |
| Early gap checks, 1 worker / 8 threads | 5.69 | 6.76 | 6.51 | 23.31 | 29.63 | 24.09 | 83.1 MiB |
| Early gap checks, 2 workers / 4 threads | 4.11 | 4.46 | 5.34 | 17.51 | 21.04 | 17.84 | 126.0 MiB |
| Early gap checks, 4 workers / 2 threads | 3.26 | 3.66 | 3.70 | 13.56 | 17.58 | 14.85 | 208.0 MiB |
| Early gap checks, 8 workers / 1 thread | 3.16 | 3.61 | 3.59 | 12.86 | 17.48 | 14.58 | 372.7 MiB |

The published profile hit its 600-second whole-profile limit while scanning
128 KiB Markdown, after completing 122 cases. That is not a 600-second timing
for that one case; all earlier work consumed part of the budget. The timeout and
completed checkpoints are retained. The optimized sequential profile finished
all 127 cases in 177.67 seconds; the 2/4/8-worker profiles took 133.57/110.03/
110.74 seconds respectively, including initialization/licensing.

Four workers are the best measured memory tradeoff: eight add little throughput
while using approximately 164 MiB more peak RSS. The Markdown improvement is
large (about 27 times at 32 KiB), while ordinary code/prose gains are much more
modest. This experiment does not establish universally fast bulk scans on Linux.
Results apply to this ARM host and these files, not every Linux server.

Peak observed RSS is the larger of sampled RSS and the child's recorded high
water mark. Sampling is approximate; this is not allocator-level accounting.

## Larger files and more CPU capacity

The user subsequently set a 2–3 second full-file target. A second scaling test
uses the same varied Markdown and TypeScript at approximately 512 KiB. A final
test permits all 16 host cores with eight independent two-thread workers. This
has more CPU capacity than the earlier matrix and is reported separately.

| CPU budget and workers | 32 KiB Markdown | 32 KiB TypeScript | 128 KiB Markdown | 128 KiB TypeScript | 512 KiB Markdown | 512 KiB TypeScript |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 cores, 1 worker / 8 threads | 6.76 | 6.51 | 29.63 | 24.09 | 182.86 | 96.14 |
| 8 cores, 4 workers / 2 threads | 3.66 | 3.70 | 17.58 | 14.85 | 139.58 | 56.89 |
| 16 cores, 8 workers / 2 threads | 2.70 | 2.39 | 12.59 | 10.28 | 122.39 | 39.18 |

All selected 512 KiB spans match their optimized sequential control. All six
16-core cases match the corresponding sequential controls after verifying
per-case text hashes and model/native/Rust identities; CPU-affinity differences
are explicit. The larger files still fail the user's target. More RAM permits
more sessions, but does not remove inference cost or serial document cleanup.
This does not establish a universal Linux file-size threshold.

A pure Rust attribution check reconstructed valid response payloads for all six
16-core cases and passed them through the unchanged `parse_result` function,
including full restoration checks. Three repetitions per payload matched the
recorded fingerprints. Median validator cost was 44 ms/893 ms for 128/512 KiB
Markdown and 3.4 ms/19.3 ms for TypeScript. No SDK or model code ran in that check.
The validator therefore does not explain the remaining bulk-scan delay; removing
it would still leave these large files well above the target.

## Fixed-padding feasibility test

The pinned model runs 256-position windows even for short chunks. Public LiteRT
APIs expose input resizing, so a copied licensed Rust host attempted `[1,64]`
allocation after normal SDK licensing and network sealing. Both retained native
runtimes (2.2 and 2.3.1) accepted the two input-resize calls but rejected output
allocation: the first fixed `RESHAPE` requires 256 elements and receives 64.
Each probe completed in about 0.41 seconds. No text input was read, logits were
not invoked, and model files/weights were not modified. This is a failed
allocation feasibility test, not a shorter-window performance measurement.

The original inherited receipt contains an inapplicable `input_read_after_seal`
field; its probe-specific fields and generated early return prove no input read.
A separate clarification preserves the historical hashes, and future probe
receipts explicitly say `input_read: false`. Future preparation/run paths are
content-addressed so they cannot replace the historical evidence. No known
allocation failure was repeated to repair metadata.

A substantial further CPU inference change therefore needs a compatible
variable-length/batched export or another backend/model, verified against the
same boundary-sensitive cases. The published immutable repository contains
TFLite and Core ML exports, not an ONNX export or training checkpoint. The
[LiteRT API](https://developers.google.com/edge/api/litert/c/classlitert/1-1-compiled-model)
documents resizing and reallocation, but does not guarantee a static graph can
accept arbitrary dimensions.

The 2–3 second target is not met for these large files on this host, even with
16 CPU cores. The recommended native integration is automatic enhanced scanning
only where full-file calibration fits the latency budget, with complete basic
regex processing otherwise and an explicit slower enhanced full-scan option.
An enforced deadline must accompany prediction. More capable machines can admit
larger inputs after their own calibration; extra RAM alone is insufficient.

## Memory and latency policy prototype

`scripts/redact_native_resource_policy.rs` implements the proposed native
resource selection as a standalone, reusable Rust prototype. It does not activate
product CLI/TUI settings or change the browser's model policy.

| Nominal effective RAM | Enhanced model budget ceiling |
| --- | ---: |
| 2 GiB or less | Disabled; retain regex |
| 4 GiB | 300 MiB |
| 8 GiB | 800 MiB |
| 16 GiB or more | 1,536 MiB |

Usable-RAM thresholds allow 12.5% kernel reservation for the nominal tiers;
intermediate values use the lower known tier. The actual budget also cannot
exceed one quarter of currently available memory. Container limits and remaining
headroom are separate inputs: a cgroup cap without current remaining headroom
fails closed. A 4 GiB container with 200 MiB remaining does not inherit the
host's free RAM. Worker selection conservatively estimates 96 MiB base plus
48 MiB per worker, caps at eight supported workers and approximately half the
available CPU count, and uses at most two inference threads per worker.

Budgets are ceilings, not targets to fill. Available CPU counts must also account
for platform affinity/quotas. A 300 MiB watchdog profile completed with four
workers; an eight-worker profile under the same limit was stopped on RSS without
a completed inference result. The sampled watcher observed approximately 302 MiB before stopping:
it can transiently overshoot and is not a hard kernel cgroup limit. These are
simulated budget checks on this host, not physical 2/4/8/16 GiB machine tests.

Resource eligibility alone never approves automatic enhanced scanning. A
separate prototype gate requires a calibrated prediction for the entire file
of at most 2,500 ms. Missing calibration or a slower prediction retains regex;
an explicit full-scan request can bypass latency, but cannot bypass memory
restrictions. This is a prediction policy, not a guarantee that real runtime
never overruns. Product integration also needs an enforced deadline/cancellation
path and the existing privacy/licensing decision. No arbitrary byte cutoff or
silent partial-enhanced claim is introduced here.

Five Rust resource-policy tests cover tier/headroom/cgroup/CPU limits, numeric
edge cases and latency/override semantics. Ten Python checks cover synthetic
occurrences, full input/native provenance, explicit optimized controls and
coverage comparisons. All passed. Public-header ABI compilation, both native
candidate builds and corrected-probe dry compilation also passed.

## Detection checks and limits

All 122 completed published-engine cases match the optimized sequential
candidate's labels and UTF-16 offsets exactly, with no individual annotated
coverage loss. The five cases not completed by that published profile have no
full published-run parity claim. All 127 cases match exactly between the
optimized sequential profile and each parallel configuration, again with no
annotated coverage losses. Confidence is excluded from span comparisons.

The early-gap predicate proof and ordered-merge review additionally address
semantic equivalence; finite fixtures alone cannot establish it for every text.
Existing model misses and code false positives are not repaired by concurrency.
These checks preserve baseline behavior rather than claiming complete
anonymization. Full regex/secret detection remains essential.

## Reproduction

The private build helper is `scripts/redact_native_chunk_experiment.py` with
`--parallel` or `--parallel-fast-gaps`. It verifies the pinned SDK archive,
official signed Swift toolchain and exact changed-file inventory. Retained
receipts include patches, dependencies, proof and library hashes. The private
toolchain/build scratch was removed only after live-reference checks; sources,
archives, native outputs, signatures, proof and receipts were preserved.

`scripts/redact_parallel_evaluation.py` supports explicit worker/thread/CPU
budgets, corpus selection and fresh evidence paths. Its default baseline mode
requires a completed published single-worker profile with matching input,
model, Rust binary/source and CPU affinity. `--optimized-baseline` explicitly
permits a completed same-build sequential fast-gap control; it is not presented
as a published-engine control. Failed/partial published observations are admitted
separately and explicitly scoped to completed cases.

The [licensing/privacy review](redact-licensing-privacy-review-2026-10-26.md)
continues to withhold production approval. No large-file fallback/default change
or browser engine change is made by this engineering work.
