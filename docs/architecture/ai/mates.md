---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/mates.yml
  - backend/apps/ai/utils/mate_utils.py
  - backend/apps/ai/processing/preprocessor.py
  - frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts
  - frontend/packages/ui/src/styles/mates.css
---

# Mates: Domain Expert AI Personas

> Specialized AI personas with domain-specific system prompts, automatically selected by the preprocessor based on message content.

## Why This Exists

A generic AI assistant underperforms on domain-specific tasks. Mates provide tailored system prompts that establish expertise, set communication style, include domain-specific guidelines, and add necessary disclaimers (medical, legal, financial). The preprocessor routes each message to the most appropriate Mate.

## How It Works

### Configuration

All Mates are defined in [`backend/apps/ai/mates.yml`](../../backend/apps/ai/mates.yml). Each entry contains:

- **`id`**: Unique identifier (e.g., `sophia`, `melvin`)
- **`name`**: Display name
- **`category`**: Maps to preprocessing categories (e.g., `software_development`, `medical_health`)
- **`description`**: Brief expertise summary
- **`default_system_prompt`**: Domain-specific instructions injected into the LLM system prompt
- **`system_prompt_translation_key`**: i18n key for localized prompts
- **`background_color_start`/`background_color_end`**: UI gradient branding

### Available Mates (17 total)

| Mate | Category | Domain |
|------|----------|--------|
| Sophia | software_development | Coding, architecture, software engineering |
| Burton | business_development | Strategy, market analysis, growth |
| Melvin | medical_health | Health and wellness (educational only) |
| Leon | legal_law | Legal information (not legal advice) |
| Makani | maker_prototyping | DIY, 3D printing, electronics, fabrication |
| Mark | marketing_sales | Marketing strategies, sales, branding |
| Finn | finance | Financial planning, investment (educational) |
| Denise | design | Graphic design, UI/UX, visual aesthetics |
| Elton | electrical_engineering | Circuits, electronics, electrical systems |
| Monika | movies_tv | Cinema, TV series, actors, directors |
| Hiro | history | Historical events, figures, periods |
| Scarlett | science | Physics, biology, chemistry, astronomy |
| Lisa | life_coach_psychology | Personal development, well-being |
| Colin | cooking_food | Recipes, culinary techniques, food culture |
| Ace | activism | Social movements, advocacy, organizing |
| George | general_knowledge | Broad topics not covered by specialists |
| Suki | onboarding_support | OpenMates platform help and onboarding |

### Loading and Validation

[`mate_utils.py`](../../backend/apps/ai/utils/mate_utils.py) provides:

- **`load_mates_config()`**: Loads and validates all Mate configs from YAML using Pydantic models
- **`MateConfig`**: Pydantic model validating individual Mate fields
- **`MatesYAML`**: Pydantic model validating the entire file structure

### Routing

1. The preprocessor analyzes the user message and selects a `category` (e.g., `software_development`)
2. The category maps to a Mate whose `default_system_prompt` is injected into the main LLM call
3. Users can bypass auto-routing with `@mate:{name}` syntax (e.g., `@mate:sophia`)

### Frontend Integration

- [`mateHelpers.ts`](../../frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts): Contains `VALID_MATES` array and `detectAndReplaceMates()` for @-mention handling in the message editor
- [`mates.css`](../../frontend/packages/ui/src/styles/mates.css): Mate-specific CSS with visual branding (gradient colors)
- Messages in the UI show which Mate responded, with the Mate's gradient colors

### Notable Design Decisions

- **Suki (onboarding)** has a strict topic restriction -- she only answers OpenMates-related questions and redirects all other topics to appropriate Mates.
- **Hiro (history)** has explicit multi-perspective instructions to avoid bias when describing complex historical events.
- **Sophia (software)** requires documentation search before answering API/framework questions to avoid outdated training data.
- **Denise (design)** encourages combining human-made art with AI rather than full AI replacement.

## Edge Cases

- **Onboarding trigger filtering**: The preprocessor removes `onboarding_support` from candidate categories when no onboarding-related phrases appear in the chat history, preventing mis-routing to Suki.
- **@mate mention not yet fully implemented**: The frontend has the helpers and CSS, but the full mention UI flow is noted as not yet complete in the codebase.

## Related Docs

- [AI Model Selection](./ai-model-selection.md) -- model selection after Mate routing
- [Message Processing](../messaging/message-processing.md) -- full pipeline
