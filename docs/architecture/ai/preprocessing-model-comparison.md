---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/app.yml
  - backend/tests/test_model_comparison_mistral_vs_ministral.py
  - backend/providers/mistral.yml
---

# Preprocessing Model Comparison Report

> Benchmark comparison of Mistral models for preprocessing/postprocessing, concluding that Mistral Small is the optimal choice.

## Why This Exists

The preprocessing and postprocessing stages run a lightweight LLM call on every request. Choosing the right model here directly impacts latency, cost, and quality of intent classification, skill selection, and user sentiment detection. This report documents the evaluation.

## Test Summary

**Test date**: 2026-02-02
**Test suite**: 23 test cases (20 preprocessing, 3 postprocessing) covering factual queries, complex reasoning, code, safety/moderation, skill selection, follow-up detection, user unhappiness, edge cases, and multilingual input.

**Run command**: `docker exec api python /app/backend/tests/test_model_comparison_mistral_vs_ministral.py --iterations 1`

## Results

### Mistral Small 3.2 (24B) vs Ministral 8B

| Metric | Mistral Small 3.2 | Ministral 8B | Winner |
|--------|-------------------|--------------|--------|
| Success Rate | 100% | 100% | Tie |
| Avg Latency | 1,671ms | 3,079ms | Mistral Small (1.8x faster) |
| Total Cost (23 tests) | $0.0086 | $0.0118 | Mistral Small (27% cheaper) |
| Validation Accuracy | 100% | 100% | Tie |

### Mistral Small 3.2 (24B) vs Ministral 3B

| Metric | Mistral Small 3.2 | Ministral 3B | Winner |
|--------|-------------------|--------------|--------|
| Success Rate | 100% | 100% | Tie |
| Avg Latency | 1,779ms | 918ms | Ministral 3B (1.9x faster) |
| Total Cost (23 tests) | $0.0086 | $0.0079 | Ministral 3B (8% cheaper) |

**Quality failures in Ministral 3B**:
- `skill_web_search`: Failed to identify web search skill should be used (critical)
- `user_unhappy_1`: Failed to detect user frustration (affects model escalation)

### Cost at Scale (per 1M requests)

| Model | Projected Cost |
|-------|---------------|
| Mistral Small 3.2 | $374.20 (baseline) |
| Ministral 8B | $544.53 (+45%) |
| Ministral 3B | $343.45 (-8%) |

## Recommendation

**Continue using Mistral Small** (currently `mistral/mistral-small-2506` in [`app.yml`](../../backend/apps/ai/app.yml)).

- 100% validation accuracy on all critical checks
- Faster and cheaper than Ministral 8B
- Only 8% more expensive than 3B, but without skill selection and sentiment detection failures
- ~1.5-1.8s average latency is acceptable for preprocessing

## Related Docs

- [AI Model Selection](./ai-model-selection.md) -- how the preprocessing model fits into the pipeline
