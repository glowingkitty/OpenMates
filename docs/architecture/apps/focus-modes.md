# Focus Modes — SKILL.md Architecture

Status: **In progress — prototype stage.** The new format is live for one
focus mode (`jobs/career_insights`) behind a parity validator. All other
focus modes continue to load from `app.yml` + frontend i18n YAML files.

This doc defines the target format and the migration path from the legacy
layout. It is the source of truth for future focus mode authoring and the
follow-up bulk migration session.

---

## Why change

The legacy layout splits a single focus mode across 3–4 files:

| File | Holds |
|---|---|
| `backend/apps/<app>/app.yml` → `focuses[]` | id, translation keys, `system_prompt`, `process`, `stage`, `preprocessor_hint`, `icon_image` |
| `frontend/packages/ui/src/i18n/sources/focus_modes/<app>_<mode>.yml` | name, description, process bullets, `how_to_use.1/2/3` examples — all languages |
| `frontend/packages/ui/src/i18n/sources/app_focus_modes/<app>.yml` | Per-app grouping of the same strings (duplicated) |
| `backend/apps/<app>/app.yml` → `preprocessor_hint` | Often contains the *actual* system prompt text (legacy drift) |

Problems this creates:

1. **Authoring is painful.** Adding or editing one focus mode touches 3+ files in two different repos. Translations live as YAML strings, not as the markdown prose they actually are.
2. **Drift is silent.** `systemprompt_translation_key` in several `app.yml` files points at keys that don't exist in any i18n YAML. The settings page's "show full instructions" button renders nothing in those cases, with no build-time warning.
3. **Not portable.** A focus mode can't be shared, forked, or moved between projects — it's smeared across the repo.
4. **Schema is implicit.** `AppFocusDefinition` only declares a subset of the fields actually used in `app.yml`. Extra fields (`process_translation_key`, `systemprompt_translation_key`, `icon_image`) are silently accepted by Pydantic, not validated.
5. **No room for new capabilities.** Adding model gating, skill gating, or phased workflows to the current schema would require coordinated edits across all 31 focus modes.

The new layout consolidates a focus mode into a single **directory with one `SKILL.md` per language**, matching Anthropic's Claude Code skills format so focus modes become portable in both directions (OpenMates ↔ Claude Code).

---

## Target layout

```
backend/apps/<app>/focus_modes/<focus_id>/
├── SKILL.md              # Canonical, English, source of truth
├── SKILL.de.md           # German override (string fields only)
├── SKILL.zh.md           # Chinese override
├── SKILL.fr.md           # …
├── references/           # Optional — loaded on-demand by the LLM
│   └── spaced-repetition.md
└── scripts/              # Optional — bundled helper scripts
    └── build_schedule.py
```

One directory per focus mode. `SKILL.md` is the canonical English artifact
**and the Claude-Code-compatible entry point**: drop the directory into
`~/.claude/skills/` and it works as a (monolingual) Claude Code skill.
`SKILL.<lang>.md` siblings are string-override files validated against the
canonical file by the parity lint (see below).

The legacy frontend i18n YAML files stay in place until the full migration
lands — they are the `SKILL.md` export target for non-English strings in
the prototype phase.

---

## `SKILL.md` format

YAML frontmatter + markdown body, modeled on Claude Code's SKILL.md layout
with OpenMates-specific extensions.

### Canonical English example

```markdown
---
# ── Identity ────────────────────────────────────────────────────────
id: career_insights
app: jobs
stage: production
icon: insight.svg

# ── User-facing strings (English canonical) ─────────────────────────
name: Career insights
description: Find the right career based on your strengths.

# ── Routing hint for the preprocessor LLM ───────────────────────────
preprocessor-hint: >
  Select when the user expresses career frustration, feels stuck in
  their job, is considering a career change, wants career direction
  or guidance, asks about career paths, or needs help figuring out
  what to do next professionally.

# ── Capability gating ───────────────────────────────────────────────
# All optional. Missing = unrestricted.
allowed-models: []              # empty = any model; populate to restrict
recommended-model: null         # default model when user has no preference
allowed-apps: []                # coarse allow-list of OpenMates apps
allowed-skills: []              # fine allow-list, overrides allowed-apps when set
                                #   entries: "<app>:<skill>" or "<app>:*"
denied-skills: []               # escape hatch for "allow app except these"

# ── i18n metadata ───────────────────────────────────────────────────
lang: en
verified_by_human: true
source_hash: null               # populated by build step on non-canonical files
---

# Career insights

## Process

- Understands your current job situation and what's prompting a change
- Explores what energizes and drains you in past and current roles
- Identifies your core skills, strengths, and areas of expertise
- Discusses your values, interests, and priorities in a career
- Considers practical constraints (location, finances, family, timeline)
- Suggests 2–4 concrete career directions that match your profile
- Provides actionable next steps (networking, upskilling, job boards)

## How to use

- I'm a **software developer** feeling burned out — help me explore alternative careers
- I love **creative work** and problem-solving — what careers match my skills?
- I want to **switch industries** from finance to tech — how should I start?

## System prompt

You are a thoughtful, experienced career advisor. Your goal is to help
users gain clarity on their career direction by deeply understanding who
they are, what they want, and what's realistic for them.

Start by understanding the user's current situation: What do they do now?
How long have they been doing it? What prompted them to seek advice?

… (full prompt continues) …
```

### Localized override (`SKILL.de.md`)

Only the user-facing strings and markdown body are translated. All
structural frontmatter (id, app, stage, gating lists, phases) must match
the canonical file — enforced by the parity lint.

```markdown
---
id: career_insights
app: jobs
stage: production
icon: insight.svg

name: Karriere-Einblicke
description: Finde die passende Karriere anhand deiner Stärken.

preprocessor-hint: >
  (English preprocessor hint — LLM selection runs in English)

allowed-models: []
recommended-model: null
allowed-apps: []
allowed-skills: []
denied-skills: []

lang: de
verified_by_human: true
source_hash: a1b2c3d4              # hash of canonical SKILL.md at translation time
---

# Karriere-Einblicke

## Ablauf

- Versteht deine aktuelle berufliche Situation und was einen Wechsel antreibt
- … (full German content) …

## So wird's verwendet

- Ich bin **Softwareentwickler** und fühle mich ausgebrannt — hilf mir, Alternativen zu erkunden
- …

## System-Prompt

(German system prompt body)
```

---

## Frontmatter reference

Required fields in **bold**. All others optional.

| Field | Type | Purpose |
|---|---|---|
| **`id`** | string | Stable identifier, snake_case. Used in API responses, chat state, WS events. Must match the directory name. |
| **`app`** | string | Parent app id (e.g. `jobs`, `study`). Must match the containing `backend/apps/<app>/` directory. |
| **`name`** | string | User-facing display name (≤60 chars). |
| **`description`** | string | One-line user-facing description (≤140 chars). |
| **`lang`** | string | BCP 47-ish language code (`en`, `de`, `zh`, …). The canonical file uses `en`. |
| `stage` | `planning` \| `development` \| `production` | Lifecycle gate. `planning` is excluded from API responses. Defaults to `development`. |
| `icon` | string | SVG filename in the app's icon directory. |
| `preprocessor-hint` | string (1–3 sentences) | LLM-facing hint used during focus mode selection. Lives in the canonical English file only — selection runs in English. |
| `allowed-models` | list\<string\> | Model allowlist (e.g. `[claude-opus-4-6, gpt-5]`). Empty or missing = any model. |
| `recommended-model` | string \| null | Default model when user has no preference. |
| `allowed-apps` | list\<string\> | Coarse app allowlist. Empty = all apps. |
| `allowed-skills` | list\<string\> | Fine-grained skill allowlist, format `<app>:<skill>` or `<app>:*`. Overrides `allowed-apps` when present. |
| `denied-skills` | list\<string\> | Subtractive filter applied after `allowed-apps`/`allowed-skills`. |
| `verified_by_human` | bool | True if a human has reviewed this specific language file end-to-end. |
| `source_hash` | string \| null | SHA-256 of the canonical `SKILL.md` at the time this localized file was generated. Used by the parity lint to detect stale translations. Always `null` on the canonical file. |

### Reserved for a future session (not yet implemented)

| Field | Type | Purpose |
|---|---|---|
| `phases` | list\<object\> | Multi-phase workflow with gates. Each phase: `id`, `title`, `requires`, `completion` list, optional `allowed-skills` override. Reserved — do not populate yet; runtime contract is out of scope for the prototype session. |

---

## Markdown body sections

Parsed by heading. Section order in the canonical file:

| Heading | Required | Maps to |
|---|---|---|
| `# <name>` | required | Presentational title. Must match frontmatter `name`. |
| `## Process` | required | Bullet list shown on the focus mode settings page and in the activation banner. One bullet per line, `- ` prefix. |
| `## How to use` | optional | Example user prompts. `**word**` syntax highlights trigger words in the UI. Backwards-compatible with the legacy `how_to_use.1/2/3` keys — loader emits indexed entries. |
| `## System prompt` | required | Full system prompt injected into the LLM context when this focus mode is active. Free-form markdown. Linked `references/*.md` files are lazy-loaded on demand. |

All other headings are treated as free-form commentary and passed through
unchanged — useful for authoring notes that don't leave the file.

---

## Loader contract

The SKILL.md loader lives at
`backend/shared/python_utils/focus_mode_skill_loader.py` and exposes:

```python
def load_focus_mode_from_skill_md(skill_md_path: str) -> dict:
    """
    Parse a SKILL.md file into a dict shaped for AppFocusDefinition.

    Returns a dict with the same field names AppFocusDefinition consumes
    (id, name_translation_key, description_translation_key,
    system_prompt, process, stage, preprocessor_hint, icon_image,
    allowed_models, recommended_model, allowed_apps, allowed_skills,
    denied_skills, how_to_use).

    Translation keys are derived from <app>.<id> — consistent with the
    legacy app.yml convention so the frontend build script sees an
    identical shape without frontend changes.
    """
```

The loader **does not** mutate app.yml or i18n files. In the prototype
phase, it runs as a startup-time parity validator (see below); in the
bulk migration phase, it becomes the primary focus mode source.

---

## Parity validator (prototype-phase safety net)

On backend startup, a validator compares each migrated focus mode's
SKILL.md-derived dict to its existing `app.yml` entry. Drift is logged
as a warning but **does not fail startup** — the legacy path is
authoritative in the prototype phase. This catches accidental drift
between the two sources while migration is incomplete.

Compared fields: `id`, `stage`, `icon_image`, `preprocessor_hint`
(normalized), and any field both sources populate. Fields unique to
SKILL.md (gating, how_to_use) are not compared.

---

## Parity lint (bulk-migration safety net — future)

When the full migration lands, a build-time lint enforces that all
`SKILL.<lang>.md` siblings have **identical structural frontmatter** to
the canonical `SKILL.md`. Only these fields are allowed to differ:

- `name`, `description`, `preprocessor-hint` (localized strings)
- Markdown body content
- `lang`, `verified_by_human`, `source_hash` (metadata)

All other frontmatter fields must match exactly. Drift fails CI.

The lint also verifies `source_hash` on each localized file: if the
canonical `SKILL.md`'s hash has changed since the translation was
generated, the localized file is flagged as stale and `verified_by_human`
is auto-flipped to false until a human re-verifies.

---

## Migration phases

### Phase 1 — prototype (this session)

- Write this doc ✓
- Create `backend/apps/jobs/focus_modes/career_insights/SKILL.md` (English, canonical) and `SKILL.de.md` (German)
- Extend `AppFocusDefinition` with new optional fields (additive, non-breaking)
- Add SKILL.md loader at `backend/shared/python_utils/focus_mode_skill_loader.py`
- Add startup parity validator (warning-only)
- Deploy, run `focus-mode-career-insights.spec.ts`, confirm green
- No changes to `app.yml`, frontend i18n YAML, frontend build script, or runtime hot path

### Phase 2 — bulk migration (follow-up session)

- Migrate remaining 33 focus modes via conversion script (app.yml + i18n YAML → SKILL.md + translations)
- Switch loader from parity validator to primary source
- Teach `generate-apps-metadata.js` to read SKILL.md files (or add a pre-build step that synthesizes app.yml from SKILL.md)
- Remove legacy `focuses[]` entries from `app.yml`
- Remove legacy `focus_modes/` and `app_focus_modes/` i18n source files
- Ship parity lint

### Phase 3 — phased workflows (separate design session)

- Design `phases:` runtime contract (`advance_phase`, `mark_requirement` tools, state persistence on chat)
- Implement one multi-phase focus mode (candidate: `code/setup_infrastructure`)
- Add UI for phase progress display

---

## Portability

A Phase-2 focus mode is a self-contained directory. To use it as a
Claude Code skill:

```bash
cp -r backend/apps/jobs/focus_modes/career_insights ~/.claude/skills/career-insights
```

Claude Code reads `SKILL.md` directly; the `SKILL.<lang>.md` siblings are
ignored. OpenMates-specific frontmatter fields (`app`, `allowed-apps`,
`phases`) are likewise ignored by Claude Code — the markdown body still
works as a skill prompt.

Going the other way (Claude Code skill → OpenMates focus mode) requires
adding the OpenMates-specific frontmatter (`app`, `stage`) and wiring the
focus mode into the parent app's routing.

---

## Related

- Schema: `backend/shared/python_schemas/app_metadata_schemas.py` (`AppFocusDefinition`)
- Loader: `backend/shared/python_utils/focus_mode_skill_loader.py`
- Frontend metadata generator: `frontend/packages/ui/scripts/generate-apps-metadata.js`
- Current i18n sources (being retired): `frontend/packages/ui/src/i18n/sources/focus_modes/`, `frontend/packages/ui/src/i18n/sources/app_focus_modes/`
- Spec coverage: `frontend/apps/web_app/tests/focus-mode-career-insights.spec.ts` (1 of 34 focus modes covered)
- Preprocessor consumer: `backend/apps/ai/processing/preprocessor.py` (reads `focus.preprocessor_hint` for LLM selection)
