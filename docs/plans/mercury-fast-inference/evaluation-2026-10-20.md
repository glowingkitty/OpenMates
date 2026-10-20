# Mercury 3 evaluation — 2026-10-20

**Decision: preserve current Gemini defaults.** The direct Inception integration
is implemented, but usable Mercury capacity prevented the paired quality/speed
benchmark. Mercury merits a low-complexity pilot once capacity is available;
there is no basis yet for replacing Gemini on medium-complexity requests or
workflow authoring. Mercury transcript correction remains disabled behind its
enablement flag; existing Gemini correction remains active. No account,
chat-model or automatic-routing defaults were changed.

## Implemented and published to dev

- Direct Inception text, tools, structured output, streaming and usage adapter;
  Vault-first credentials; bounded transient retry with Retry-After support.
- Ordinary batch/realtime transcript correction behind
  `INCEPTION_TRANSCRIPT_CORRECTION_ENABLED`, with a five-second Mercury deadline,
  zero correction retries and the existing Gemini fallback. Original transcript
  timestamp/sanitization behavior and actual-model attribution are preserved.
- Mercury's product server is **direct Inception only**. OpenRouter is allowed
  solely for the user's synthetic benchmark, pinned to Inception without
  provider fallbacks. It is not a product Mercury route.
- Existing `temporary_prices` passes the launch discount to customer credits:
  **3,300 input / 950 output tokens per credit**, versus regular 1,650 / 475.
  Supplier launch prices are **$0.10 / $0.35 per million input/output tokens**
  and $0.01 cached input, versus regular $0.20 / $0.70 / $0.02. No published
  promotion expiry was established; the dated entry can be retired when it ends.

Integration/pricing source: `1891f7aa7700b9998b36530ba6121e839968f53e`.
Benchmark-only gateway source and runtime:
`9cc5ec1d273d7efded6ab2e0b4469bbe3d4a7802`.
API image: `sha256:6161df56fb6801d796e05c263a84aa8d8efa93358fc11f70b87bab92663e4a1f`.
Both coordinated backend refreshes finished with healthy services.

## What live requests actually established

| Probe | Result | Interpretation |
| --- | --- | --- |
| Initial direct `mercury-3` text probe | HTTP 200, `API_ACCESS_OK`, 1.255 s | Credentials and basic generation work; one response is not a capacity or quality benchmark. |
| Subsequent direct forced-tool requests | HTTP 429, shared free-tier capacity message | No completed output or model-quality measurement. |
| Initial synthetic OpenRouter forced-tool probe | HTTP 200, Inception / `inception/mercury-3`, 0.604 s, correct small tool arguments | Confirms one gateway generation, not representative workload performance or direct latency. |
| Deployed gateway transcript smoke, reasoning `none` and `low` | Both HTTP 429 | Neither profile produced a correction. Rejection times are not answer latency. |
| Diagnostic gateway request | HTTP 429; provider Inception, temporarily rate-limited upstream | The failure is upstream capacity, not a schema-quality result. |
| One bounded gateway `low` retry after backoff | HTTP 429 | Stop further Mercury calls rather than accumulate failed requests. |
| Same deployed transcript smoke, Gemini 3.8 low | Completed and passed finite constraints, 2.219 s | One successful case, not a latency distribution. |
| Same smoke, existing Gemini 3.5 model/prompt over streaming measurement transport | Completed and passed finite constraints, 2.808 s | One successful case, not production-path latency; production Gemini correction is nonstreaming. |

The completed initial gateway probe reported $0.00005984 usage cost. Failed
Mercury requests reported no usage/cost; their costs are **unknown**, not zero.
There are no Mercury workload pass rates, median/p95 task latencies, workflow
reliability scores or measured per-task savings to publish yet. The full matrices
were not run after the smoke/backoff failed. Gateway availability also does not
guarantee that a direct paid-account upgrade resolves the observed limitation.

Private synthetic receipts remain outside source control:
`/tmp/mercury-acad-gateway-smoke.json`,
`/tmp/mercury-acad-gateway-backoff.json` and
`/tmp/mercury-acad-smoke-runtime.json` on the dev host. The earlier direct smoke
is retained separately as `/tmp/mercury-acad-smoke.json`.

## Public evidence and routing recommendation

See [the cited public-benchmark comparison](public-benchmarks.md). Artificial
Analysis's exact Gemini 3.8 Flash configurations score 33 (low reasoning), 40
(medium) and 41 (high) on Intelligence Index v4.3.2; no matched Mercury 3 result
was verified. Inception's medium-reasoning vendor chart includes Haiku 5.5 and
GPT-6 Luna, without Gemini. Mercury wins selected rows, while Haiku leads DeepSWE
v1 and MRCR v2. Its 1,068 tokens/s claim is throughput, not end-to-end task latency.
Cross-operator GPQA results use different effort/settings and do not settle parity.

| Use case | Recommendation now | Evidence needed before switching |
| --- | --- | --- |
| Low-complexity text transformations and short generation | Candidate for a bounded Mercury pilot; keep current defaults | Paired quality, usable capacity and complete-task latency/cost. |
| Transcript correction/title | Implementation ready; gate remains off | Preservation of names, numbers, negation, language and self-corrections; usable direct API; production-helper smoke. |
| Medium-complexity general requests | Keep Gemini | Representative multi-step/tool/reasoning evaluation; public results are not a matched head-to-head. |
| AI workflow authoring | Keep Gemini 3.8 Flash | Compiled graph validity **and** intent fidelity, including branching, schedules, references, batches and safe updates; retry-inclusive cost/latency. |
| Decision-only tasks | Keep existing decision provider | No generative model substitution is required by this evaluation. |

Reasoning effort `medium` is distinct from an OpenMates complexity tier. A
successful low-effort short-text pilot would not authorize a blanket medium-tier
replacement. Current Mercury automatic selection remains disabled.

## Reproducible next benchmark

The published harness preserves identical prompts and native logical schemas,
rotates arm order, and uses synthetic data without workflow/account writes.
Gateway payloads specify `only: [inception]`, `allow_fallbacks: false`,
`require_parameters: true`, `data_collection: deny`. Timing includes gateway
transit and excludes ASR, persistence and UI. Fast-suite credentials are loaded
before timing; workflow author timing can include Gemini credential lookup.
Reports identify transport
and observed provider/model, token usage and gateway-reported cost separately
from uncached price estimates. Missing usage remains incomplete.

Once the smoke succeeds, run under the coordinated dev runtime read lease:

```sh
python -m backend.scripts.benchmark_fast_inference --allow-paid-dev-inference \
  --revision <deployed-revision> --repeats 2 \
  --arms gemini-3.5 gemini-3.8-low mercury-openrouter-none mercury-openrouter-low \
  --output /tmp/mercury-fast-results.json
python -m backend.scripts.benchmark_workflow_authoring_models --allow-paid-dev-inference \
  --revision <deployed-revision> --repeats 2 \
  --arms gemini mercury-openrouter-none mercury-openrouter-low \
  --output /tmp/mercury-workflow-results.json
```

Fast suite: six multilingual transcript cases plus three bounded writing tasks,
two repeats per arm. Workflow suite: eight requests, two repeats per arm, common
measured Jev preselection, production parser/compiler/retry loop and independent
semantic constraints. Manually review retained outputs without weakening the
oracle. Sum all author attempts for cost; keep shared Jev cost separate. Small
synthetic samples cannot establish production p95 or broad quality guarantees.

Verification completed: 31 focused benchmark tests; 29 direct-provider/metadata
tests; focused Ruff and diff checks. Prior audio UI CI had 13 passing cases,
with the correction insertion case passing on its first retry. That mocked
provider UI evidence verifies protocol compatibility, not Mercury inference.
The owner explicitly confirmed that “Improve the model for everyone” is OFF
for the direct Inception API account.
