# Redact Linux evaluation

Date: 2026-10-26. Task: TASK-906. Session: 678f.
Dependency: working web trial TASK-6119. Production CLI integration is deferred.

The native SDK completed offline classification on this ARM Linux host with
about 182 MiB peak process RSS. Long-input scans are expensive: 27,135 characters
took a median 41.1 seconds on one core and 23.4 seconds on two. Redact adds useful
name/address components but cannot replace deterministic secret detection.
Production CLI integration remains deferred.

The parent confirmed the web trial before native execution. One complete native
quality/latency profile and a two-core long-input supplement succeeded. Both
initial five-minute watchdog terminations remain recorded; completed shorter
two-core timing groups are explicitly identified as partial-profile evidence.

## Pinned source

Use published `@desert-ant-labs/redact/native` 4.1.0,
`@desert-ant-labs/core` 4.1.0 and koffi 2.16.3. Installed Linux ARM64 prebuilts
include `libRedactNode.so`, `libLiteRt.so` and `libdalcpushim.so`.
No GPU, global install, service mutation, real user data, training or OpenMates
chat/model override is involved.

The SDK catalog pins `desert-ant-labs/redact@v0.4.0`, resolved on 2026-10-26 to
commit `3ed5033aeb544f454ebde77dc76fd7b7e76cc572`:

| File | Bytes | Pinned integrity |
| --- | ---: | --- |
| `redact.tflite` | 24,529,472 | SHA-256 `ee36727f07e3237569e71427bfe661463a82e526f7e97e92b0fa583cad16ed27` |
| `redact_tokenizer.bin` | 391,416 | SHA-256 `81bc354dc99285e05b8f70edca9df3afbd83dfa4b0cea18d0448ab17ce58aae2` |
| `labels.json` | 3,842 | Git blob SHA-1 `fe76679736d86b47a45fe03a94994aa292fc6203` |

The downloader uses the immutable commit and verifies size/hash before saving.
The evaluator verifies the assets again before SDK load, and records SHA-256 for
every model file and native library. Npm integrity strings are in the manifest.

Sources checked 2026-10-26:

- [Published Node API and native support](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/packages/redact-node/README.md).
- [Pinned model catalog](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Redact/Catalog.swift).
- [Native licensing request implementation](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Licensing.swift).
- [Native installation/license persistence](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Storage.swift).
- [Pinned model metadata](https://huggingface.co/api/models/desert-ant-labs/redact/revision/v0.4.0?blobs=true).
- [Model card, taxonomy and language limits](https://huggingface.co/desert-ant-labs/redact).
- [Source-available license](https://license.desertant.com/1.0).

## Quality and reliability protocol

Import the actual detector used by `scripts/privacy_filter_regex_baseline.mjs`
directly, alongside the current `webPIIMatches.ts` adapter; retain source hashes
with each result. The 56 existing synthetic fixtures contain 50 annotated values
and 12 negatives: code, UUIDs, hashes, timestamps, placeholders and public links.
Three generated long-tail fixtures add an emoji, name and email after growing
neutral context. Their whitespace lengths do not identify an exact native
tokenizer window boundary.

Retain six variants separately:

1. Raw SDK defaults with native label names.
2. SDK with browser labels, excluding blanket URL and ORG.
3. Actual regex/validator detector.
4. Browser-policy SDK plus actual web guards/merging and full regex.
5. Regex with fixture-configured private values.
6. The hybrid with the same configured values.

Every span must exactly reproduce its original using JavaScript UTF-16 slicing,
without splitting a surrogate pair. Convert valid spans additionally to Unicode
code points for comparison with the earlier Python evaluator. Do not search,
shift or repair invalid offsets. Protection requires **every annotated character**,
including address separators, spaces and credential punctuation, to be covered.
Retain exact single spans, partial matches, category results and negative-case
false positives separately. Different label taxonomies do not prevent scoring.

Restoring raw and browser-policy SDK results must reproduce each input exactly.
Repeated latency scans compare label/offset fingerprints and record RSS before
and after each length. The supervisor records crashes, timeout and memory-limit
termination. A second metric counts values with all letters, digits and combining
marks covered, distinguishing meaningful uncovered characters from separators
between component spans. It does not excuse uncovered credential punctuation;
strict coverage remains the full-value metric. This bounded sample cannot establish production reliability or
long-term absence of memory leaks.

Redact has no contextual `SECRET` head. Deterministic secret detection and exact
configured values remain essential; unknown contextual passphrases may be missed.
Japanese and Arabic are outside its published 27-language list; retain these
fixtures as limitation probes. This small synthetic set cannot establish
population accuracy or guarantee anonymity.

## Resource and latency protocol

Run sequential fresh processes on one and two allowed CPU cores at reduced
priority. All native threads inherit affinity. The public SDK has no documented
native thread-count option: its default remains and thread count is recorded.
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and the Node worker pool are additional
hints; affinity supplies the actual CPU ceiling.
The host has 16 ARM Neoverse-N1 cores and approximately 32 GB RAM. Measured
processes used Linux 6.8.0-137-generic and Node v24.22.1, with CPU affinity `0`
or `0-1`, niceness increased by 10 and no GPU. Internal thread counts after SDK
load were 11 and 13 in the successful one-core and two-core processes; their
CPU use remained bounded by affinity.

Default limits: 1,536 MiB RSS sampled every 100 ms, 300-second wall time and
256-MiB Node heap. RSS polling is a watchdog, allowing a transient overshoot
between samples. Also record Linux process-lifetime peak RSS, RSS before model
load, after load and after repeated scans.

Disk is the logical sum of the three model files and selected host's native
libraries. Exclude shared system libraries, Node, other-platform binaries and the
JavaScript dependency tree. This differs from browser WASM/download footprint.

Record first model load in a new process, then a reload after disposal in the
same process. Leave OS caches intact; neither is a cold-disk result. Download time
is outside load timing. Run one warm-up per length. Initial profiles attempted
seven repetitions and hit the 300-second watchdog. The first one-core attempt
had no stage checkpoint; the two-core checkpoint places its timeout in the
longest timing group. The
successful one-core retry used three repetitions with a 600-second ceiling; the
two-core supplement repeats only the missing longest length three times.
Lengths are 32, 256, 1,024 and 4,096 whitespace units, **not model-token counts**:
the documented JavaScript API does not expose its tokenizer. Report characters,
sample count, minimum, median, maximum and all samples. These sample sizes do not
establish representative percentiles.

## Offline inference and required telemetry

Normal SDK model load and `flushTelemetry()` finish before offline inference;
required reporting remains intact. Refuse license-endpoint overrides and raw
HTTP debug logging. Inputs/predictions never enter network requests or terminal
logs. Saved synthetic evidence uses split `synthetic_parts` arrays assembled
locally, preserving complete recoverable predictions without literal vendor keys.

After flushing, require no owned existing Internet sockets and apply libseccomp
TSYNC to all existing/future threads. Deny sockets, connection attempts and
send-message syscalls; a real libc socket call must fail with EPERM. Inference
runs only after this self-check; fixture inputs are loaded after sealing.
Unavailable filtering, residual sockets, load
errors or invalid offsets stop the profile. Do not modify SDK telemetry. This
process-only seal proves offline inference; it is not a production reporting policy.
Normal native licensing persists its installation identifier and license through
Foundation `UserDefaults`; the harness neither reads those values nor redirects
the store. The explicit directory holds public model assets only. These normal
SDK storage writes and development licensing metadata requests are authorized;
no OpenMates account, encrypted chat or CLI state is used.
The native run proves content-bearing calls complete under an actual OS deny.
Native HTTPS bodies were not intercepted: their metadata-only schema is supported
by the pinned licensing implementation and the separate web audit. The native
flush API waits for requests without exposing HTTP response success.

## CVE-2026-111497: evaluator remediation

The historical benchmark's on-load licensing phase used the host's libcurl with
system `libbrotli1=1.1.0-2build2`, before content classification was network-sealed.
That decoder is in the affected upstream range. Patched Node 24.22.1 does not
fix this separate native dependency: the SDK's statically bundled Swift
FoundationNetworking uses its curlcompat shim to open system `libcurl.so.4` with
`RTLD_DEEPBIND`. Foundation enables automatic response decompression, including
Brotli when libcurl supports it. No malicious compressed input or exploitation
was tested or observed. Original benchmark JSON, manifest and measurement hashes
remain unchanged; the following loader verification is separate evidence.

The evaluator now requires a task-private, ABI-compatible Brotli **1.1.1** build
before any SDK model/HTTP load. Host packages, services, browser configuration
and normal SDK licensing/reporting were not changed. The helper compiles only
the upstream common/decoder shared libraries with existing `cc`, SONAME 1,
reduced priority and at most two CPUs. CMake was unavailable; no tools or packages
were installed. The entire private source/build prefix occupies about 3.2 MiB.

- Official tag `v1.1.1`, commit `db0631dfea829194206d269bc7b25d0908cdb97d`.
- Source archive SHA-256: `38f9c17ee36c2e930ce00975b50fcd246a8e5594c1bcf43cd56b14118786b82a`.
- Decoder source SHA-256: `79db5a1879540eb7c915ce948e8fb94adc1ff49be87dca01529b9283c6ba343e`.
- Built decoder SHA-256: `2db67bd9c7d1bec64a4c0c60b0d157abacd39d4757cdca93a31894eebe5e8b1f`.
- Built common-library SHA-256: `74907dcc520f4df0de4ffa271070a7d91e553f7ed0f2ae94608d4f12d650037c`.

The pinned decoder returns the permanent format-block-switch error when the
block-type count is invalid, and propagates status from literal, command and
distance block switches. Both source identity and this fixed logic are checked.
The supervisor verifies source/library hashes and sets `LD_LIBRARY_PATH` only
for its child processes, replacing inherited search paths. It rejects loader
interposition and missing/unverified prefixes. The direct Node evaluator also
checks these identities before native model loading, so invoking it directly
does not silently fall back to the host decoder.

Loader-only probes load the actual SDK C shim, obtain its already-loaded libcurl
handle, and resolve both `BrotliDecoderVersion` and
`BrotliDecoderDecompressStream`. Python `dladdr` and Node process-map checks
place the actual symbols in the verified private decoder. Its runtime version
is **16781313 / 1.1.1**, and libcurl reports `brotli/1.1.1`. Only the private
common/decoder libraries were mapped. Real seccomp TSYNC network denial was
installed before probing; the only curl operations were initialization and
cleanup. No HTTP transfer, model, license client or inference was started.

[Selected final loader proof](evaluations/2026-10-26-redact/security-brotli-2026-10-26/native-loader-preflight-final.json),
its supervisor receipt and the separate
[security manifest](evaluations/2026-10-26-redact/security-brotli-2026-10-26/manifest.json)
retain compiler commands, library/source hashes and resolved symbol addresses.
Nine Node and eight Python tooling tests pass, including missing-prefix,
unpatched-receipt, library-tampering, loader-path and interposition rejection.
No model benchmark was repeated after this remediation; historical performance
numbers must not be represented as measurements of the patched setup.

Sources: [Google fixed release](https://github.com/google/brotli/releases/tag/v1.1.1),
[SDK native shim](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Tools/curlcompat/dal_curl_compat.c),
[Swift 6.3.3 decompression configuration](https://github.com/swiftlang/swift-corelibs-foundation/blob/swift-6.3.3-RELEASE/Sources/FoundationNetworking/URLSession/libcurl/EasyHandle.swift#L337),
[libcurl encoding semantics](https://curl.se/libcurl/c/CURLOPT_ACCEPT_ENCODING.html).

## Reproduction after the web gate

Run only after parent confirmation. Use a task-private cache outside the repo;
profiles run sequentially. The parent must set
`OPENMATES_REDACT_EVALUATION_GO=web-trial-passed` explicitly.
Use a fresh result filename for each attempt; previous evidence is never replaced.
Build the private patched decoder explicitly first. It must remain present for
the mandatory per-process source/hash/version/address preflight:

```sh
python3 scripts/redact_brotli_guard.py --build --prefix /tmp/openmates-redact-678f-brotli-1.1.1
```

```sh
python3 scripts/redact_linux_evaluation.py --run --download --cores 1 --repeats 3 --timeout-seconds 600 \
  --brotli-prefix /tmp/openmates-redact-678f-brotli-1.1.1 \
  --directory /tmp/openmates-redact-678f-model \
  --output /tmp/redact-new-1core.json
python3 scripts/redact_linux_evaluation.py --run --cores 2 --repeats 3 --timeout-seconds 600 \
  --brotli-prefix /tmp/openmates-redact-678f-brotli-1.1.1 \
  --directory /tmp/openmates-redact-678f-model \
  --output /tmp/redact-new-2core.json
```

Omitting `--run` verifies existing assets and saves static metadata without SDK
import/load. Acquisition also requires the web gate. Preparation checks do not
import the SDK or perform inference:

```sh
node --test scripts/redact_linux_evaluation.test.mjs
python3 scripts/redact_linux_evaluation_test.py
```

Re-score retained raw predictions after a deterministic adapter change without
loading the SDK or running the model:

```sh
node --experimental-strip-types --loader ./frontend/packages/openmates-cli/tests/loader.mjs \
  scripts/redact_linux_evaluation.mjs --rescore \
  docs/architecture/privacy/evaluations/2026-10-26-redact/linux-arm64-1core-bounded.json \
  /tmp/redact-new-quality-rescore.json
```

## Measured resources and latency

The successful one-core profile took 327.9 seconds overall under its 600-second
ceiling. It completed 59 quality fixtures and 12 timed scans, with zero SDK
restoration failures, zero repeated label/offset drift and no invalid offsets.
The two-core supplement took 93.8 seconds for one long warm-up and three timed
scans, with zero repeated-output drift. No model/runtime failure was observed
beyond the two initial whole-profile watchdog terminations.

| One-core measurement | Result |
| --- | ---: |
| RSS before SDK load | 108,507,136 bytes |
| RSS after SDK load | 128,036,864 bytes |
| RSS after first classification | 176,533,504 bytes |
| Peak sampled process RSS | 191,217,664 bytes / 182.4 MiB |
| Model plus ARM64 native libraries | 87,201,250 bytes / 83.2 MiB |
| SDK load in a new process | 29.17 ms |
| Same-process SDK reload | 0.105 ms |
| First classification, 59 characters | 132.7 ms |

The load API returns before lazy inference initialization. Its small load time
must not be presented as end-to-end readiness; first-classification timing and
RSS are included separately. OS file caches were not flushed. The separate
two-core latency-only process peaked at 173,674,496 bytes / 165.6 MiB; its smaller
workload excludes the quality-fixture/result objects, so the memory difference
does not establish a CPU-count effect.

| Whitespace units | Characters | One-core n | One-core min / median / max, seconds | Two-core n | Two-core min / median / max, seconds |
| --- | ---: | ---: | --- | ---: | --- |
| 32 | 211 | 3 | 0.243 / 0.245 / 0.246 | 7 | 0.135 / 0.138 / 0.143 |
| 256 | 1,695 | 3 | 2.497 / 2.501 / 2.542 | 7 | 1.390 / 1.425 / 1.443 |
| 1,024 | 6,783 | 3 | 10.083 / 10.165 / 10.270 | 7 | 5.625 / 5.765 / 5.978 |
| 4,096 | 27,135 | 3 | 40.722 / 41.060 / 41.189 | 3 | 23.080 / 23.404 / 23.539 |

The three shorter two-core timing groups come from the completed groups in the
first two-core profile's progress receipt. That whole profile failed its wall
limit; its incomplete longest group is not claimed. The longest row comes from
the successful separate supplement. All inputs are identical between CPU
profiles at a given length; sample-count asymmetry is explicit.

## Detection quality and limitations

The table uses the original 56 cases, 50 expected values and 12 negative cases.
Three generated long-tail cases are scored separately. Native predictions were
retained from the complete one-core run. A deterministic rescore applies the
current web adapter to those exact predictions, without importing the SDK or
rerunning model inference. Both original and corrected adapter source hashes and
results remain retained.

| Variant | Strict complete value, /50 | All letters/digits/marks hidden, /50 | Negative cases changed, /12 |
| --- | ---: | ---: | ---: |
| Raw SDK default labels | 15 | 31 | 3 |
| SDK browser labels | 14 | 30 | 2 |
| Actual regex/validators | 20 | 20 | 0 |
| Browser-policy SDK + regex hybrid | 22 | 38 | 2 |
| Regex + configured private values | 23 | 23 | 0 |
| Hybrid + configured private values | 25 | 40 | 2 |

Strict totals include spaces and punctuation. Ten of thirteen names are split
into component spans: all name letters are hidden but separators remain visible;
one initials example also leaves a period. Six of seven addresses similarly hide
all letters/digits but leave component separators. These gaps are not reported
as exposed name/address letters. The contextual apartment/bakery address does
leave 16 letters/digits uncovered. Japanese and Arabic names are missed entirely.
The long-tail name and email letters are covered in all three lengths, including
the 69,706-character tail; strict coverage is 3/6 because the spaces between the
two name components remain visible. These are tail checks, not exact-tokenizer
window-boundary proof.

Raw SDK results cover all 6 emails, 5 phones and 2 account values in this set.
They cover none of the 15 secret fixtures or the private birth-date fixture.
The regex layer protects 8/15 secrets, increasing to 10/15 with fixture-configured
exact values. Unknown contextual secrets remain a material capability gap.

Raw SDK false positives occur on a public historical name, a public documentation
URL and a public landmark address. Browser URL policy removes the URL case;
public-name and public-address changes remain. The negative code/version, UUID,
hash, timestamp and placeholder fixtures remain unchanged. This is synthetic
coverage, not a population accuracy estimate.

The evaluation exposed a concrete merge defect: in `account-iban`, two regex
PHONE spans covered offsets 26–46 while the model's complete BANK_ACCOUNT span
covered 24–46. The old adapter discarded the complete model span, exposing two
alphanumeric characters. The corrected adapter retains the complete validated
bank-account mapping while preserving exclusions and mandatory secret/configured
matching. The saved pre-fix hybrid score is 21/50 strict and 37/50 letters/digits;
the corrected scores are 22/50 and 38/50. This correction is a deterministic
rescore of saved model predictions; browser integration verification belongs to
the parent web task.

## Historical comparison

Use the retained [2026-10-03 OpenAI Privacy Filter evaluation](offline-pii-evaluation-2026-10-03.md),
without downloading/rerunning its large models. Native Q8 was 1.53 GiB, with about
1.68 GiB RSS after load and 1.87 GiB peak through 4,096 actual tokenizer tokens.
Its two-core warm median was 0.166/0.647/2.701/10.671 seconds at
64/256/1,024/4,096 actual tokens (two samples each). Strict annotation coverage was
47/50; its broader sensitive-content metric was 48/50. These measurements used
the same host at an earlier date, with different software, length units and
conditions. They provide historical context, **not a controlled A/B comparison**
or directly comparable throughput ratio.
