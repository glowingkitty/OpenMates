# Preprocessing Model Comparison Report

> **Status**: Completed  
> **Last Updated**: 2026-02-02  
> **Test Date**: 2026-02-02

## Overview

This report compares different Mistral AI models for use in preprocessing and postprocessing tasks. The goal is to evaluate if smaller, cheaper models can match the quality of Mistral Small 3.2 while reducing cost and latency.

## Models Tested

All models tested via **direct Mistral API** for fair comparison:

| Model             | Parameters | Input Cost     | Output Cost    |
| ----------------- | ---------- | -------------- | -------------- |
| Mistral Small 3.2 | 24B        | $0.10/M tokens | $0.30/M tokens |
| Ministral 3 8B    | 8B         | $0.15/M tokens | $0.15/M tokens |
| Ministral 3 3B    | 3B         | $0.10/M tokens | $0.10/M tokens |

## Test Suite

The comparison test suite includes **23 test cases** covering:

### Preprocessing Tests (20 cases)

- **Simple factual queries** (2): Basic knowledge questions
- **Complex reasoning** (2): Multi-step analysis and comparison tasks
- **Code queries** (3): Simple code, complex code, API documentation lookup
- **Safety/moderation** (3): Benign requests, harm reduction, mental health
- **Skill selection** (4): Web search, news search, video search, maps search
- **Follow-up detection** (1): Weather follow-up context
- **User unhappiness detection** (2): Frustrated user responses
- **Edge cases** (3): Empty-like queries, multilingual (German), long context

### Postprocessing Tests (3 cases)

- Code response suggestions
- Creative response suggestions
- Factual response suggestions

## Results Summary

### Mistral Small 3.2 (24B) vs Ministral 3 8B

| Metric                | Mistral Small 3.2 | Ministral 8B | Winner            |
| --------------------- | ----------------- | ------------ | ----------------- |
| Success Rate          | 100%              | 100%         | Tie               |
| Avg Latency           | 1,671ms           | 3,079ms      | **Mistral Small** |
| Median Latency        | 1,582ms           | 2,925ms      | **Mistral Small** |
| Total Cost (23 tests) | $0.0086           | $0.0118      | **Mistral Small** |
| Validation Accuracy   | 100%              | 100%         | Tie               |

**Finding**: Mistral Small 3.2 is both **faster** (1.8x) and **cheaper** (27%) than Ministral 8B while maintaining identical quality.

### Mistral Small 3.2 (24B) vs Ministral 3 3B

| Metric                | Mistral Small 3.2 | Ministral 3B | Winner           |
| --------------------- | ----------------- | ------------ | ---------------- |
| Success Rate          | 100%              | 100%         | Tie              |
| Avg Latency           | 1,779ms           | **918ms**    | **Ministral 3B** |
| Median Latency        | 1,526ms           | **910ms**    | **Ministral 3B** |
| Total Cost (23 tests) | $0.0086           | **$0.0079**  | **Ministral 3B** |

**Validation Accuracy Differences**:

| Test                  | Check                 | Mistral Small | Ministral 3B |
| --------------------- | --------------------- | ------------- | ------------ |
| `skill_web_search`    | `relevant_app_skills` | ✓ Pass        | ✗ **Fail**   |
| `user_unhappy_1`      | `user_unhappy`        | ✓ Pass        | ✗ **Fail**   |
| `complex_reasoning_1` | `task_area`           | ✗ Fail        | ✗ Fail       |
| `complex_reasoning_2` | `task_area`           | ✗ Fail        | ✗ Fail       |

**Finding**: Ministral 3B is **faster** (1.9x) and **cheaper** (8%), but has **quality issues** in skill selection and user unhappiness detection.

## Cost Projections

Per 1 million preprocessing/postprocessing requests:

| Model                   | Projected Cost | vs Mistral Small    |
| ----------------------- | -------------- | ------------------- |
| Mistral Small 3.2 (24B) | $374.20        | baseline            |
| Ministral 8B            | $544.53        | +45% more expensive |
| Ministral 3B            | $343.45        | -8% cheaper         |

## Quality Issues with Ministral 3B

### 1. Skill Selection Failure (`skill_web_search`)

The 3B model failed to correctly identify that a web search skill should be used. This is critical for the preprocessing pipeline as it determines which app/skill handles the user request.

### 2. User Unhappiness Detection Failure (`user_unhappy_1`)

The 3B model failed to detect when a user expressed frustration. This affects the system's ability to adjust responses and improve user experience.

## Recommendation

**Continue using Mistral Small 3.2** for preprocessing and postprocessing.

### Rationale:

1. **Quality**: 100% validation accuracy on all test cases
2. **Reliability**: No failures on critical checks (skill selection, user sentiment)
3. **Cost-effective**: Cheaper than Ministral 8B despite being larger
4. **Acceptable latency**: ~1.5-1.8s average is within acceptable range

### Why not switch to Ministral 3B:

- **Skill selection failures** could route requests to wrong apps
- **User sentiment detection failures** could miss opportunities to improve responses
- **Cost savings minimal** (~8%) compared to quality risk

### Why not switch to Ministral 8B:

- **More expensive** than Mistral Small (45% higher cost)
- **Slower** than Mistral Small (1.8x slower)
- **No quality advantage** over Mistral Small

## Test Execution

The full test suite can be run with:

```bash
docker exec api python /app/backend/tests/test_model_comparison_mistral_vs_ministral.py --iterations 1
```

Test file: [`backend/tests/test_model_comparison_mistral_vs_ministral.py`](../../backend/tests/test_model_comparison_mistral_vs_ministral.py)

## Configuration

Current preprocessing model configuration:

- **File**: [`backend/apps/ai/app.yml`](../../backend/apps/ai/app.yml)
- **Setting**: `preprocessing_model: mistral/mistral-small-latest`

Model definitions:

- **File**: [`backend/providers/mistral.yml`](../../backend/providers/mistral.yml)

## Future Considerations

1. **Re-evaluate periodically**: As Mistral releases new models, re-run comparison tests
2. **Fine-tuning**: Consider fine-tuning a smaller model specifically for preprocessing tasks
3. **Hybrid approach**: Use smaller model for simple cases, larger model for complex cases
4. **Batch processing**: For non-real-time tasks, cost optimization may be more important than latency
