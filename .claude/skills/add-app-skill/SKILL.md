---
name: openmates:add-app-skill
description: Scaffold a new skill in an existing app (BaseSkill, schemas, app.yml, i18n)
user-invocable: true
argument-hint: "<appId> <skillId> <SkillClassName>"
---

## Arguments

Parse `$ARGUMENTS` into three parts:
- `appId` — app directory name (e.g., `web`, `news`, `travel`)
- `skillId` — kebab-case skill identifier (e.g., `deep-research`)
- `SkillClassName` — PascalCase class name (e.g., `DeepResearchSkill`)

If any are missing, ask the user before proceeding.

## Instructions

You are adding a new skill to an existing app microservice. This touches backend Python code, YAML config, and i18n.

### Step 1: Understand the Target App

Read these files to understand the app's patterns:
1. `backend/apps/{appId}/app.yml` — existing skills, embed types, categories
2. `backend/apps/base_skill.py` (lines 1-145) — BaseSkill interface
3. An existing skill in `backend/apps/{appId}/skills/` — use as template
4. `backend/shared/python_schemas/app_metadata_schemas.py` — AppYAML schema (for valid field names)

### Step 1b: Create Skill Behavior Spec

Before scaffolding a new app skill, run `specify` or create an inline spec using
`docs/contributing/guides/spec-driven-development.md`.

New app skills usually require a full spec because they define user-facing AI
behavior, tool contracts, provider behavior, and often embed behavior. The spec
must include:

- Sample user prompts
- Expected tool input parameters
- Expected skill output shape
- No-results behavior
- Provider-error behavior
- Permission, privacy, and API-key behavior
- Embed preview/fullscreen behavior if the skill produces embeds
- App-store examples that double as executable examples

### Step 2: Create the Skill File

Create `backend/apps/{appId}/skills/{skill_file}.py` where `skill_file` is `skillId` with hyphens replaced by underscores.

Follow this structure exactly:

```python
"""
{SkillClassName} — {brief description}.

Architecture: docs/architecture/app_skills.md
"""
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class {SkillName}Request(BaseModel):
    """{description}."""
    # Define input fields from tool_schema


class {SkillName}Response(BaseModel):
    """{description}."""
    success: bool = Field(default=False)
    # Define output fields


class {SkillClassName}(BaseSkill):
    """
    {Description of what this skill does}.
    """

    async def execute(
        self,
        # Skill-specific params (must match tool_schema properties)
        secrets_manager=None,
        cache_service=None,
        encryption_service=None,
        directus_service=None,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        **kwargs
    ) -> {SkillName}Response:
        """Execute the skill."""
        try:
            # Implementation here
            return {SkillName}Response(success=True)
        except Exception as e:
            logger.error(f"{SkillClassName} error: {e}", exc_info=True)
            return {SkillName}Response(success=False, error=str(e))
```

### Step 3: Register in app.yml

Add to the `skills:` list in `backend/apps/{appId}/app.yml`:

```yaml
  - id: {skillId}
    name_translation_key: {appId}.{skill_id_underscored}
    description_translation_key: {appId}.{skill_id_underscored}.description
    icon_image: {icon}.svg
    preprocessor_hint: >
      Natural language description for AI model routing
    stage: development
    providers:
      - name: OpenMates
        no_api_key: true
    class_path: backend.apps.{appId}.skills.{skill_file}.{SkillClassName}
    tool_schema:
      type: object
      properties:
        # Define input parameters
      required:
        # List required params
```

If the skill produces embeds, also add an `embed_types:` entry.

### Step 4: Add i18n Entries

Add skill name and description to `frontend/packages/ui/src/i18n/sources/skills.yml` (all 20 locales).

Then rebuild:
```bash
cd frontend/packages/ui && npm run build:translations
```

### Step 5: Add App-Store Examples

Every new app skill must include app-store examples so the skill details page can show realistic preview cards.

If the skill produces embeds:
1. Run or script at least two real skill requests that cover the main provider/result shapes.
2. Create `frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedPreview.examples.ts` next to the preview component.
3. Export an array of flat preview props matching the preview component, with `query_translation_key` values under `settings.app_store_examples.{appId}.{skill_id_underscored}.<n>`.
4. Add those query labels to `frontend/packages/ui/src/i18n/sources/settings/app_store_examples.yml`.

If the skill does not produce embeds, add equivalent user-facing examples in `backend/apps/{appId}/app.yml` using the existing `example_entries` or `example_translation_keys` pattern for that app.

### Step 6: Create Test Script (Optional)

If `scripts/test_skills/` exists, create `test_{skill_id_underscored}.py` following the pattern of other test scripts in that directory.

### Step 7: Check for Embed Need

Ask the user: "Does this skill produce embeds that need a frontend component?"

If yes, suggest running `/add-embed-type {appId} {skillId} {SkillName}` next.

## Rules

- Skills must NOT import from other skills — shared logic goes to `BaseSkill` or `backend/shared/`
- All `execute()` params must match `tool_schema.properties` names exactly
- Use `logger = logging.getLogger(__name__)` — never `print()`
- Type hints on all function parameters and return values
- Pydantic models use `PascalCase` — end request models with `Request`, response with `Response`
- Initial `stage` should be `development` until tested
- App-store examples are required for every new skill; do not ship a skill with an empty examples section
