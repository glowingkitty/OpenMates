# Data-Driven Embed Fullscreen Routing

## Problem

`ActiveChat.svelte` has a ~940-line manual if/else chain (lines ~10192-11140) mapping embed types to fullscreen components. Every new embed type requires:
1. Adding a branch to this chain
2. Manually extracting fields from `decodedContent` with type coercion
3. Manually passing `initialChildEmbedId` for search embeds

This caused 6 missing branches and 3 missing `initialChildEmbedId` passthroughs (OPE-256). The current coverage check script catches gaps but doesn't prevent them.

## Solution

Replace the if/else chain with dynamic component resolution using the existing `embedRegistry.generated.ts`. Each fullscreen component accepts a standardized `data` prop and extracts its own fields internally.

## Architecture

```
ActiveChat.svelte
  │
  ▼
resolveRegistryKey(embedType, decodedContent)
  │  → "app:health:search_appointments" or "health-appointment"
  ▼
loadFullscreenComponent(registryKey)
  │  → dynamic import from EMBED_FULLSCREEN_COMPONENTS map
  ▼
<svelte:component this={Component} {data} {...commonProps} />
```

### ~940 lines replaced by ~30:

```svelte
{@const registryKey = resolveRegistryKey(embedType, decodedContent)}
{#if registryKey && hasFullscreenComponent(registryKey)}
  {#await loadFullscreenComponent(registryKey) then Component}
    <svelte:component
      this={Component}
      data={{
        decodedContent: embedFullscreenData.decodedContent ?? {},
        attrs: embedFullscreenData.attrs,
        embedData: embedFullscreenData.embedData,
        focusChildEmbedId: embedFullscreenData.focusChildEmbedId,
      }}
      embedId={embedFullscreenData.embedId}
      onClose={handleCloseEmbedFullscreen}
      {hasPreviousEmbed}
      {hasNextEmbed}
      onNavigatePrevious={handleNavigatePreviousEmbed}
      onNavigateNext={handleNavigateNextEmbed}
      navigateDirection={embedNavigateDirection}
      showChatButton={showChatButtonInFullscreen}
      onShowChat={handleShowChat}
    />
  {/await}
{:else}
  <div class="embed-fullscreen-fallback">...</div>
{/if}
```

## Files to Create

### 1. `frontend/packages/ui/src/types/embedFullscreen.ts`

Shared interfaces for the data-driven pattern:

```typescript
/** Raw embed data passed to every fullscreen component */
export interface EmbedFullscreenRawData {
  decodedContent: Record<string, unknown>;
  attrs?: Record<string, unknown>;
  embedData?: Record<string, unknown>;
  focusChildEmbedId?: string | null;
  restoreFromPip?: boolean;
}

/** Common props ALL fullscreen components share */
export interface EmbedFullscreenCommonProps {
  onClose: () => void;
  embedId?: string;
  hasPreviousEmbed?: boolean;
  hasNextEmbed?: boolean;
  onNavigatePrevious?: () => void;
  onNavigateNext?: () => void;
  navigateDirection?: 'previous' | 'next' | null;
  showChatButton?: boolean;
  onShowChat?: () => void;
}
```

### 2. `frontend/packages/ui/src/services/embedFullscreenResolver.ts`

Registry lookup + dynamic import:

```typescript
import { EMBED_FULLSCREEN_COMPONENTS } from '../data/embedRegistry.generated';

export function resolveRegistryKey(
  embedType: string,
  decodedContent?: Record<string, unknown>
): string | null {
  if (embedType === 'app-skill-use') {
    const appId = decodedContent?.app_id;
    const skillId = decodedContent?.skill_id;
    if (typeof appId === 'string' && typeof skillId === 'string') {
      return `app:${appId}:${skillId}`;
    }
    return null;
  }
  return embedType;
}

export function hasFullscreenComponent(key: string): boolean {
  return key in EMBED_FULLSCREEN_COMPONENTS;
}

// Use import.meta.glob for Vite compatibility
const modules = import.meta.glob(
  '../components/embeds/**/*EmbedFullscreen.svelte'
);

export async function loadFullscreenComponent(key: string) {
  const path = EMBED_FULLSCREEN_COMPONENTS[key];
  if (!path) return null;
  const importPath = `../components/embeds/${path}`;
  const loader = modules[importPath];
  if (!loader) return null;
  const module = await loader();
  return (module as { default: unknown }).default;
}
```

## Component Migration Pattern

Each fullscreen component adds a `data` prop and extracts fields internally. Existing direct props kept during migration for backward compatibility.

### Before (ActiveChat extracts fields):
```svelte
<!-- In ActiveChat.svelte — 20 lines per component -->
<HealthSearchEmbedFullscreen
  query={embedFullscreenData.decodedContent?.query || ''}
  provider={embedFullscreenData.decodedContent?.provider || 'Doctolib'}
  embedIds={embedFullscreenData.decodedContent?.embed_ids || ...}
  results={Array.isArray(...) ? ... : []}
  status={normalizeEmbedStatus(...)}
  errorMessage={typeof ... === 'string' ? ... : ''}
  embedId={embedFullscreenData.embedId}
  initialChildEmbedId={embedFullscreenData.focusChildEmbedId ?? undefined}
  onClose={handleCloseEmbedFullscreen}
  ...
/>
```

### After (component extracts its own fields):
```svelte
<!-- In the component's <script> -->
let { data, onClose, embedId, ...nav }: Props = $props();

let query = $derived(
  typeof data?.decodedContent?.query === 'string'
    ? data.decodedContent.query : ''
);
let initialChildEmbedId = $derived(
  data?.focusChildEmbedId ?? undefined
);
```

## Migration Waves (Incremental)

During migration, ActiveChat uses a hybrid gate — migrated components go through the data-driven path, others through the legacy if/else:

```typescript
const DATA_DRIVEN_COMPONENTS = new Set<string>([
  // Grows with each wave
]);
```

### Wave 1: Simple direct types (5 components)
- `RecordingEmbedFullscreen` — few fields
- `PDFEmbedFullscreen` — 2 fields  
- `MathPlotEmbedFullscreen` — 2 fields
- `MathCalculateEmbedFullscreen` — 3 fields
- `MailEmbedFullscreen` — 4 fields

### Wave 2: Content-display with PII (3 components)
- `CodeEmbedFullscreen`
- `DocsEmbedFullscreen`
- `SheetEmbedFullscreen`

### Wave 3: Search-pattern components (8 components)
All use `SearchResultsTemplate` — same migration pattern:
- `WebSearchEmbedFullscreen`, `NewsSearchEmbedFullscreen`, `VideosSearchEmbedFullscreen`
- `MapsSearchEmbedFullscreen`, `ImagesSearchEmbedFullscreen`, `EventsSearchEmbedFullscreen`
- `HealthSearchEmbedFullscreen`, `HomeSearchEmbedFullscreen`, `ShoppingSearchEmbedFullscreen`
- `TravelSearchEmbedFullscreen`, `TravelStaysEmbedFullscreen`

### Wave 4: Child-embed fullscreen components (7 components)
- `WebsiteEmbedFullscreen`, `HealthAppointmentEmbedFullscreen`, `HomeListingEmbedFullscreen`
- `TravelConnectionEmbedFullscreen`, `TravelStayEmbedFullscreen`
- `EventEmbedFullscreen`, `ImageResultEmbedFullscreen`

### Wave 5: Complex/special components (remaining ~8)
- `ImageGenerateEmbedFullscreen`, `VideoEmbedFullscreen` (restoreFromPip)
- `MapsLocationEmbedFullscreen`, `MapLocationEmbedFullscreen`
- `TravelFlightDetailsEmbedFullscreen`, `ReminderEmbedFullscreen`
- `VideoTranscriptEmbedFullscreen`, `WebReadEmbedFullscreen`, `CodeGetDocsEmbedFullscreen`

## Edge Cases

### `app-skill-use` routing
Handled by `resolveRegistryKey()` — combines `appId + skillId` into `"app:{appId}:{skillId}"` registry key.

### `normalizeEmbedType`
Replace the local hardcoded function in ActiveChat with the generated one from `embedRegistry.generated.ts`.

### `validTopLevelEmbedTypes` 
Replace hardcoded `Set` with registry-derived:
```typescript
const validTopLevelEmbedTypes = new Set(
  Object.keys(EMBED_FULLSCREEN_COMPONENTS).filter(k => !k.startsWith('app:'))
);
```

### Video PiP `restoreFromPip`
Included in `EmbedFullscreenRawData`, component extracts it.

## Type Safety

Type safety is **preserved but relocated**:
- Today: ActiveChat coerces `Record<string, unknown>` → typed props at the call site
- After: Each component coerces `data.decodedContent` → typed fields internally using generated content interfaces from `embedRegistry.generated.ts`

The generated `*EmbedContent` interfaces (e.g., `WebSearchEmbedContent`) already exist in the registry and provide the same guarantees.

## Cleanup After Full Migration

Delete from ActiveChat:
- ~940 lines of if/else routing
- ~30 static fullscreen component imports
- `get*Results` type-cast helpers (lines 1093-1123)
- `ActiveChat*Result` type aliases (lines 325-416)
- `EmbedDecodedContent` local type alias (lines 215-250)

## Verification

1. `scripts/check_embed_fullscreen_coverage.sh` passes
2. Each migrated wave: verify fullscreen opens correctly for every embed type in that wave
3. Verify inline badge clicks auto-focus child embeds (initialChildEmbedId)
4. Verify embed prev/next navigation still works
5. Verify deep link to specific embeds via URL hash
