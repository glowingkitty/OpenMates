# GLiNER2.5-Decide before OpenAI Privacy Filter

Date: 2026-10-03. Task: TASK-900. Session: 8c51.

**Memory permits this cascade on the current dev server, but the measured gate
does not justify its cost.** It increases disk and RAM, takes longer than the
optimized OpenAI detector, and can suppress detections that OpenAI would find.
Conservative routing recovers detection quality by forwarding almost everything,
without removing the gate's latency. Neither model is activated in OpenMates.

## Scope and method

The requested model is [Fastino GLiNER2.5-Decide](https://huggingface.co/fastino/GLiNER2.5-Decide),
an English decision classifier advertised as 340M parameters. The downloaded
checkpoint has 486,444,053 parameters including its embeddings. This evaluation
uses the specific Decide checkpoint, rather than substituting a smaller general
GLiNER model. The [official library](https://github.com/fastino-ai/GLiNER2) supports
label descriptions and classification confidence; a negative decision is not a
guarantee that text contains no PII.

The same synthetic set as the [OpenAI evaluation](offline-pii-evaluation-2026-10-03.md)
contains 56 inputs, 44 sensitive inputs, 50 annotated sensitive values, and 12
negative coding/public-information cases. Names, addresses, phones, emails,
contextual credentials, vendor-shaped secrets, JSON, code, logs and multilingual
examples are included. No real Project or account data was scanned.
OpenAI's token classifier runs through the pinned third-party
[LocalAI C++ Q8 runtime](https://github.com/localai-org/privacy-filter.cpp), rather
than OpenAI's reference PyTorch runtime. GLiNER uses its official PyTorch library.

The gate receives two described labels: `sensitive_information` and
`ordinary_content`. All text is scanned in 256 GLiNER-subword windows with
32-subword overlap. Any sensitive window routes the input to OpenAI. Two more
conservative policies also route an input if any ordinary decision has confidence
below 0.8 or 0.9. Those thresholds are illustrative and **not calibrated privacy
probabilities**. The library's long-text confidence-winning merge is not used;
it could let a confident negative outweigh a sensitive window.

Runs used four CPU cores on the 16-core ARM Neoverse-N1 Linux dev server, which has
30.54 GiB total RAM and initially about 15.13 GiB available. Each profile ran
sequentially, with CPU affinity, lower priority, an 8 GiB RSS watchdog and a
process-local seccomp network denial. No GPU or shared service was changed.
Results establish this host's feasibility, not population accuracy or production
latency percentiles.

## Disk and RAM

| Measurement | GLiNER float32 + OpenAI Q8 | Experimental GLiNER int8 + OpenAI Q8 |
| --- | ---: | ---: |
| GLiNER checkpoint | 1.81 GiB | Same original checkpoint retained |
| OpenAI Q8 checkpoint | 1.53 GiB | 1.53 GiB |
| Both weight files | **3.34 GiB** | **3.34 GiB** |
| GLiNER Python environment, logical footprint | Approximately 0.64 GiB | Same environment |
| Gate RAM immediately after loading | 2.23 GiB | 1.64 GiB |
| Gate RAM after short scans | 2.29 GiB | 1.82 GiB |
| Both models resident after short scans | **3.83 GiB** | **3.36 GiB** |
| Peak process RSS, including startup | **4.09 GiB** | **4.03 GiB** |
| RAM after releasing OpenAI and trimming the allocator | 2.32 GiB | 1.63 GiB |
| Gate load from a new process, normal OS file cache | 12.87 s | 12.93 s + 0.51 s quantization |
| OpenAI load while gate is present | 2.09 s | 2.09 s |

The previous OpenAI-only native worker used about 1.87 GiB peak RAM. Adding this
gate therefore roughly doubles warm memory in the float32 case. An 8 GB dedicated
VM with at least 5 GiB available for the process could accommodate the measured
cascade; a 4 GB total VM has inadequate startup headroom. This is sizing inferred
from process measurements, not a separate small-VM test. Builds and other services
need additional RAM. Approximately 4 GiB installed disk, including the Python
runtime, and about 8 GiB free for safe model replacement are reasonable budgets.

The int8 variant dynamically quantizes Linear layers with PyTorch 2.8/QNNPACK;
embeddings remain float32. It is an experimental CPU variant, not the library's
`quantize=True` option, which uses FP16. It loads the original checkpoint before
quantization, so it saves resident memory but **does not save checkpoint storage
or remove the startup peak**. PyTorch also emits quantization deprecation and
QNNPACK range warnings; this is not a ready production packaging path.

The isolated evaluation environment uses uv hardlinks to shared dependency cache.
Its logical size is the reproducible installation footprint, not newly allocated
disk on this host. Neither downloaded weights nor the environment are committed.

## Speed: the gate is more expensive than what it skips

Times below exclude startup. Short-case medians time inference; tokenization and
queueing would add further cost. Long inputs scan every window, including the
tail. The long synthetic code sample is about 10 KB and 2,048 OpenAI tokens
(2,842 GLiNER subwords), requiring 13 overlapping gate windows.

| Input | GLiNER float32 gate | GLiNER int8 gate | OpenAI native Q8 directly |
| --- | ---: | ---: | ---: |
| Short fixture, median | 1.13 s | 1.80 s | 0.028–0.033 s |
| Clean 10 KB code sample | 36.92 s | 52.04 s | 2.73–2.76 s |
| Same code with customer name/address at the tail | 41.36 s | 50.68 s | 2.89–2.91 s |

For a forwarded file, the two times add. The float32 tail example therefore takes
about 44.3 seconds through the cascade, versus 2.9 seconds directly. A clean file
still incurs the whole gate scan before it can be skipped. A safe negative result
requires inspecting the full input; sampling only the beginning would miss the
tested tail content.

With positive routing fraction `p`, warm average cost is
`gate_time + p * OpenAI_time`. It improves speed only if
`gate_time < (1 - p) * OpenAI_time`. On this host, the gate alone already exceeds
direct OpenAI time on both tested short and long inputs, even if it forwards none.
Other hardware or a different optimized gate runtime could behave differently;
these results do not establish a universal comparison.

## Quality and concrete failures

Existing regex and configured private-value matching must always run regardless
of the gate. The final column below includes those existing detections. It counts
covered sensitive content, using the same address-separator rule as the earlier
evaluation; it is not a claim of perfect boundaries or correct labels.

| Policy | Forwarded inputs / 56 | Sensitive inputs incorrectly skipped / 44 | Protected values with existing configured detection / 50 |
| --- | ---: | ---: | ---: |
| OpenAI directly, no gate | 56 | 0 gate skips | **49** |
| Float32, ordinary yes/no decision | 28 | **17** | **43** |
| Float32, also forward uncertainty below 0.8 | 46 | 1 | 49 |
| Float32, also forward uncertainty below 0.9 | 53 | 0 in this set | 49 |
| Int8, ordinary yes/no decision | 34 | **11** | **44** |
| Int8, also forward uncertainty below 0.8 | 53 | 0 in this set | 49 |
| Int8, also forward uncertainty below 0.9 | 56 | 0 in this set | 49 |

Without existing deterministic detections, direct OpenAI covers 48 values, versus
31 through the strict float32 gate and 37 through the strict int8 gate. This is
why comparing only gate accuracy or saved model calls would be misleading.

Examples, all synthetic:

- `My colleague Niamh cannot sign in. Please help her.`: float32 labels it
  ordinary, confidence 0.577, so its normal rule skips a name OpenAI detects.
- `{"shippingAddress":"19 Oak Road, Cambridge CB1 2AB"}`: float32 labels it
  ordinary, confidence 0.518; direct OpenAI detects the address.
- `I live in apartment 8 above the bakery on Willow Street.`: float32 labels it
  ordinary, confidence 0.581, despite the residential-address context.
- Four phone fixtures and several credential fixtures are skipped by the strict
  float32 gate. Regex rescues recognizable formats, but cannot rescue all
  unfamiliar names, addresses or contextual credentials.
- A name and address at the end of the 10 KB code file route correctly in
  float32. Int8 labels every window ordinary and skips both under its normal
  rule. Its uncertain last-window score of 0.601 causes the conservative rule
  to forward the file instead.
- A separate name crossing the first 256-subword boundary routes correctly when
  overlapping windows are combined by OR. This is one boundary check, not a
  general long-document guarantee.

Float32's 0.8 policy skips one sensitive input: an unknown bare secret which
OpenAI also misses, but configured-value matching covers. At 0.9, only three short
inputs avoid OpenAI. Every clean long-file window has ordinary confidence below
0.9, so that conservative policy forwards the entire clean file too. The int8
0.9 policy forwards all 56 short cases. Quantization changes decisions and must
be revalidated separately.

## Recommendation and implementation implications

Do not add this two-model gate to the default CLI privacy path. Preserve the
deterministic detector and encrypted configured values for all outgoing content.
Pilot OpenAI's persistent local native worker selectively for short messages,
optional documents and explicitly selected sensitive Project excerpts. Cache
unchanged content by digest, detector version and settings; edits invalidate it.

If the cascade were ever used, one shared local worker should serve chats, rather
than duplicating models per chat. Keeping both warm costs the memory in the table.
Loading OpenAI only after a positive gate saves idle resident memory, but each
new worker adds approximately two seconds and still needs memory for both during
the scan. Process exit releases memory reliably; repeatedly loading a model is
not suitable for a busy coding loop. Loading the gate only on demand adds about
13 seconds before any text is classified.

These classifiers remain fallible. A negative prediction must not be treated as
authorization to silently bypass a selected stronger privacy policy. All model
work must stay on the authorized client executor; sending plaintext to the
OpenMates server for the gate would break the existing privacy boundary.

## Reproduce and inspect

The pinned source, weights, packages, policies, score summaries and resource
measurements are in [manifest.json](evaluations/2026-10-03-gliner-gate/manifest.json).
Per-window decisions and native detected ranges are in the adjacent `float32.json`,
`int8.json` and `boundary.json`. Literal credential fixtures are not copied into
these results. The retained synthetic fixture uses split strings for vendor-shaped
test keys; they assemble only during the offline evaluation.

Run `scripts/privacy_gate_evaluation.py --help` for required local checkpoint,
library, fixture, baseline and output paths. Use `--profile float32` or `int8`,
`--threads 4 --long-tokens 2048`; run the additional narrow boundary check with
`--boundary-only`. Prepare the pinned dependencies and checkpoint separately;
the harness does not download anything or activate a product detector.

Verification: both complete offline profiles, one overlap-boundary case, Python
compilation, full-text window coverage checks and whitespace validation. Product
CI is not applicable to this synthetic local-inference evaluation; no product
behavior or UI was changed.
