# AI Model Selection Architecture

> **Status**: ✅ Implemented
> **Last Updated**: 2026-01-30

## Overview

This document describes the architecture for AI model selection in OpenMates, including provider configuration and the automatic selection system.

---

## Current Implementation

### Provider Configuration

Under `/backend/providers/` each LLM provider (the creator of the model, not the server provider) has their own `.yml` file, with an overview of all available models, their costs, and optional server options (including server options like AWS Bedrock, Azure AI, OpenRouter). By default the API from the provider itself will be used, unless a model's `default_server` is set to another server. For example, Claude 3.7 Sonnet is configured to use AWS Bedrock by default.

Under `/backend/apps/ai/llm_providers` we have the scripts for the APIs for each provider and for optional server options.

Under `/backend/apps/ai/app.yml` we define the default LLM models for simple requests and complex requests, as well as the harmful content detection threshold.

### Default Models (Current)

| Request Type | Model | Server |
|-------------|-------|--------|
| Simple requests | Mistral Medium 3 | Mistral API |
| Complex requests | Claude 3.7 Sonnet | AWS Bedrock |

---

## Safety Controls and Gradual Rollout

The auto-selection system includes safety controls for gradual rollout of new models:

### Global Toggle: `enable_auto_model_selection`

Located in `backend/apps/ai/app.yml`:

```yaml
skill_config:
  # When false: uses hardcoded models from default_llms (safe, predictable)
  # When true: uses intelligent auto-selection based on leaderboard rankings
  enable_auto_model_selection: false

  default_llms:
    preprocessing_model: mistral/mistral-small-latest
    main_processing_simple: alibaba/qwen3-235b-a22b-2507
    main_processing_complex: alibaba/qwen3-235b-a22b-2507
    content_sanitization_model: openai/gpt-oss-safeguard-20b
```

### Per-Model Toggle: `allow_auto_select`

Each model in provider YAMLs has an `allow_auto_select` flag:

```yaml
# backend/providers/anthropic.yml
models:
  - id: "claude-sonnet-4-5-20250929"
    name: "Claude Sonnet 4.5"
    country_origin: "US"
    allow_auto_select: false  # Enable after manual testing
    external_ids:
      lmarena: "claude-sonnet-4-5-20250929"
      openrouter: "anthropic/claude-sonnet-4-5-20250929"
```

When `allow_auto_select: false`:
- Model is excluded from automatic selection
- Model can still be used via explicit `@ai-model:xxx` override
- Allows testing individual models before enabling auto-selection

### Testing Workflow

1. **Test models individually**: Use `@ai-model:{model_id}` in the web app to test each model
2. **Enable per-model**: Set `allow_auto_select: true` in the provider YAML after confirming the model works
3. **Enable global**: Set `enable_auto_model_selection: true` in `app.yml` once enough models are tested

### Configuration States

| `enable_auto_model_selection` | `allow_auto_select` on models | Behavior |
|------------------------------|-------------------------------|----------|
| `false` | Any | Uses hardcoded `default_llms` from app.yml |
| `true` | All `false` | Falls back to default model (no auto-selectable models) |
| `true` | Some `true` | Auto-selects from models with `allow_auto_select: true` |

---

## Automatic Model Selection

### Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DAILY LEADERBOARD UPDATE                            │
│                                                                             │
│   ┌────────────────┐   ┌────────────────┐   ┌────────────────┐             │
│   │   LM Arena     │   │   OpenRouter   │   │   SimpleBench  │             │
│   │   (ELO, cats)  │   │   (usage, $)   │   │   (reasoning)  │             │
│   └───────┬────────┘   └───────┬────────┘   └───────┬────────┘             │
│           └────────────────────┼────────────────────┘                       │
│                                ▼                                            │
│                  ┌─────────────────────────────┐                            │
│                  │  Leaderboard Aggregator     │                            │
│                  │  (deterministic script)     │                            │
│                  │  - Normalizes scores        │                            │
│                  │  - Maps model IDs           │                            │
│                  │  - LLM only for new models  │                            │
│                  └─────────────┬───────────────┘                            │
│                                ▼                                            │
│                  ┌─────────────────────────────┐                            │
│                  │  models_leaderboard.yml     │  → Loaded to cache on      │
│                  │  (aggregated rankings)      │    server startup          │
│                  └─────────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                         REQUEST PROCESSING FLOW                             │
│                                                                             │
│   User Message                                                              │
│        │                                                                    │
│        ▼                                                                    │
│   ┌─────────────────────────────────────────────────┐                       │
│   │  Check for User Overrides (@ai-model:xxx)       │                       │
│   │  - @ai-model:{model_id}                         │                       │
│   │  - @mate:{mate_name}                            │                       │
│   │  - @skill:{app}:{skill_id}                      │                       │
│   │  - @focus:{app}:{focus_mode_id}                 │                       │
│   └──────────────────────┬──────────────────────────┘                       │
│                          │                                                  │
│          ┌───────────────┴───────────────┐                                  │
│          │                               │                                  │
│          ▼ (override found)              ▼ (no override)                    │
│   ┌──────────────────┐           ┌──────────────────────────┐               │
│   │ Use specified    │           │ China Keyword Check      │               │
│   │ model directly   │           │ (hardcoded terms list)   │               │
│   │ (skip selection) │           │ → china_related: bool    │               │
│   └──────────────────┘           └────────────┬─────────────┘               │
│                                               │                             │
│                                               ▼                             │
│                                  ┌──────────────────────────┐               │
│                                  │ Pre-processor (LLM)      │               │
│                                  │ - Intent classification  │               │
│                                  │ - Task complexity        │               │
│                                  │ - Task area detection    │               │
│                                  │ - User sentiment check   │               │
│                                  │ - Model selection        │               │
│                                  │   → Returns top 2 models │               │
│                                  └────────────┬─────────────┘               │
│                                               │                             │
│                                               ▼                             │
│                                  ┌──────────────────────────┐               │
│                                  │ Model Selection Logic    │               │
│                                  │ - Filter CN origin models│               │
│                                  │   if china_related=true  │               │
│                                  │ - Add hardcoded fallback │               │
│                                  │   (if different from 1&2)│               │
│                                  │ → Final: [m1, m2, m3]    │               │
│                                  └────────────┬─────────────┘               │
│                                               │                             │
│                                               ▼                             │
│                                  ┌──────────────────────────┐               │
│                                  │ Main Processor           │               │
│                                  │ - Try model 1            │               │
│                                  │ - On failure: try m2     │               │
│                                  │ - On failure: try m3     │               │
│                                  └──────────────────────────┘               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### Model Selection Criteria

#### Selection Strategy

```text
IF user specified @ai-model:{model_name}
   → Use that model directly (bypass all selection logic)

ELSE IF enable_auto_model_selection = false
   → Use hardcoded models from default_llms in app.yml

ELSE (auto-selection enabled)
   1. Filter to models with allow_auto_select = true
   2. Filter out models with country_origin=CN IF china_related = true
   3. IF simple task → Select fast + economical model
      ELSE IF complex task OR user_unhappy
        → Select leading model for detected task_area
           (code → top coding model)
           (math → top math/reasoning model)
           (creative → top creative writing model)
           (general → top overall model)
   4. RETURN top 2 models + hardcoded fallback (if different)
```

#### Task Complexity

| Complexity | Criteria | Model Type |
|------------|----------|------------|
| Simple | Quick factual questions, simple translations, basic formatting | Fast + economical |
| Complex | Multi-step reasoning, analysis, code generation, research | Leading model for task area |

#### User Unhappiness Detection

The system detects user dissatisfaction through:

1. **Explicit feedback**: Thumbs down button click
2. **Sentiment analysis**: Follow-up messages expressing frustration ("this is wrong", "try again", "that's not what I asked", etc.)

When the thumbs down button is clicked:
- Automatically copies a message to the input field (in user's language) expressing that the answer isn't good enough
- This triggers the pre-processor to select a more powerful model

---

### User Override Syntax

Users can bypass automatic model selection using `@` prefixes in their message:

| Override | Syntax | Effect |
|----------|--------|--------|
| Model | `@ai-model:{model_name}` | Use specified model, skip selection |
| Model + Provider | `@ai-model:{model_name}:{provider_name}` | Use model from specific provider |
| Mate | `@mate:{mate_name}` | Skip mate auto-detection |
| Skill | `@skill:{app}:{skill_id}` | Force specific skill usage |
| Focus Mode | `@focus:{app}:{focus_mode_id}` | Start specific focus mode |

**Examples:**

```text
@ai-model:claude-4-sonnet What is the capital of France?
@ai-model:deepseek-r1:openrouter Solve this math problem...
@mate:researcher Help me find papers on quantum computing
@skill:code:get-docs Explain the React useEffect hook
@focus:code:plan-project I want to build a todo app
```

When an override is present, the pre-processor does NOT include processing for that category (model selection, mate detection, etc.) and directly uses the user's specified value.

---

### China-Sensitive Content Handling

#### Problem

Chinese models (Qwen, DeepSeek, Yi, etc.) exhibit bias or censorship on China-sensitive topics due to regulatory requirements.

#### Solution

1. **Hardcoded keyword detection** (fast, no LLM cost):

```python
CHINA_SENSITIVE_KEYWORDS = [
    # General (better safe than sorry)
    "china",

    # Territory/sovereignty
    "taiwan", "tibet", "xinjiang", "hong kong", "macau",
    "south china sea", "nine-dash line", "one china",

    # Human rights
    "uyghur", "uighur", "tiananmen", "june 4th", "1989",
    "falun gong", "dalai lama", "free tibet",

    # Political
    "ccp", "chinese communist party", "xi jinping criticism",
    "great firewall", "censorship china",

    # Historical events
    "cultural revolution", "great leap forward",
    "tiananmen square",
]
```

1. **Filtering logic**:
   - Check chat history for keywords
   - If `china_related = true` AND pre-processor selected a model with `country_origin: CN` → remove it from selection
   - Use next model in the ranked list

#### Model Country Origin

Models are tagged with `country_origin` (ISO 3166-1 alpha-2 code) in their provider YAML files:

```yaml
# backend/providers/alibaba.yml
models:
  qwen3-max:
    country_origin: CN
    # ...

# backend/providers/anthropic.yml
models:
  claude-4-sonnet:
    country_origin: US
    # ...

# backend/providers/mistral.yml
models:
  mistral-medium-3:
    country_origin: FR
    # ...
```

When `china_related = true`, models with `country_origin: CN` are filtered out.

---

### Leaderboard Categories

#### LM Arena Categories

**Main categories:**
- `text` - General text generation (default)
- `webdev` - Web development
- `vision` - Image understanding
- `text-to-image` - Image generation
- `image-edit` - Image editing
- `search` - Search/retrieval
- `text-to-video` - Video generation
- `image-to-video` - Video from images

**Text subcategories:**
- `overall` - General performance
- `hard-prompts` - Difficult prompts
- `coding` / `code` - Programming
- `math` - Mathematical reasoning
- `creative-writing` / `writing` - Creative content
- `instruction-following` - Following instructions
- `longer-query` - Long-form responses

#### OpenRouter Categories

Currently only `programming` is reliably available via scraping due to SPA limitations. Other categories (roleplay, marketing, legal, customer-support, data-analysis, creative-writing, research, education, general) require manual UI interaction.

#### Task Area Mapping

| Pre-processor Output | LM Arena Category | OpenRouter Category |
|---------------------|-------------------|---------------------|
| `code` | coding | programming |
| `math` | math | - |
| `creative` | creative-writing | creative-writing |
| `instruction` | instruction-following | - |
| `general` | overall | - |

---

### Leaderboard Aggregation

#### Daily Update Script

A scheduled task runs daily to:

1. **Fetch rankings** from each source:
   - LM Arena: ELO scores per category
   - OpenRouter: Usage data, pricing, speed (TPS)
   - SimpleBench: Reasoning benchmarks

2. **Normalize and aggregate**:
   - Convert different scoring systems to comparable metrics
   - Map model IDs across platforms

3. **Handle new models**:
   - If a model appears without known platform ID mappings
   - Use LLM (one-time) to identify the correct mapping
   - Store mapping in provider YAML for future use

4. **Output**: `models_leaderboard.yml` with:

```yaml
# Generated by leaderboard aggregator - DO NOT EDIT MANUALLY
last_updated: "2026-01-29T00:00:00Z"

models:
  claude-4-sonnet:
    provider: anthropic
    country_origin: US
    scores:
      lmarena:
        overall: 1489
        coding: 1475
        math: 1460
        creative_writing: 1495
      openrouter:
        usage_rank: 1
        tps: 53.15
      simplebench:
        reasoning: 78.5
    pricing:
      input_per_1m: 3.00
      output_per_1m: 15.00

  qwen3-max:
    provider: alibaba
    country_origin: CN
    scores:
      lmarena:
        overall: 1420
        coding: 1445
        math: 1465
      # ...

  mistral-medium-3:
    provider: mistral
    country_origin: FR
    scores:
      lmarena:
        overall: 1380
      # ...
```

#### Existing Scripts

| Script | Purpose |
|--------|---------|
| `backend/scripts/fetch_lmarena_rankings.py` | Fetches LM Arena rankings with category support |
| `backend/scripts/fetch_openrouter_rankings.py` | Fetches OpenRouter rankings and usage data |

---

### Model ID Mapping

Model IDs vary across platforms. Mappings are stored in each provider's YAML:

```yaml
# backend/providers/anthropic.yml
models:
  claude-4-sonnet:
    display_name: "Claude 4 Sonnet"
    external_ids:
      openrouter: "anthropic/claude-4-sonnet"
      lmarena: "claude-4-sonnet-20260101"
      aws_bedrock: "anthropic.claude-4-sonnet-20260101-v1:0"
    # ...
```

On server startup, all provider YAMLs are loaded to cache for fast lookup. The cache is only updated when provider files change.

---

### Fallback Strategy

#### Tiered Fallback

1. **Primary**: Best model from pre-processor selection (model 1)
2. **Secondary**: Second-best from selection (model 2)
3. **Tertiary**: Hardcoded fallback from `app.yml` (if different from 1 & 2)

#### Provider Fallback

For each model, multiple providers may be available:

1. Try default provider (e.g., AWS Bedrock for Claude)
2. On failure (rate limit, API error): try next provider
3. If all providers fail: move to next model in selection

Provider health is tracked via existing health check endpoint/script.

---

### "Economical" Model Definition

For simple tasks, select models that are:

1. **Fast**: TPS > 50 tokens/second
2. **Affordable**: < $1.00 per 1M input tokens (reasonable starting threshold)
3. **Capable enough**: LM Arena overall score > 1200

This definition will be tuned based on real-world usage patterns.

---

### Testing Strategy

Create test cases to validate and fine-tune pre-processor model selection:

```yaml
# Test case structure
test_cases:
  - name: "Simple factual question"
    message: "What is the capital of France?"
    expected:
      complexity: simple
      task_area: general
      model_type: economical

  - name: "Complex coding task"
    message: "Write a React component with authentication"
    expected:
      complexity: complex
      task_area: code
      model_type: leading_code

  - name: "China-sensitive topic"
    message: "What happened at Tiananmen Square in 1989?"
    expected:
      china_related: true
      excludes_chinese_models: true

  - name: "User override"
    message: "@ai-model:gpt-5 Explain quantum computing"
    expected:
      model: gpt-5
      bypasses_selection: true
```

---

## Key Implementation Files

| Component | File |
|-----------|------|
| Model selector service | `backend/apps/ai/utils/model_selector.py` |
| China-sensitivity detection | `backend/core/api/app/services/china_sensitivity.py` |
| User override parser | `backend/core/api/app/utils/override_parser.py` |
| Leaderboard aggregator script | `backend/scripts/aggregate_leaderboards.py` |
| Leaderboard Celery tasks | `backend/core/api/app/tasks/leaderboard_tasks.py` |
| Preprocessor integration | `backend/apps/ai/processing/preprocessor.py` |
| Main processor fallback | `backend/apps/ai/processing/main_processor.py` |
| Task area/unhappy detection | `backend/apps/ai/base_instructions.yml` |
| Provider configurations | `backend/providers/*.yml` |

---

## Benchmark Resources

The following resources provide model comparison data for leaderboard aggregation:

- [LM Arena](https://lmarena.ai/leaderboard) - ELO rankings from human preferences, category-specific leaderboards
- [OpenRouter](https://openrouter.ai/rankings) - Real usage data, pricing, speed metrics
- [SimpleBench](https://simple-bench.com) - Reasoning and capability benchmarks

---

## Read Next

- [Message Processing Architecture](./message_processing.md) - How messages flow through pre/main/post processors
- [Provider Configuration](../providers/README.md) - How to configure model providers
