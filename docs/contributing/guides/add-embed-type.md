---
status: active
last_verified: 2026-03-24
---

# Embed Types — Reference

Full component skeletons, step-by-step creation guide, and registration details.

---

# Creating New Embed Types (Full Guide)

> **MUST READ when ANY of these are true:**
>
> - You are adding a new skill embed (new `app_id` / `skill_id` combination)
> - You are adding a new direct embed type (e.g., a new file type, a new user-inserted object)
> - You are modifying how an existing embed renders in the preview card or fullscreen panel

---

## Overview

Embeds appear in two places in the chat UI:

1. **Preview card** — a fixed-size card rendered inline in the message stream
   - Desktop: `300 × 200 px`
   - Mobile: `150 × 290 px` (portrait)
2. **Fullscreen panel** — slides in from the preview card's position, fills the right panel (or overlays chat on mobile)

Every embed is built from **two Svelte components** (Preview + Fullscreen) that wrap two shared base components:

| Your component              | Wraps                           | Handles for you                                                                        |
| --------------------------- | ------------------------------- | -------------------------------------------------------------------------------------- |
| `XxxEmbedPreview.svelte`    | `UnifiedEmbedPreview.svelte`    | Card shell, sizing, tilt/hover, status bar, real-time update subscription, stop button |
| `XxxEmbedFullscreen.svelte` | `UnifiedEmbedFullscreen.svelte` | Slide-in animation, top bar (share/copy/close), gradient header, child embed loading   |

### Unified Components Are Mandatory (CRITICAL)

**You MUST use `UnifiedEmbedPreview.svelte` and `UnifiedEmbedFullscreen.svelte` as the base** for every embed. No exceptions. Your app-specific components only provide:

- Preview: the `{#snippet details}` with skill-specific content (query text, thumbnails, result counts)
- Fullscreen: the `{#snippet content}` with skill-specific result rendering (grid, list, detail view)

**Everything else is already handled by the Unified components.** Do NOT reimplement:

- Card sizing/layout, hover/tilt effects, status bar, stop button, context menus, touch handling
- Fullscreen animation, top bar, gradient header, child embed loading, search highlighting, share handler, navigation

**Before adding custom logic to an app-specific file**, verify it cannot be achieved through the existing Unified component props (`showSkillIcon`, `faviconUrl`, `customStatusText`, `hasFullWidthImage`, `customHeight`, `titleIcon`, `actionButton`, `childEmbedTransformer`). Only add app-specific code in the snippets.

---

## Embed Type Taxonomy

There are two categories of embed, each with a different rendering path:

### 1. App-Skill-Use Embeds (most common)

These represent a backend skill execution result. The embed JSON reference in the message markdown carries `app_id` and `skill_id`:

```json
{
  "type": "app-skill-use",
  "embed_id": "<uuid>",
  "app_id": "weather",
  "skill_id": "forecast"
```

**Rendering path:**

```
embedParsing.ts → EmbedNodeAttributes (type="app-skill-use")
  → AppSkillUseRenderer.ts (reads app_id + skill_id from decoded TOON)
    → mount(YourEmbedPreview.svelte)
      → fullscreen: document 'embedfullscreen' event → ActiveChat.svelte → YourEmbedFullscreen.svelte
```

Use this pattern for: web search, news, video search, travel, health, shopping, reminder, image generation — anything where the AI backend runs a skill and stores results.

### 2. Direct-Type Embeds

These are inserted directly by the client (user action or file upload), not via a backend skill. They have their own renderer class in `embed_renderers/`.

| Type string             | Renderer class                | Use case                   |
| ----------------------- | ----------------------------- | -------------------------- |
| `maps`                  | `MapLocationRenderer`         | User-pinned map location   |
| `recording`             | `RecordingRenderer`           | Voice note recording       |
| `pdf`                   | `PdfRenderer`                 | Uploaded PDF file          |
| `image`                 | `ImageRenderer`               | Inline image / SVG         |
| `focus-mode-activation` | `FocusModeActivationRenderer` | Focus mode state indicator |

Use this pattern for: a new file type the user uploads, a new object the user inserts into the editor directly (not via AI).

---

## Part 1: Creating an App-Skill-Use Embed

### Pre-flight checklist

Before writing any code, verify:

- [ ] `appId` matches the backend app identifier exactly (e.g., `"weather"`, `"finance"`)
- [ ] `skillId` matches the backend skill identifier exactly (e.g., `"forecast"`, `"portfolio"`)
- [ ] The backend skill outputs a TOON-encoded content object with the fields your Preview needs
- [ ] `--color-app-{appId}-start` and `--color-app-{appId}-end` exist in `frontend/packages/ui/src/styles/theme.css` — if not, add them (see Step 2)
- [ ] An SVG icon exists at `frontend/packages/ui/static/icons/{skillIconName}.svg` — if not, add it (see Step 3)

---

### Step 1 — Create the folder

```
frontend/packages/ui/src/components/embeds/{appId}/
```

For example: `embeds/weather/`

---

### Step 2 — Add the app gradient to `theme.css` (if needed)

Open `frontend/packages/ui/src/styles/theme.css`. Search for `--color-app-{appId}`. If it does not exist, add it following the exact format used by every other app:

```css
/* App/{AppName} */
--color-app-{appId}-start: #RRGGBB;
--color-app-{appId}-end:   #RRGGBB;
--color-app-{appId}: linear-gradient(
  135deg,
  var(--color-app-{appId}-start) 9.04%,
  var(--color-app-{appId}-end) 90.06%
);
```

**Design rule:** Choose two colours that are visually distinct from the existing apps. Use saturated, medium-bright hues — not pastels, not near-black. The gradient always runs at 135°. Never hardcode gradient colours anywhere else; always reference these variables.

---

### Step 3 — Add the skill icon SVG (if needed)

Place a single-colour SVG (filled, no stroke) at:

```
frontend/packages/ui/static/icons/{skillIconName}.svg
```

The icon is rendered via `mask-image` + `background-color`, so it must be a solid shape (no transparency tricks). Size: any — it will be masked to `29 × 29 px`.

---

### Step 4 — Register the icon in `BasicInfosBar.svelte` and `EmbedHeader.svelte`

Both files maintain a list of `:global(.skill-icon[data-skill-icon="..."])` blocks that set the `mask-image`. Add your icon to both files:

```css
/* In BasicInfosBar.svelte AND EmbedHeader.svelte <style> blocks */
:global(.skill-icon[data-skill-icon="{skillIconName}"]) {
  -webkit-mask-image: url("@openmates/ui/static/icons/{skillIconName}.svg");
  mask-image: url("@openmates/ui/static/icons/{skillIconName}.svg");
```

> **Why global?** These components are mounted into the TipTap editor via `mount()`, which creates shadow-like component boundaries. Local scoped styles cannot reach them.

---

### Step 5 — Write the Preview component

**File:** `embeds/{appId}/{SkillName}EmbedPreview.svelte`

Full skeleton — replace `{SkillName}`, `{appId}`, `{skillId}`, `{skillIconName}`, and the skill-specific fields:

```svelte
<!--
  frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedPreview.svelte

  Preview card for {AppName} / {SkillName} skill embeds.
  Uses UnifiedEmbedPreview as base; provides skill-specific content via the `details` snippet.

  States:
  - processing: Shows query/title while skill is running (stop button shown by UnifiedEmbedPreview)
  - finished:   Shows key result data (counts, images, primary info)
  - error:      Shows error indicator in the details area
  - cancelled:  Dimmed card (handled by UnifiedEmbedPreview automatically)

  Real-time updates from 'processing' → 'finished' are handled by UnifiedEmbedPreview's
  embedUpdated listener. This component implements onEmbedDataUpdated to sync its local
  state when notified.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatSyncService } from '../../../services/chatSyncService';

  /**
   * Skill-specific result shape from the backend TOON content.
   * Add only the fields your preview actually uses — keep it minimal.
   */
  interface {SkillName}Result {
    // Example fields — replace with real fields from your skill:
    title?: string;
    url?: string;
    // ...
  }

  /**
   * Props — mirrors the fields AppSkillUseRenderer extracts from TOON content
   * and passes directly to this component via mount().
   */
  interface Props {
    /** Unique embed ID (from contentRef "embed:{uuid}") */
    id: string;
    /** Primary query/title shown in the preview (direct format) */
    query?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Skill results for finished state */
    results?: {SkillName}Result[];
    /** Task ID for full-response cancellation (fallback) */
    taskId?: string;
    /** Skill task ID for single-skill cancellation (preferred) */
    skillTaskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler that opens the fullscreen */
    onFullscreen?: () => void;
  }

  let {
    id,
    query: queryProp,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // ── Local state ─────────────────────────────────────────────────────────────
  // Mirror props in $state so onEmbedDataUpdated can update them reactively.
  // UnifiedEmbedPreview's embedUpdated listener calls onEmbedDataUpdated when
  // the server sends new embed data — props from mount() are static and cannot
  // be updated from outside. $state is the correct pattern here.

  let localQuery   = $state('');
  let localStatus  = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<{SkillName}Result[]>([]);
  let localTaskId  = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);

  // Initialize from props on first render and whenever they change (e.g., navigation)
  $effect(() => {
    localQuery       = queryProp || '';
    localStatus      = statusProp || 'processing';
    localResults     = resultsProp || [];
    localTaskId      = taskIdProp;
    localSkillTaskId = skillTaskIdProp;
  });

  // Derive display values from local state (single source of truth)
  let query       = $derived(localQuery);
  let status      = $derived(localStatus);
  let results     = $derived(localResults);
  let taskId      = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);

  // ── Embed data update callback ───────────────────────────────────────────────
  /**
   * Called by UnifiedEmbedPreview when it receives an embedUpdated event for this id.
   * Update ONLY the fields your preview cares about; ignore unknown fields.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (!c) return;
    if (typeof c.query === 'string') localQuery = c.query;
    if (Array.isArray(c.results)) localResults = c.results as {SkillName}Result[];
    if (typeof c.skill_task_id === 'string') localSkillTaskId = c.skill_task_id;
    // Add other skill-specific fields here
  }

  // ── Stop / cancel ────────────────────────────────────────────────────────────
  /**
   * Cancel this skill's execution.
   * Prefer skillTaskId (cancels just this skill; AI continues).
   * Fall back to taskId (cancels the entire AI response).
   */
  async function handleStop() {
    if (status !== 'processing') return;
    if (skillTaskId) {
      await chatSyncService.sendCancelSkill(skillTaskId, id).catch(err =>
        console.error('[{SkillName}EmbedPreview] Failed to cancel skill:', err)
      );
    } else if (taskId) {
      await chatSyncService.sendCancelAiTask(taskId).catch(err =>
        console.error('[{SkillName}EmbedPreview] Failed to cancel task:', err)
      );
    }
  }

  // ── Derived display values ───────────────────────────────────────────────────
  let skillName = $derived($text('embeds.{i18n_key}'));  // Add this key to embeds.yml (Step 8)
</script>

<UnifiedEmbedPreview
  {id}
  appId="{appId}"
  skillId="{skillId}"
  skillIconName="{skillIconName}"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <!--
      DETAILS AREA — visible inside the card above the BasicInfosBar.
      Design rules (see Design Guidelines below):
      - Primary info at the top (query/title, 16px bold, 3-line clamp)
      - Secondary info below (provider/subtitle, 14px, --color-grey-70)
      - Result indicators at bottom (icons, counts, thumbnails)
      - Never use fixed heights; let content flow within the card
    -->
    <div class="{appId}-{skillId}-details" class:mobile={isMobileLayout}>
      <div class="primary-text">{query}</div>

      {#if status === 'error'}
        <div class="error-indicator">{$text('chat.an_error_occured')}</div>
      {:else if status === 'finished'}
        <!-- Show key result summary here -->
        <div class="result-count">{results.length} results</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ── Details layout ─────────────────────────────────────────────────────── */

  .{appId}-{skillId}-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }

  /* Desktop: vertically center content in the card */
  .{appId}-{skillId}-details:not(.mobile) {
    justify-content: center;
  }

  /* Mobile: top-align content */
  .{appId}-{skillId}-details.mobile {
    justify-content: flex-start;
  }

  /* ── Typography ─────────────────────────────────────────────────────────── */

  .primary-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    /* Limit to 3 lines */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .{appId}-{skillId}-details.mobile .primary-text {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  /* ── Error state ─────────────────────────────────────────────────────────── */

  .error-indicator {
    font-size: 13px;
    color: var(--color-error);
    margin-top: 4px;
  }

  /* ── Skill icon ──────────────────────────────────────────────────────────── */
  /* Define BOTH preview and mobile variants. */

  :global(.unified-embed-preview .skill-icon[data-skill-icon="{skillIconName}"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/{skillIconName}.svg');
    mask-image: url('@openmates/ui/static/icons/{skillIconName}.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="{skillIconName}"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/{skillIconName}.svg');
    mask-image: url('@openmates/ui/static/icons/{skillIconName}.svg');
  }
</style>
```

---

### Step 6 — Write the Fullscreen component

**File:** `embeds/{appId}/{SkillName}EmbedFullscreen.svelte`

Full skeleton:

```svelte
<!--
  frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedFullscreen.svelte

  Fullscreen view for {AppName} / {SkillName} skill embeds.
  Uses UnifiedEmbedFullscreen as base.

  Layout:
  - EmbedTopBar (share / copy / close) — handled by UnifiedEmbedFullscreen
  - EmbedHeader (gradient banner with title + subtitle) — handled by UnifiedEmbedFullscreen
  - Scrollable content area — your `content` snippet

  Child embeds:
  - If results are stored as separate child embeds (typical for search results):
    Pass `embedIds` + `childEmbedTransformer` → UnifiedEmbedFullscreen loads them.
  - If all data is in the parent embed's TOON content:
    Use `legacyResults` or handle in onEmbedDataUpdated.

  Drill-down navigation:
  - When a result opens its own fullscreen view, render it inside <ChildEmbedOverlay>.
  - This keeps the parent result grid always mounted beneath (no re-animation on back).
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  // Import ChildEmbedOverlay only if you need drill-down child fullscreens:
  // import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import { text } from '@repo/ui';

  /**
   * Typed result object for the content snippet.
   * Produced by childEmbedTransformer (one entry per child embed).
   */
  interface {SkillName}Result {
    embed_id: string;
    title?: string;
    // ... skill-specific fields
  }

  interface Props {
    /** Primary heading shown in the gradient banner */
    query?: string;
    /** Subtitle shown below the heading (e.g., "via Brave Search", "Data from 2025-03-01") */
    subtitle?: string;
    /** Pipe-separated child embed IDs (or array) — loaded automatically by UnifiedEmbedFullscreen */
    embedIds?: string | string[];
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Close callback */
    onClose: () => void;
    /** Embed ID for the share button */
    embedId?: string;
    /** Navigation between sibling embeds in the same message */
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    /** Ultra-wide chat-button support */
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    query: queryProp,
    subtitle: subtitleProp,
    embedIds,
    status: statusProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  // ── Local state ─────────────────────────────────────────────────────────────
  let localQuery    = $state('');
  let localSubtitle = $state('');
  let localStatus   = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  // embedIdsOverride: updated by handleEmbedDataUpdated when new embed_ids arrive via streaming.
  // Use override ?? prop so the prop value is available immediately on mount (before any $effect).
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = queryProp    || '';
    localSubtitle = subtitleProp || '';
    localStatus   = statusProp   || 'finished';
  });

  let query    = $derived(localQuery);
  let subtitle = $derived(localSubtitle);
  let status   = $derived(localStatus);

  // ── Child embed transformer ──────────────────────────────────────────────────
  /**
   * Converts raw decoded TOON content of each child embed into a typed result.
   * Called once per child embed by UnifiedEmbedFullscreen.
   * Keep this pure (no side effects).
   */
  function transformToResult(embedId: string, content: Record<string, unknown>): {SkillName}Result {
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      // Map all fields your content snippet needs:
    };
  }

  // ── Embed data updates ───────────────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (typeof c.query === 'string') localQuery = c.query;
    if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
  }

  // ── Drill-down state (only if you have child fullscreens) ────────────────────
  // let selectedResult = $state<{SkillName}Result | null>(null);
  // function handleResultFullscreen(result: {SkillName}Result) { selectedResult = result; }
  // function handleResultClose() { selectedResult = null; }
</script>

<UnifiedEmbedFullscreen
  appId="{appId}"
  skillId="{skillId}"
  embedHeaderTitle={query}
  embedHeaderSubtitle={subtitle}
  onClose={onClose}
  skillIconName="{skillIconName}"
  showSkillIcon={true}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToResult}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const results = ctx.children as {SkillName}Result[]}

    {#if status === 'error'}
      <div class="error-state">
        <p class="error-title">Search failed</p>
      </div>
    {:else if results.length === 0}
      {#if ctx.isLoadingChildren}
        <div class="loading-state"><p>{$text('embeds.loading')}</p></div>
      {:else}
        <div class="no-results"><p>{$text('embeds.no_results')}</p></div>
      {/if}
    {:else}
      <div class="results-list">
        {#each results as result}
          <div class="result-item">
            <p>{result.title}</p>
            <!-- render your result card here -->
          </div>
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!--
  If you have a drill-down child fullscreen (e.g., opening a single result in fullscreen):

  {#if selectedResult}
    <ChildEmbedOverlay>
      <SomeChildEmbedFullscreen
        ...props from selectedResult...
        onClose={handleResultClose}
      />
    </ChildEmbedOverlay>
  {/if}
-->

<style>
  /* ── Loading / empty states ─────────────────────────────────────────────── */

  .loading-state,
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
  }

  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }

  /* ── Content grid / list ─────────────────────────────────────────────────── */

  .results-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px 16px;
    padding-bottom: 120px; /* Space for bottom bar + gradient */
    max-width: 800px;
    margin: 0 auto;
  }

  /* Use container queries (not viewport) for responsive layout: */
  @container fullscreen (min-width: 600px) {
    .results-list {
      /* e.g. two-column grid */
    }
  }

  /* ── Skill icon (for EmbedHeader / BasicInfosBar) ───────────────────────── */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="{skillIconName}"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/{skillIconName}.svg');
    mask-image: url('@openmates/ui/static/icons/{skillIconName}.svg');
  }
</style>
```

---

### Step 7 — Write the mock data files

These power the `/dev/preview/embeds/{appId}/{SkillName}EmbedPreview` development preview route.

**File:** `embeds/{appId}/{SkillName}EmbedPreview.preview.ts`

```typescript
/**
 * Preview mock data for {SkillName}EmbedPreview.
 * Access at: /dev/preview/embeds/{appId}/{SkillName}EmbedPreview
 */

const defaultProps = {
  id: "preview-{appId}-{skillId}-1",
  query: "example query",
  status: "finished" as const,
  results: [
    { title: "Result 1", url: "https://example.com/1" },
    { title: "Result 2", url: "https://example.com/2" },
  ],
  isMobile: false,
  onFullscreen: () => console.log("[Preview] Fullscreen clicked"),
};

export default defaultProps;

/** Named variants — ALL FOUR are required */
export const variants = {
  /** Loading animation */
  processing: {
    id: "preview-{appId}-{skillId}-processing",
    query: "loading...",
    status: "processing" as const,
    results: [],
    isMobile: false,
  },
  /** Error indicator */
  error: {
    id: "preview-{appId}-{skillId}-error",
    query: "failed query",
    status: "error" as const,
    results: [],
    isMobile: false,
  },
  /** Cancelled state */
  cancelled: {
    id: "preview-{appId}-{skillId}-cancelled",
    query: "cancelled",
    status: "cancelled" as const,
    results: [],
    isMobile: false,
  },
  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-{appId}-{skillId}-mobile",
    isMobile: true,
  },
};
```

Create an equivalent `{SkillName}EmbedFullscreen.preview.ts` file with fullscreen-specific props.

---

### Step 8 — Add i18n strings

Open `frontend/packages/ui/src/i18n/sources/embeds.yml` and add an entry for the skill label shown in `BasicInfosBar`. The key becomes `$text('embeds.{i18n_key}')` in your Preview component.

```yaml
{i18n_key}:
  context: {AppName} {SkillName} skill label
  en: {SkillLabel}
  de: {Translation}
  zh: {Translation}
  es: {Translation}
  fr: {Translation}
  pt: {Translation}
  ru: {Translation}
  ja: {Translation}
  ko: {Translation}
  it: {Translation}
  tr: {Translation}
  vi: {Translation}
  id: {Translation}
  pl: {Translation}
  nl: {Translation}
  ar: {Translation}
  hi: {Translation}
  th: {Translation}
  cs: {Translation}
  sv: {Translation}
  verified_by_human: []
```

**All 20 locales are required.** Do not skip any. See `docs/contributing/guides/i18n.md` and `docs/contributing/guides/manage-translations.md`.

---

### Step 9 — Register in `AppSkillUseRenderer.ts`

**File:** `frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts`

**9a — Add the import** at the top of the file alongside the other skill imports:

```typescript
import {SkillName}EmbedPreview from '../../../embeds/{appId}/{SkillName}EmbedPreview.svelte';
```

**9b — Add the routing block** in the `render()` method, before the generic fallback `renderGenericSkill()` call:

```typescript
// For {appId} {skillId}, render {SkillName} preview using Svelte component
if (appId === '{appId}' && skillId === '{skillId}') {
  return this.render{SkillName}Component(attrs, embedData, decodedContent, content);
```

**9c — Add the render method** at the bottom of the class, following the exact pattern of every existing render method:

```typescript
/**
 * Render {SkillName} embed preview using Svelte component.
 */
private render{SkillName}Component(
  attrs: EmbedNodeAttributes,
  embedData: any,
  decodedContent: any,
  content: HTMLElement,
): void {
  const query      = decodedContent?.query      || (attrs as any).query || '';
  const status     = embedData?.status          || attrs.status         || 'processing';
  const taskId     = decodedContent?.task_id    || '';
  const skillTaskId = decodedContent?.skill_task_id || '';
  const results    = decodedContent?.results    || [];
  // Add other fields your preview needs:

  const embedId = attrs.contentRef?.startsWith('embed:')
    ? attrs.contentRef.replace('embed:', '')
    : (attrs.id ?? '');

  // Unmount any previously mounted instance on this DOM node
  const existing = mountedComponents.get(content);
  if (existing) {
    try { unmount(existing); } catch {}
  }
  content.innerHTML = '';

  const handleFullscreen = () => {
    document.dispatchEvent(new CustomEvent('embedfullscreen', {
      bubbles: true,
      detail: {
        embedType: 'app-skill-use',
        embedId,
        appId:    '{appId}',
        skillId:  '{skillId}',
        attrs,
        embedData,
        decodedContent: { ...decodedContent, query, status },
      },
    }));
  };

  const component = mount({SkillName}EmbedPreview, {
    target: content,
    props: {
      id: embedId,
      query,
      status,
      results,
      taskId,
      skillTaskId,
      isMobile: false,
      onFullscreen: handleFullscreen,
    },
  });

  mountedComponents.set(content, component);

  console.debug('[AppSkillUseRenderer] Mounted {SkillName}EmbedPreview:', {
    embedId, query, status,
  });
```

---

### Step 10 — Fullscreen registration (automatic — no ActiveChat changes needed)

Fullscreen routing is **data-driven** via `embedFullscreenResolver.ts` and `embedRegistry.generated.ts`. When your preview fires an `embedfullscreen` DOM event, `ActiveChat.svelte` automatically:

1. Calls `resolveRegistryKey()` to map `app_id + skill_id` → `"app:{appId}:{skillId}"` registry key
2. Looks up the component path in `EMBED_FULLSCREEN_COMPONENTS` (auto-generated from `app.yml`)
3. Lazy-loads your fullscreen component via `loadFullscreenComponent()`
4. Renders it with a standardized `data: EmbedFullscreenRawData` prop

**You do NOT need to:**
- Add branches to `ActiveChat.svelte`
- Manually extract fields and pass individual props
- Register fullscreen cases by hand

**Your fullscreen component must:**
- Accept `data: EmbedFullscreenRawData` as a required prop (import from `types/embedFullscreen.ts`)
- Extract its own fields from `data.decodedContent` using `$derived()` with type guards
- Use `UnifiedEmbedFullscreen` as the base wrapper
- Be the default export of `{SkillName}EmbedFullscreen.svelte`

> Architecture: `docs/architecture/frontend/data-driven-embed-fullscreen-routing.md`

---

### Step 10b — Register in `GroupRenderer.ts` (if the skill produces groupable child embeds)

Some skills produce **groups** of child embeds (e.g., a "travel search" skill produces multiple `travel-connection` child embeds). These child embed types flow through `GroupRenderer.ts` instead of `AppSkillUseRenderer.ts`. If your skill has a child type listed in `EMBED_GROUPABLE_TYPES` in `embedRegistry.generated.ts`, you **must** register it in `GroupRenderer` as well.

**File:** `frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts`

There are three places to update:

**10b-1 — Add import at top of file:**

```typescript
import {ChildSkillName}EmbedPreview from '../../../embeds/{appId}/{ChildSkillName}EmbedPreview.svelte';
```

**10b-2 — Add to `individualMounters` Map in the constructor:**

```typescript
this.individualMounters.set('{child-type-string}', (item, embedData, decodedContent, content) =>
  this.render{ChildSkillName}Component(item, embedData, decodedContent, content),
);
```

**10b-3 — Add a case to `renderItemContent()` switch (HTML fallback):**

```typescript
case '{child-type-string}':
  return this.render{ChildSkillName}Item(item, embedData, decodedContent);
```

**10b-4 — Add to `getGroupDisplayName()` map:**

```typescript
'{child-type-string}': $text('embeds.{i18n_key}'),
```

**10b-5 — Add the two render methods:**

```typescript
/**
 * Render {ChildSkillName} embed using Svelte component (individual group item).
 */
private async render{ChildSkillName}Component(
  attrs: EmbedNodeAttributes,
  embedData: any,
  decodedContent: any,
  content: HTMLElement,
): Promise<void> {
  const embedId = attrs.contentRef?.startsWith('embed:')
    ? attrs.contentRef.replace('embed:', '')
    : (attrs.id ?? '');

  // NOTE: onFullscreen is intentionally undefined here if no dedicated
  // top-level fullscreen exists (child-overlay-only fullscreens in
  // parent group embeds should not be duplicated as standalone routes).

  const component = mount({ChildSkillName}EmbedPreview, {
    target: content,
    props: {
      id: embedId,
      status: (embedData?.status || decodedContent?.status || 'finished') as 'processing' | 'finished' | 'error' | 'cancelled',
      // Map fields from decodedContent:
      isMobile: false,
      onFullscreen: undefined,
    },
  });
  this.groupMountedComponents.set(content, component);

/**
 * HTML fallback for {ChildSkillName} embeds (used by renderItemContent switch).
 */
private async render{ChildSkillName}Item(
  _item: EmbedNodeAttributes,
  _embedData?: any,
  decodedContent: any = null,
): Promise<string> {
  const title = decodedContent?.title || '{ChildSkillName}';
  return `
    <div class="embed-app-icon {appId}">
      <span class="icon icon_{appId}"></span>
    </div>
    <div class="embed-content">
      <div class="embed-title">${title}</div>
    </div>
  `;
```

> **Startup warning:** The `GroupRenderer` constructor checks all `EMBED_GROUPABLE_TYPES` against `individualMounters` at startup and logs `[GroupRenderer] WARNING: No individual mounter registered for type "..."` for any missing registration. If you see this warning in the browser console, add the missing mounter.

---

### Step 11 — Verify in dev preview

Start the frontend dev server and visit:

```
/dev/preview/embeds/{appId}/{SkillName}EmbedPreview
```

Verify all four state variants (`processing`, `finished`, `error`, `cancelled`) and the `mobile` variant look correct before integrating with the backend.

---

## Complete Registration Checklist (App-Skill-Use)

Use this checklist when adding any new app-skill-use embed. Every item must be completed for the embed to work end-to-end.

### Files you MUST touch

| File                                                                                                  | What to add                                                        | Required?         |
| ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ----------------- |
| `frontend/packages/ui/src/styles/theme.css`                                                           | `--color-app-{appId}-start/end` gradient vars                      | Yes (if new app)  |
| `frontend/packages/ui/static/icons/{skillIconName}.svg`                                               | Skill icon SVG                                                     | Yes (if new icon) |
| `frontend/packages/ui/src/components/embeds/{appId}/`                                                 | New folder + Preview + Fullscreen `.svelte` files                  | Yes               |
| `frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedPreview.svelte`                   | Preview component using `UnifiedEmbedPreview`                      | Yes               |
| `frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedFullscreen.svelte`                | Fullscreen using `UnifiedEmbedFullscreen`                          | Yes               |
| `frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedPreview.preview.ts`               | Dev preview mock data                                              | Yes               |
| `frontend/packages/ui/src/components/embeds/{appId}/{SkillName}EmbedFullscreen.preview.ts`            | Dev preview mock data                                              | Yes               |
| `frontend/packages/ui/src/components/BasicInfosBar.svelte`                                            | `:global(.skill-icon[...])` CSS block                              | Yes               |
| `frontend/packages/ui/src/components/EmbedHeader.svelte`                                              | `:global(.skill-icon[...])` CSS block                              | Yes               |
| `frontend/packages/ui/src/i18n/sources/embeds.yml`                                                    | Skill label for all 20 locales                                     | Yes               |
| `frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts` | Import + routing block + render method                             | Yes               |
| `frontend/packages/ui/src/data/embedRegistry.generated.ts`                                            | Entry in `EMBED_FULLSCREEN_COMPONENTS` (auto-generated from `app.yml` — verify it's there) | Yes (auto)        |

### If your skill produces groupable child embeds

If `EMBED_GROUPABLE_TYPES` in `embedRegistry.generated.ts` includes any child type from your skill, also touch:

| File               | What to add                                                                                                          |
| ------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `GroupRenderer.ts` | Import + `individualMounters.set(...)` + `renderItemContent()` case + `getGroupDisplayName()` entry + render methods |
| `groupHandlers.ts` | Handler registered for the parent group type                                                                         |

### Quick audit command

To check if a type is missing from any registration point, run:

```bash
# Check if a type is in embedRegistry
grep -n '"travel-connection"' frontend/packages/ui/src/data/embedRegistry.generated.ts

# Check if GroupRenderer handles it
grep -n 'travel-connection' frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts

# Check if groupHandlers handles it
grep -n 'travel-connection' frontend/packages/ui/src/message_parsing/groupHandlers.ts

# Check if ActiveChat has a fullscreen case
grep -n 'travel' frontend/apps/web_app/src/routes/\(authenticated\)/chat/\[chatId\]/ActiveChat.svelte
```

---

## Part 2: Creating a Direct-Type Embed

Direct-type embeds (recordings, uploaded files, user-inserted objects) bypass the `AppSkillUseRenderer` and have their own renderer class.

### Step 1 — Decide the type string

Choose a short, lowercase, hyphen-separated type string (e.g., `"spreadsheet"`, `"voice-clip"`). This becomes the key in the `embedRenderers` registry and the `type` field in the embed JSON reference.

### Step 2 — Create the Svelte components

Same structure as app-skill-use — see Part 1 Steps 5 and 6. The Preview and Fullscreen components are identical in shape; only the props differ.

### Step 3 — Create a Renderer class

**File:** `embed_renderers/{TypeName}Renderer.ts`

```typescript
// {TypeName}Renderer.ts
// Renderer for "{type-string}" embed nodes in the TipTap editor.

import type { EmbedRenderer, EmbedRenderContext } from './types';
import type { EmbedNodeAttributes } from '../../../../message_parsing/types';
import { mount, unmount } from 'svelte';
import {TypeName}EmbedPreview from '../../../embeds/{folder}/{TypeName}EmbedPreview.svelte';

const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

export class {TypeName}Renderer implements EmbedRenderer {
  type = '{type-string}';

  render(context: EmbedRenderContext): void | Promise<void> {
    const { content, attrs } = context;

    // Unmount any existing component
    const existing = mountedComponents.get(content);
    if (existing) {
      try { unmount(existing); } catch {}
    }
    content.innerHTML = '';

    try {
      const embedId = attrs.contentRef?.startsWith('embed:')
        ? attrs.contentRef.replace('embed:', '')
        : (attrs.id ?? '');

      const handleFullscreen = () => {
        document.dispatchEvent(new CustomEvent('{type-string}fullscreen', {
          bubbles: true,
          detail: { embedId, attrs },
        }));
      };

      const component = mount({TypeName}EmbedPreview, {
        target: content,
        props: {
          id: embedId,
          status: (attrs.status as 'processing' | 'finished' | 'error') || 'finished',
          isMobile: false,
          onFullscreen: handleFullscreen,
          // Add type-specific props from attrs:
        },
      });

      mountedComponents.set(content, component);
    } catch (error) {
      console.error('[{TypeName}Renderer] Error mounting preview:', error);
      content.innerHTML = `<div style="padding:8px;font-size:12px;color:var(--color-grey-50)">{TypeName} unavailable</div>`;
    }
  }

  update(context: EmbedRenderContext): boolean {
    this.render(context);
    return true;
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    if (attrs.contentRef?.startsWith('embed:')) {
      const embed_id = attrs.contentRef.replace('embed:', '');
      return `\`\`\`json\n${JSON.stringify({ type: '{type-string}', embed_id })}\n\`\`\``;
    }
    return '';
  }
```

### Step 4 — Register in `index.ts`

**File:** `embed_renderers/index.ts`

```typescript
import { {TypeName}Renderer } from './{TypeName}Renderer';

export const embedRenderers: EmbedRendererRegistry = {
  // ... existing entries ...
  '{type-string}': new {TypeName}Renderer(),
};
```

### Step 5 — Register in `embedParsing.ts` (if needed)

If the embed type is inserted by the client (not streamed from the server), ensure `embedParsing.ts` can recognise the JSON reference block and produce the correct `EmbedNodeAttributes`. Check whether a new `type` case needs adding to the parser.

### Step 6 — Register TipTap node attributes (if needed)

If your embed carries extra data in the TipTap node attributes beyond the base `EmbedNodeAttributes` (like `MapLocationRenderer` uses `preciseLat`, `preciseLon`), add these as additional attributes in `Embed.ts`.

---

## Design Guidelines

These rules are derived from the actual measurements and patterns across all existing embeds. Follow them exactly — do not deviate without a design review.

### Card Anatomy (Preview)

```
┌─────────────────────────────────────┐  ← 300px wide (desktop)
│                                     │
│  [details snippet — your content]   │  ← Flex column, gap 4px
│                                     │     Desktop: justify-content center
│                                     │     Mobile:  justify-content flex-start
├─────────────────────────────────────┤
│  [BasicInfosBar]                    │  ← Always rendered by UnifiedEmbedPreview
│  App icon  Skill name  Status text  │     You never touch this
└─────────────────────────────────────┘
   300px × 200px desktop / 150px × 290px mobile
```

The `details` snippet fills the space **above** the BasicInfosBar. It receives `{ isMobile: boolean }` and is responsible for all the skill-specific visual content.

### Fullscreen Anatomy

```
┌─────────────────────────────────────────────────────┐
│  [EmbedTopBar — share / copy / close]               │  ← Always rendered
├─────────────────────────────────────────────────────┤
│  [EmbedHeader — gradient banner]                    │  ← Always rendered
│   Skill icon  Title  Subtitle                       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  [content snippet — your results grid/list]         │  ← Scrollable
│                                                     │
│  padding-bottom: 120px  ← space for bottom bar      │
└─────────────────────────────────────────────────────┘
```

### Typography Scale

| Use                                 | Size   | Weight | Color                   |
| ----------------------------------- | ------ | ------ | ----------------------- |
| Primary info (query, title)         | `16px` | `600`  | `var(--color-grey-100)` |
| Secondary info (subtitle, provider) | `14px` | `400`  | `var(--color-grey-70)`  |
| Tertiary / counts                   | `14px` | `500`  | `var(--color-grey-70)`  |
| Mobile primary                      | `14px` | `600`  | `var(--color-grey-100)` |
| Mobile secondary                    | `12px` | `400`  | `var(--color-grey-70)`  |
| Error title (fullscreen)            | `18px` | `600`  | `var(--color-error)`    |
| Error message (fullscreen)          | `14px` | `400`  | line-height 1.4         |

### Spacing

| Context                        | Value                                     |
| ------------------------------ | ----------------------------------------- |
| Details inner gap              | `4px`                                     |
| Results grid gap               | `16px`                                    |
| Fullscreen content padding     | `24px 16px`                               |
| Fullscreen padding-bottom      | `120px` (space for bottom bar + gradient) |
| Error margin-top               | `6px`                                     |
| Max content width (fullscreen) | `800px–1000px` centred                    |

### Colour Rules

- **App gradient:** always `var(--color-app-{appId})` — defined in `theme.css`. Never hardcode hex values in component styles.
- **Text primary:** `var(--color-grey-100)`
- **Text secondary:** `var(--color-grey-70)` or `var(--color-font-secondary)`
- **Error background:** `rgba(var(--color-error-rgb), 0.08)` with `1px solid rgba(var(--color-error-rgb), 0.3)`
- **Error text:** `var(--color-error)`

### External Images — Always Proxy

**NEVER load external images directly.** Import helpers from `utils/imageProxy.ts`. See `docs/contributing/guides/image-proxy.md` for the full API, max-width presets, and anti-patterns.

```typescript
import { proxyImage, proxyFavicon, MAX_WIDTH_FAVICON } from '../../../utils/imageProxy';
// Use: proxyImage(url, MAX_WIDTH_PREVIEW_THUMBNAIL)
```

### Status States

| Status       | Visual behaviour                                                                        |
| ------------ | --------------------------------------------------------------------------------------- |
| `processing` | Shimmer/loading (handled by `UnifiedEmbedPreview`). Show query/title text if available. |
| `finished`   | Full interactive card. Clicking opens fullscreen. Tilt-hover effect active.             |
| `error`      | Red error indicator in details area. Card is NOT clickable.                             |
| `cancelled`  | Dimmed card (handled by `UnifiedEmbedPreview`). Show what was cancelled.                |

Do **not** replicate the shimmer, the hover tilt, or the cancel visual in your component — `UnifiedEmbedPreview` handles all of these via CSS class toggling on the card root.

### Responsive Layout

- Use **CSS container queries** (not viewport `@media`) for layout changes inside the fullscreen, because the fullscreen can be narrow even on wide viewports (split view):
  ```css
  @container fullscreen (max-width: 500px) { ... }
  ```
- Mobile vs desktop within the preview card is controlled by the `isMobile` boolean passed into the `details` snippet — add `.mobile` class modifier to your wrapper div and use it to adjust font sizes and layout.

### Text Overflow

Long text **must** be clamped. Use this pattern:

```css
.primary-text {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
```

---

## What NOT to Do (Anti-Patterns)

### Never subscribe to `embedUpdated` yourself

`UnifiedEmbedPreview` already subscribes to `chatSyncService` `embedUpdated` events and calls your `onEmbedDataUpdated` callback. **Do not add another listener in your skill component** — it creates duplicate processing and memory leaks.

```svelte
<!-- WRONG — never do this in a skill component -->
<script>
  import { onMount, onDestroy } from 'svelte';
  import { chatSyncService } from '...';
  onMount(() => {
    chatSyncService.addEventListener('embedUpdated', handler);  // ❌
  });
</script>
```

### Never use `$:` reactive statements

This is Svelte 4 syntax. Use `$derived()` and `$effect()` only.

```typescript
// WRONG
$: query = queryProp || ""; // ❌

// CORRECT
let query = $derived(localQuery); // ✅
```

### Never hardcode colours

```css
/* WRONG */
.my-header {
  background: linear-gradient(135deg, #de1e66, #ff763b);
} /* ❌ */

/* CORRECT */
.my-header {
  background: var(--color-app-web);
} /* ✅ */
```

### Never call `resolveEmbed` in your skill component

`UnifiedEmbedPreview` handles all embed store lookups. Your component receives data via `onEmbedDataUpdated`. If you need to load child embeds in the preview (like `WebSearchEmbedPreview` does for favicons), use `loadEmbedsWithRetry` from `embedResolver` — but only for supplementary data, not for the primary embed content.

### Never duplicate BasicInfosBar

`UnifiedEmbedPreview` always renders `BasicInfosBar` below the details snippet. Do not render another status bar, icon row, or label inside your `details` snippet.

### Never add `isMobile` detection via JS in fullscreen

The fullscreen container has a CSS `container` named `fullscreen`. Use `@container fullscreen (max-width: ...)` for all layout breakpoints. Do not read `window.innerWidth` or pass `isMobile` to fullscreen components (unlike preview components, fullscreen is never used in the mobile card layout).

---

## Inline Badge → Child Embed Auto-Open (`initialChildEmbedId`)

When a user clicks an **inline embed link** (e.g., `[Mad Cool 2024 Aftermovie](embed:youtube.com-sss)`) that points to a **child embed** inside a search result, the flow is:

1. `EmbedInlineLink.handleClick()` → `embedStore.resolveFullscreenTarget(childId)` → returns `{ targetEmbedId: parentSearchId, focusChildEmbedId: childId }`
2. `ActiveChat.handleEmbedFullscreen()` stores `focusChildEmbedId` in `embedFullscreenData`
3. The parent search fullscreen receives it as `initialChildEmbedId` prop

### How it works (unified in `UnifiedEmbedFullscreen`)

The auto-open logic lives **in `UnifiedEmbedFullscreen.svelte`**, not in each consumer. This eliminates duplicated boilerplate across all search fullscreens:

1. **`initialChildEmbedId?: string`** — prop passed from `ActiveChat.svelte` via `embedFullscreenData.focusChildEmbedId`
2. **`onAutoOpenChild?: (index: number, children: unknown[]) => void`** — callback invoked when the matching child is found
3. After `loadChildEmbeds()` finishes and `onChildrenLoaded` fires, UnifiedEmbedFullscreen searches for `initialChildEmbedId` in the loaded children. If found, it calls `onAutoOpenChild(index, children)` exactly once (guarded by `_autoOpenChildFired`).

### Required implementation in each search fullscreen

Every search fullscreen that has a drill-down overlay (child fullscreen) **MUST** implement these three things:

```svelte
<UnifiedEmbedFullscreen
  ...
  {initialChildEmbedId}
  onAutoOpenChild={(index, children) => {
    // 1. Populate the local results array for sibling navigation
    allResults = children as MyResultType[];
    // 2. Open the child overlay at the matching index
    const item = allResults[index];
    if (item) handleItemFullscreen(item);
  }}
  onChildrenLoaded={(children) => {
    // Populate results for manual clicks (when no initialChildEmbedId)
    allResults = children as MyResultType[];
  }}
>
```

Additionally, the **close handlers** must check `initialChildEmbedId`:

```typescript
// When child overlay is closed:
function handleChildClose() {
  if (initialChildEmbedId) {
    // Opened via inline badge — close the ENTIRE fullscreen (no parent grid)
    onClose();
  } else {
    // Opened via card click — return to parent results grid
    selectedIndex = -1;
  }

// When main close button is clicked:
function handleMainClose() {
  if (selectedIndex >= 0 && !initialChildEmbedId) {
    selectedIndex = -1; // Close child overlay first
  } else {
    onClose(); // Close entire fullscreen
  }
```

### ActiveChat.svelte: passing the prop

In `ActiveChat.svelte`, every search fullscreen mount **MUST** include:

```svelte
initialChildEmbedId={embedFullscreenData.focusChildEmbedId ?? undefined}
```

### Checklist for new search fullscreens

- [ ] Add `initialChildEmbedId?: string` to Props interface
- [ ] Destructure `initialChildEmbedId` from `$props()`
- [ ] Pass `{initialChildEmbedId}` to `<UnifiedEmbedFullscreen>`
- [ ] Pass `onAutoOpenChild` callback that opens the child overlay
- [ ] Pass `onChildrenLoaded` callback that populates local results array
- [ ] Check `initialChildEmbedId` in child close handler (close entire fullscreen vs return to grid)
- [ ] Check `initialChildEmbedId` in main close handler (same logic)
- [ ] In `ActiveChat.svelte`, pass `initialChildEmbedId={embedFullscreenData.focusChildEmbedId ?? undefined}`

---

## Canonical Reference: `web/search`

When in doubt, treat `WebSearchEmbedPreview.svelte` and `WebSearchEmbedFullscreen.svelte` as the canonical examples. They implement every pattern described in this document:

- `$state` / `$derived` / `$effect` runes
- `onEmbedDataUpdated` with all field updates
- Skill-level cancel (`sendCancelSkill`) with task-level fallback
- Child embed loading via `childEmbedTransformer`
- Drill-down overlay via `ChildEmbedOverlay`
- External image proxying
- Text clamping
- Container query responsive layout

---

## Linking back to CLAUDE.md

Add this entry to the **Required Documents by Trigger** section of `CLAUDE.md`:

```markdown
#### `docs/contributing/guides/add-embed-type.md`

**MUST READ when ANY of these are true:**

- You are creating a new embed type (Preview + Fullscreen component pair)
- You are adding a new `app_id` / `skill_id` to the embed renderer routing
- You are creating a new direct-type embed renderer class
- You are modifying how embed cards render in the chat message stream
```
