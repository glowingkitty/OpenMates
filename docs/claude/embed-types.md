# Embed Types — Rules

Rules for creating or modifying embed types. For full component skeletons and step-by-step guide, run:
`python3 scripts/sessions.py context --doc embed-types-ref`

---

## Architecture

Embeds appear in two places:

1. **Preview card** — fixed-size card inline in messages (desktop: 300x200px, mobile: 150x290px)
2. **Fullscreen panel** — slides in from preview, fills right panel

Every embed uses two Svelte components wrapping two shared base components:

- `XxxEmbedPreview.svelte` → wraps `UnifiedEmbedPreview.svelte`
- `XxxEmbedFullscreen.svelte` → wraps `UnifiedEmbedFullscreen.svelte`

## Critical Rules

### Use Unified Components — No Exceptions

You MUST use `UnifiedEmbedPreview.svelte` and `UnifiedEmbedFullscreen.svelte` as the base. Your components only provide:

- Preview: the `{#snippet details}` with skill-specific content
- Fullscreen: the `{#snippet content}` with skill-specific results

Do NOT reimplement: card sizing, hover/tilt, status bar, stop button, fullscreen animation, top bar, gradient header, child embed loading, share handler, navigation.

Before adding custom logic, check if existing Unified component props handle it: `showSkillIcon`, `faviconUrl`, `customStatusText`, `hasFullWidthImage`, `customHeight`, `titleIcon`, `actionButton`, `childEmbedTransformer`.

### Two Embed Categories

1. **App-Skill-Use** (most common): Backend skill execution result. Has `app_id` + `skill_id`. Rendering path: `embedParsing.ts → AppSkillUseRenderer.ts → mount(YourPreview)`
2. **Direct-Type**: Client-inserted (file upload, user action). Has own renderer class in `embed_renderers/`.

### Anti-Patterns — Never Do These

- Never subscribe to `embedUpdated` yourself — UnifiedEmbedPreview already does it
- Never use `$:` reactive statements — Svelte 5 only (`$derived`, `$effect`)
- Never hardcode colors — use `var(--color-app-{appId})`
- Never call `resolveEmbed` in skill components — data comes via `onEmbedDataUpdated`
- Never duplicate BasicInfosBar — UnifiedEmbedPreview renders it
- Never use `window.innerWidth` in fullscreen — use `@container fullscreen (max-width: ...)`
- Never load external images directly — use `proxyImage()` from `imageProxy.ts`

### Registration Checklist (App-Skill-Use)

Files you MUST touch for every new app-skill-use embed:

1. `theme.css` — add `--color-app-{appId}-start/end` (if new app)
2. `static/icons/{skillIconName}.svg` — skill icon (if new icon)
3. `embeds/{appId}/{SkillName}EmbedPreview.svelte` — preview component
4. `embeds/{appId}/{SkillName}EmbedFullscreen.svelte` — fullscreen component
5. `embeds/{appId}/*.preview.ts` — dev preview mock data (both preview + fullscreen)
6. `BasicInfosBar.svelte` + `EmbedHeader.svelte` — skill icon CSS blocks
7. `i18n/sources/embeds.yml` — skill label (all 20 locales)
8. `AppSkillUseRenderer.ts` — import + routing + render method
9. `ActiveChat.svelte` — fullscreen dispatch case
10. If groupable child embeds: also update `GroupRenderer.ts`
11. **CLI text renderer** — add preview + fullscreen cases in `frontend/packages/openmates-cli/src/embedRenderers.ts` (preview in `renderEmbedPreview()` switch, fullscreen in `renderEmbedFullscreen()` switch). For app-skill-use embeds add a `case "{appId}/{skillId}":` entry; for direct-type embeds add a `case "{type}":` entry in `renderByDirectType()` / `renderDirectTypeFullscreen()`

### Design Rules

- Primary text: 16px/600 weight, `--color-grey-100`, 3-line clamp
- Secondary text: 14px/400, `--color-grey-70`
- Mobile primary: 14px; mobile secondary: 12px
- Details gap: 4px; results grid gap: 16px; fullscreen padding: 24px 16px, bottom: 120px
- App gradient: always `var(--color-app-{appId})`, 135deg
- Use CSS container queries in fullscreen: `@container fullscreen (max-width: ...)`
- Clamp long text with `-webkit-line-clamp`
