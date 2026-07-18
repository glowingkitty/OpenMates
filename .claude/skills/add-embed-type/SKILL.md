---
name: openmates:add-embed-type
description: Scaffold and register a new embed type (components, theme, icons, i18n, renderer)
user-invocable: true
argument-hint: "<appId> <skillId> <SkillName>"
---

## Arguments

Parse `$ARGUMENTS` into three parts:
- `appId` — kebab-case app identifier (e.g., `weather`)
- `skillId` — kebab-case skill identifier (e.g., `forecast`)
- `SkillName` — PascalCase component prefix (e.g., `WeatherForecast`)

If any are missing, ask the user before proceeding.

## Instructions

You are scaffolding a new embed type. This is a multi-file, multi-step process — follow every step exactly.

### Step 0: Load the Full Guide

```bash
python3 scripts/sessions.py context --doc embed
```

Read the guide output carefully — it contains the complete checklist, component skeletons, design rules, and anti-patterns. The steps below are a summary; the guide is authoritative.

### Step 0b: Confirm Phase Gate

Do not scaffold a web embed before the producing skill or feature has CLI-first
evidence. Confirm or record in the spec/inline contract:

1. The backend skill/provider emits the embed payload correctly in OpenMates CLI
   against the dev server. Mocked OpenMates API calls, mocked SDK clients,
   stubbed servers, direct function calls, and fixture replay do not satisfy this
   gate.
2. npm SDK and pip SDK parity are implemented and tested locally against the dev
   server when the embed-producing behavior is exposed programmatically. After
   local CLI and SDK evidence is green, reproduce or wire the same coverage into
   GitHub Actions for CI/daily tests.
3. Web preview/fullscreen components and Playwright coverage start only after CLI
   and required SDK evidence are green.
4. The user must confirm the deployed dev web embed works and looks correct before
   Apple parity starts. `*.spec.ts` evidence alone is not enough.
5. Apple embed parity starts only after CLI, SDK, web, and user-confirmation
   evidence are complete, or after an explicit waiver/blocker is recorded.

### Step 1: Check Existing State

Before creating anything:
1. Check if `frontend/packages/ui/src/components/embeds/{appId}/` already exists
2. Check if `theme.css` already has `--color-app-{appId}` gradient
3. Read an existing embed pair as a template (e.g., `embeds/news/NewsEmbedPreview.svelte`)
4. Read `AppSkillUseRenderer.ts` to see the routing pattern

### Step 2: Create Component Files

Create these files in `frontend/packages/ui/src/components/embeds/{appId}/`:

| File | Purpose |
|------|---------|
| `{SkillName}EmbedPreview.svelte` | Wraps `UnifiedEmbedPreview`, provides `{#snippet details}` |
| `{SkillName}EmbedFullscreen.svelte` | Wraps `UnifiedEmbedFullscreen`, provides `{#snippet content(ctx)}` |
| `{SkillName}EmbedPreview.preview.ts` | Mock data with 4 variants: processing, error, cancelled, mobile |
| `{SkillName}EmbedFullscreen.preview.ts` | Mock data for fullscreen preview |
| `{camelCase}EmbedText.ts` | Text-only renderer for copy-message (uses `str()`, `trunc()` helpers) |

Use the template skeletons from the guide. Follow existing embed patterns exactly.

### Step 3: Theme & Icons (if new app)

1. **Gradient** — add to `frontend/packages/ui/src/styles/theme.css`:
   ```css
   --color-app-{appId}-start: #RRGGBB;
   --color-app-{appId}-end:   #RRGGBB;
   --color-app-{appId}: linear-gradient(135deg, var(--color-app-{appId}-start) 9.04%, var(--color-app-{appId}-end) 90.06%);
   ```

2. **Icon SVG** — add to `frontend/packages/ui/static/icons/{skillIconName}.svg` (single-colour, filled, no stroke)

3. **Icon CSS** — add to BOTH `BasicInfosBar.svelte` and `EmbedHeader.svelte` `<style>` blocks:
   ```css
   :global(.skill-icon[data-skill-icon="{skillIconName}"]) {
     -webkit-mask-image: url("@openmates/ui/static/icons/{skillIconName}.svg");
     mask-image: url("@openmates/ui/static/icons/{skillIconName}.svg");
   }
   ```

### Step 4: i18n

Add entries to `frontend/packages/ui/src/i18n/sources/embeds.yml` — ALL 20 locales required. Then:
```bash
cd frontend/packages/ui && npm run build:translations
```

### Step 5: Register in Renderer

In `AppSkillUseRenderer.ts`:
1. Import the Preview component at top
2. Add routing block in `render()` method (before generic fallback)
3. Add `render{SkillName}Component()` private method at bottom

### Step 6: Fullscreen Registration (Automatic)

Fullscreen routing is **automatic** via `embedRegistry.generated.ts` and `embedFullscreenResolver.ts`. When your embed preview fires an `embedfullscreen` event, ActiveChat dynamically loads and renders your fullscreen component — **no manual ActiveChat changes needed**.

Ensure your fullscreen component:
1. Accepts `data: EmbedFullscreenRawData` (from `types/embedFullscreen.ts`) as a required prop
2. Extracts fields from `data.decodedContent` internally (not via individual props)
3. Uses `UnifiedEmbedFullscreen` as the base wrapper
4. Is the default export of `{SkillName}EmbedFullscreen.svelte`

### Step 7: Register embedText

In `frontend/packages/ui/src/data/embedTextRenderers.ts`: import and register the text renderer function.

### Step 8: Register in app.yml

Add `embed_types` entry in `backend/apps/{appId}/app.yml` with correct `skill_id`, `preview_component`, `fullscreen_component`.

### Step 9: Verify

Check dev preview at `/dev/preview/embeds/{appId}/{SkillName}EmbedPreview` — test all state variants.

## Design Rules (Critical)

- **Never** hardcode colours — use `var(--color-app-{appId})` and theme variables
- **Never** use `$:` reactive statements — use `$derived()` and `$effect()` (Svelte 5)
- **Never** subscribe to `embedUpdated` yourself — `UnifiedEmbedPreview` handles it
- **Always** proxy external images via `proxyImage()` / `proxyFavicon()`
- **Always** use CSS container queries (not `@media`) inside fullscreen
- Typography: 16px/600 primary, 14px/400 secondary, 14px/500 tertiary
