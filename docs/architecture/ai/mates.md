---
status: active
last_verified: 2026-04-09
key_files:
  - backend/apps/ai/mates/
  - backend/apps/ai/utils/mate_utils.py
  - backend/apps/ai/processing/preprocessor.py
  - frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts
  - frontend/packages/ui/src/styles/mates.css
---

# Mates: Domain Expert AI Personas

> Specialized AI personas with domain-specific system prompts, automatically selected by the preprocessor based on message content. Stored in a Claude Code compatible frontmatter markdown format.

## Why This Exists

A generic AI assistant underperforms on domain-specific tasks. Mates provide tailored system prompts that establish expertise, set communication style, include domain-specific guidelines, and add necessary disclaimers (medical, legal, financial). The preprocessor routes each message to the most appropriate Mate.

## How It Works

### Configuration

All Mates live in [`backend/apps/ai/mates/`](../../../backend/apps/ai/mates/) as one frontmatter `.md` file per Mate. The filename is the category (e.g., `software_development.md`). Each file has a YAML frontmatter block with metadata and a markdown body that is the English default system prompt.

The format intentionally aligns with the [Claude Code subagent file format](https://docs.claude.com/en/docs/claude-code/sub-agents) so that future imports of Claude Code agents into OpenMates are mostly a drop-in.

#### Frontmatter schema

**Claude Code compatible fields:**

| Field | Purpose |
|---|---|
| `name` | Stable lowercase identifier (e.g., `sophia`). Maps to `MateConfig.id`. |
| `description` | Brief expertise summary. |
| `model` | Preferred model. `inherit` = no restriction. **Reserved — not yet enforced.** |
| `tools` | Allowlist of app/skill IDs this Mate can use. `inherit` = no restriction. **Reserved — replaces the legacy `assigned_apps` field.** |
| `skills` | Allowlist of focus modes (Claude Code calls these "skills"). `inherit` = no restriction. **Reserved — not yet enforced.** |

**OpenMates extensions:**

| Field | Purpose |
|---|---|
| `display_name` | Human-readable UI name (e.g., `Sophia`). Falls back to capitalized `name` if omitted. UI primarily uses i18n translations. |
| `category` | Preprocessing category (must match the filename). |
| `colors.start` / `colors.end` | UI gradient branding (mirrored in `matesMetadata.ts`). |
| `i18n.system_prompt` | Translation key for the localized system prompt. |

**Body:** the English default system prompt. Used as fallback when no translation is selected.

#### Example

```markdown
---
name: sophia
description: Software development expert.
model: inherit
tools: inherit
skills: inherit

display_name: Sophia
category: software_development
colors:
  start: "#155D91"
  end: "#42ABF4"
i18n:
  system_prompt: mates.software_development.systemprompt
---

You are Sophia, an expert AI software development assistant.
...
```

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

[`mate_utils.py`](../../../backend/apps/ai/utils/mate_utils.py) provides:

- **`load_mates_config(mates_dir_path)`**: Walks the mates directory, parses each `.md` file's frontmatter and body, validates via Pydantic, skips individual bad files (logged), and returns the list sorted by `id`.
- **`MateConfig`**: Pydantic model. Downstream consumers read `id`, `name`, `category`, `description`, `default_system_prompt`, and `tools`. `model` and `focus_modes` are parsed but not yet used.
- Reserved fields collapse the `inherit` sentinel (or missing value) to `None` so downstream code keeps using "None means no restriction" semantics.

### Routing

1. The preprocessor analyzes the user message and selects a `category` (e.g., `software_development`).
2. The category maps to a Mate whose `default_system_prompt` is injected into the main LLM call.
3. Users can bypass auto-routing with `@mate:{name}` syntax (e.g., `@mate:sophia`), or `@sophia` in the message editor.

### Frontend Integration

- [`mateHelpers.ts`](../../../frontend/packages/ui/src/components/enter_message/utils/mateHelpers.ts): Contains `VALID_MATES` array and `detectAndReplaceMates()` for @-mention handling in the message editor.
- [`matesMetadata.ts`](../../../frontend/packages/ui/src/data/matesMetadata.ts): Frontend mirror of the mate metadata (profile classes, colors, i18n keys). Display names are resolved via i18n translations.
- [`mates.css`](../../../frontend/packages/ui/src/styles/mates.css): Mate-specific CSS with visual branding.

### Notable Design Decisions

- **Suki (onboarding)** has a strict topic restriction — she only answers OpenMates-related questions and redirects all other topics to appropriate Mates.
- **Hiro (history)** has explicit multi-perspective instructions to avoid bias when describing complex historical events.
- **Sophia (software)** requires documentation search before answering API/framework questions to avoid outdated training data.
- **Denise (design)** encourages combining human-made art with AI rather than full AI replacement.
- **Claude Code compatible format**: The `.md` + frontmatter layout was chosen (over a single `mates.yml`) so Claude Code agents can be imported with minimal transformation once per-mate `model`/`tools`/`skills` enforcement is wired up.

## Edge Cases

- **Onboarding trigger filtering**: The preprocessor removes `onboarding_support` from candidate categories when no onboarding-related phrases appear in the chat history, preventing mis-routing to Suki.
- **Reserved fields not enforced**: `model`, `tools`, and `skills` are parsed into `MateConfig` but currently ignored at runtime. They become active when per-mate gating ships.

## Related Docs

- [AI Model Selection](./ai-model-selection.md) — model selection after Mate routing
- [Message Processing](../messaging/message-processing.md) — full pipeline
