---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/app.yml
  - backend/apps/ai/utils/model_selector.py
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/processing/main_processor.py
  - backend/providers/*.yml
  - backend/apps/ai/base_instructions.yml
---

# AI Model Selection

> Selects the optimal LLM for each request using leaderboard rankings, task analysis, and sensitivity filters, with tiered fallback across models and providers.

## Why This Exists

A single model cannot optimally serve all request types. Simple factual questions waste money on premium models; complex coding tasks need top-tier reasoning. The selection system matches request characteristics to model strengths while filtering out models that may be censored on sensitive topics.

## How It Works

### Configuration

Model selection is configured in [`backend/apps/ai/app.yml`](../../backend/apps/ai/app.yml) under `skill_config`:

- **`enable_auto_model_selection`**: When `true` (current default), uses intelligent leaderboard-based selection. When `false`, falls back to hardcoded `default_llms`.
- **`default_llms`**: Hardcoded model IDs for preprocessing, simple requests, complex requests, and content sanitization.
- **Current defaults**: Mistral Small (`mistral/mistral-small-2506`) for preprocessing, Qwen3 (`alibaba/qwen3-235b-a22b-2507`) for both simple and complex main processing.

### Provider YAML Structure

Each LLM provider has a YAML config in [`backend/providers/`](../../backend/providers/). Models define:

- **`country_origin`**: ISO 3166-1 alpha-2 code (used for China-sensitive filtering)
- **`allow_auto_select`**: Whether the model participates in auto-selection
- **`external_ids`**: Cross-platform ID mappings (LMArena, OpenRouter)
- **`default_server`** and **`servers`**: Provider routing (e.g., AWS Bedrock primary, direct API fallback)
- **`pricing`/`costs`**: Token pricing for billing

### Selection Flow

1. **User override check**: If the message contains `@ai-model:{model_id}`, that model is used directly, bypassing all selection logic. Other overrides: `@mate:{name}`, `@skill:{app}:{id}`, `@focus:{app}:{id}`.

2. **Preprocessing LLM analysis**: The preprocessor ([`preprocessor.py`](../../backend/apps/ai/processing/preprocessor.py)) runs a lightweight LLM call that returns:
   - `complexity` (simple/complex)
   - `task_area` (code, math, creative, instruction, general)
   - `user_unhappy` (boolean)
   - `china_model_sensitive` (boolean, detected by LLM -- replaces old hardcoded keyword approach)

3. **Model selection** ([`model_selector.py`](../../backend/apps/ai/utils/model_selector.py)):
   - Filters to models with `allow_auto_select: true`
   - Excludes CN-origin models if `china_model_sensitive` is true
   - For simple tasks: selects from economical models (e.g., Claude Haiku, Gemini Flash)
   - For complex tasks or unhappy users: selects premium models for the detected task area
   - Returns primary + secondary + fallback (3 models total)

4. **Main processing with fallback** ([`main_processor.py`](../../backend/apps/ai/processing/main_processor.py)):
   - Tries primary model first
   - On failure: tries secondary, then fallback
   - Each model may have multiple server providers (e.g., AWS Bedrock then direct API)

### China-Sensitive Content Handling

Chinese-origin models (Qwen, DeepSeek) may exhibit censorship on politically sensitive topics. The preprocessing LLM detects this via the `china_model_sensitive` field in [`base_instructions.yml`](../../backend/apps/ai/base_instructions.yml). When true, models with `country_origin: CN` are excluded from selection. Users can still explicitly request CN models via `@ai-model:` override.

### Leaderboard System

Daily scripts fetch rankings from external sources:

- [`fetch_lmarena_rankings.py`](../../backend/scripts/fetch_lmarena_rankings.py): ELO scores by category (coding, math, creative writing, etc.)
- [`fetch_openrouter_rankings.py`](../../backend/scripts/fetch_openrouter_rankings.py): Usage data, pricing, speed (TPS)

Rankings are aggregated into a leaderboard file loaded to cache on server startup. The `ModelSelector` class uses these rankings to determine the best model per task area.

### Fallback Strategy

Three tiers of fallback ensure reliability:

| Tier | Source | Example |
|------|--------|---------|
| Primary | Best ranked for task area | `alibaba/qwen3-235b-a22b-2507` |
| Secondary | Second-best ranked | `google/gemini-3.1-pro-preview` |
| Tertiary | Hardcoded reliable default | `anthropic/claude-sonnet-4-6` |

Each model tries its configured servers in order (e.g., Bedrock then direct API) before moving to the next tier.

## Edge Cases

- **All providers fail**: The `AllServersFailedError` exception propagates a standardized user-facing error message.
- **No auto-selectable models**: Falls back to `default_llms` from `app.yml`.
- **User override with invalid model**: Logs a warning and falls back to auto-selection.
- **Leaderboard data missing**: Uses hardcoded model rankings as fallback.

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- full request pipeline
- [Preprocessing Model Comparison](./preprocessing-model-comparison.md) -- benchmark data for preprocessing model choice
- [Thinking Models](./thinking-models.md) -- reasoning model support
