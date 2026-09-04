---
status: active
last_verified: 2026-09-03
---

# Cerebras Qwen 3.8 27B Evaluation

## Catalog

OpenMates exposes `alibaba/qwen-3.8-27b` as a Cerebras-primary, low-capability,
explicit-selection-only `ai.ask` model. The `@fast` alias remains mapped to
`alibaba/qwen3-235b-a22b-2507` until a stronger comparison supports changing it.

Official Cerebras documentation lists `qwen-3.8-27b` at approximately 1,500
tokens/second, with 128k paid context, 40k paid maximum output, and developer
pricing of $0.99/M input and $1.49/M output tokens. It supports streaming,
tool calling, structured output, reasoning controls, and image input.

Sources checked 2026-09-03:

- https://inference-docs.cerebras.ai/models/qwen-3.8-27b
- https://inference-docs.cerebras.ai/models/overview
- https://openrouter.ai/qwen/qwen3.8-27b

## Real Product-Path Benchmark

The benchmark used the deployed OpenMates CLI, the `quick-code` real-life
TypeScript task, and `--parallel 1` to avoid cross-model attribution problems.
The OpenMates benchmark judge failed for the candidate, so the deterministic
task result and observed duration are the reliable quality signals here.

| Model | Run | Duration | Deterministic result | Judge |
|---|---|---:|---|---|
| Cerebras Qwen 3.8 27B | `548ac951-47ea-4b6d-a121-a3931e622923` | 23.6s | Failed: returned an embed reference instead of code | unavailable |
| Current @fast Qwen 3 256B | `be7ac101-2cf9-458d-a541-8303eb3efa25` | 19.1s | Passed | 5/5 |

The earlier two-model parallel run (`c6088de1-ed43-46b0-92a2-9d9f340ab839`)
is retained as an operational finding only: model output attribution became
ambiguous, so it is not used for the decision.

## Recommendation

Do not replace `@fast` yet. In this product-path sample, Qwen 3.8 27B was
approximately 23% slower end-to-end and failed the requested code-output
contract, while the current Qwen 3 256B passed and was faster. Qwen 3.8 27B is
available for explicit testing and should be re-evaluated with a larger,
sequential suite after the benchmark judge and embed-output handling are stable.
