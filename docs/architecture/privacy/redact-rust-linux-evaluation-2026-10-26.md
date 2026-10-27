# Redact: direct Rust/Linux evaluation

Date: 2026-10-26. TASK-906; session 678f. This is an engineering evaluation,
not production CLI activation. The working browser/iPhone engine is unchanged.

## Result

Calling the published native engine directly from Rust does not remove the
long-input bottleneck. Short address detection is fast and process memory is
modest, but serial overlapping chunks dominate long messages. Matching native
threads to two available cores reduces the long fixture's latency by about 14%;
eight cores make it about 2.8 times faster than the original two-core default.
Faster chunking experiments lose detected personal data and are rejected.

| Direct Rust configuration | Address, 86 chars | 211 chars | 1,695 chars | 27,135 chars | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Published SDK, 2 cores, default native threads | 47.27 ms | 139.58 ms | 1,419.43 ms | 23,406.59 ms | 76.16 MiB |
| Published SDK, 2 cores, 2 native threads | 40.18 ms | 118.05 ms | 1,253.28 ms | 20,238.02 ms | 76.07 MiB |
| Published SDK, 8 cores, 8 native threads | 16.65 ms | 54.28 ms | 545.28 ms | 8,485.23 ms | 76.42 MiB |

These are medians of three scans after one warm-up, excluding download, licensing
and model initialization. This repetitive synthetic long fixture is a stress
case, not representative throughput. All 92 label/offset fingerprints match
across these three configurations; confidence is excluded from fingerprints.
The earlier Node two-core long result was 23,404 ms with the same native engine,
essentially the same as Rust/default.

The host is ARM64 Linux, with 16 Neoverse-N1 cores and approximately 32 GB RAM.
Affinity limits the benchmark to the stated cores; niceness is increased by 10.
There is no GPU. Different hardware, browser backends and messages are not
controlled comparisons. The earlier Node profile's 182 MiB peak and this Rust
profile's 76 MiB cover different workloads and are not an isolated host-language
comparison. No comparison with another vendor's model was run.

## Method and privacy boundary

`scripts/redact_rust_evaluation.rs` is an optimized Rust executable calling the
published Redact 4.1.0 native C ABI through `dlopen`. No Node or Python process
performs inference. Python compiles, verifies assets, supplies synthetic fixtures,
supervises limits and scores output. The engine itself is the vendor's Swift/
LiteRT implementation; this is a Rust host, not a model rewrite.

Pinned SDK source: `86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb`. Model
`redact@v0.4.0`: `3ed5033aeb544f454ebde77dc76fd7b7e76cc572`.
Native/model files are verified against the retained original manifest. Rust
1.98.1 compiles with edition 2021 and optimization enabled. The
[evidence manifest](evaluations/2026-10-26-redact-rust/manifest.json) records source,
binary, model, library and result hashes. The immutable engineering source
candidate is `39891df85b2486e03c5e7a8f7a2bcf1a15a322b2`.

The harness unconditionally initializes native download/session state, flushes
normal SDK licensing and verifies its real ES256 signature with OpenSSL. Every
successful full profile records a successful licence verification. It then
shuts down idle Internet connections without closing SDK-owned descriptors,
checks those disconnected descriptors, applies process-wide libseccomp TSYNC
network denial and verifies EPERM using a real socket call. Synthetic input is
read only after sealing. This proves offline content inference after ordinary
licensing, not a telemetry-free production licence.

The first pre-input probe refused to continue because a licence HTTP connection
remained open; its failed receipt is retained. Later probes simulate and verify
a disconnect before sealing. No content-bearing test ran under the failed seal.
A private patched Brotli 1.1.1 decoder is verified through the actual native
curl path; this evaluator does not use the affected host decoder.

UTF-16 offsets must be valid and reproduce the original substring. SDK redacted
output is independently reconstructed from spans and local placeholders, and
restoration must reproduce the input exactly. Original values, licence tokens
and installation identifiers are not saved in result receipts. Ten Rust unit
checks cover verification, codec, Unicode spans, restoration and socket shutdown;
nine Python checks cover input, scoring, completeness and immutable-build
validation. All passed, with independent review of the harness/restoration guard.
Python lint passed. Limits are 1,536 MiB RSS and bounded wall time.

## Root cause

The SDK defaults to approximately 150 UTF-16 characters per chunk with one
trailing sentence carried into the next chunk. The 27,135-character fixture has
512 short sentences, producing 511 serial padded model calls of 256 tokens.
The model has separate token-window handling for larger chunks; it does not
silently truncate all larger chunks at 256 tokens. Source comments warn that
extra neutral context can lower name scores because training used short strings.

`DAL_LITERT_THREADS` controls native LiteRT threads. Its default derives from
host CPU count, capped at eight, without respecting the smaller affinity used
in the original benchmark. Setting two threads on two cores avoids that
oversubscription. One native thread was slower in an exploratory probe. This
improvement does not make long-input latency acceptable for a general CLI filter.

Source: [chunker](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Redact/Chunks.swift),
[model windows](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Redact/Model.swift),
[thread setting](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/CLiteRt/shim.c).

## Quality and rejected optimizations

Full profiles contain 56 original quality fixtures with 50 annotated values and
12 negative cases, 32 added context/window probes and four latency inputs. The
harness uses the browser's 20-label policy at threshold 0.6. It tests model spans,
not the web hybrid's deterministic guards. Baseline model coverage is 14/50
values including every separator, or 30/50 covering all letters/digits/combining
marks; 2/12 negative cases are flagged. Context probes score 8/32 strict and
32/32 meaningful-character coverage. This finite synthetic sample is not a
population accuracy estimate. Full regex/secret detection remains necessary;
see the [earlier hybrid evaluation](redact-linux-evaluation-2026-10-26.md).

A task-private Linux SDK build changes only `Sources/Redact/Model.swift` behind
a benchmark compilation flag. Defaults remain 150 characters/carry one. All 903
other tracked files, including licensing/tokenization, match the pinned SDK.
Its 92 baseline fingerprints match the published SDK. The official Swift 6.3.3
toolchain signature, patch, dependencies and output hashes are retained in
receipts. No vendor binaries, weights or source archive are committed here.

| Experiment, 8 cores/8 threads | Long median | Detection comparison | Decision |
| --- | ---: | --- | --- |
| Rebuilt default 150 chars/carry one | 8,321.04 ms | Baseline parity passed | Reference |
| 300 chars/carry one | 2,308.06 ms | 9 annotated cases lose meaningful characters; context coverage 23/32 | Reject |
| 600 chars/carry one | 932.13 ms | 14 annotated cases lose meaningful characters; context coverage 18/32 | Reject |
| 150 chars/carry zero | 4,226.05 ms | Extra boundary sweep loses 14 meaningful characters in one German address | Reject |
| Default chunks, native LiteRT 2.3.1 | 8,767.54 ms | Baseline fingerprints match; no speed benefit | No performance upgrade |

Carry zero initially matched the main suite. An extra 28-case boundary sweep
found an individual regression even though aggregate coverage improved from
20/24 to 22/24 values. Per-value comparison prevents the aggregate improvement
from hiding a lost address. Larger-chunk comparisons also record individual
coverage losses, not only changed fingerprints.

LiteRT 2.3.1 came from the official versioned ARM64 object; published object
checksums and 35 required shim exports were verified. The core remained built
against 2.2 headers. Drop-in compatibility is not vendor-guaranteed: this is only
a private experiment. Browser LiteRT 2.6.0 is a different version line and was
not changed.

## Reproduction and decision

The supervisor accepts explicit native/model/decoder directories and fresh
output paths, with CPU, RSS and wall limits. Example, from the repository root
with verified artifacts present:

```sh
python3 scripts/redact_rust_evaluation.py --run \
  --native-directory /tmp/openmates-redact-inspect/redact/package/native/linux-arm64 \
  --model-directory /tmp/openmates-redact-rust-678f/model \
  --brotli-prefix /tmp/openmates-redact-678f-brotli-1.1.1 \
  --output /tmp/openmates-redact-rust-678f/reproduction-2cpu.json \
  --cores 2 --threads 2 --units 32 256 4096 --quality --repeats 3 \
  --timeout-seconds 300
```

The evidence folder includes byte-identical historical boundary/comparison
scripts. These are audit artifacts with task-private paths, not product commands;
do not run them over retained output paths. The build helper requires explicit
admission and verifies the exclusive patch. Toolchain/build scratch was removed
after checking live references; unique source, outputs, signatures and evidence
remain task-private.

Keep the working browser and full regex fallback. Do not adopt the rejected
shortcuts or activate the CLI model on these results. A major native speed
improvement requires an engine/backend change verified with boundary-sensitive
quality cases. Separately, the [licensing/privacy review](redact-licensing-privacy-review-2026-10-26.md)
withholds production approval: browsers directly submit licensing metadata/IPs,
and the vendor policy does not adequately explain SDK processing.
