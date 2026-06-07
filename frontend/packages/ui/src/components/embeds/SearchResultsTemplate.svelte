<!--
  frontend/packages/ui/src/components/embeds/SearchResultsTemplate.svelte

  Unified template for search-type fullscreen embeds (web search, news search,
  images search, videos search, travel search, events search, etc.).

  Wraps UnifiedEmbedFullscreen and provides:
  - Responsive CSS grid of result cards (configurable minCardWidth)
  - Loading skeleton state (configurable count)
  - Empty/no-results state
  - Error state
  - ChildEmbedOverlay integration with prev/next sibling navigation
  - initialChildEmbedId auto-open behavior
  - Streaming embed data update passthrough

  Consumers provide two Svelte 5 snippets:
  - resultCard: how to render one result preview card
  - childFullscreen: what fullscreen to show when a result is clicked

  All UnifiedEmbedFullscreen props are passed through (appId, skillId, header, nav, etc.).

  See docs/architecture/embeds.md
-->

<script lang="ts" generics="T extends { embed_id: string }">
  /* eslint-disable no-undef -- Svelte generics are not visible to ESLint's base no-undef rule. */
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from './UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from './ChildEmbedOverlay.svelte';
  import { text } from '@repo/ui';
  import { activeEmbedStore } from '../../stores/activeEmbedStore';
  import type { Snippet } from 'svelte';

  /**
   * Navigation context passed to childFullscreen snippet so the consumer
   * can wire up close/prev/next on the overlay fullscreen component.
   */
  export interface ChildNavContext<U> {
    result: U;
    index: number;
    total: number;
    onClose: () => void;
    hasPrevious: boolean;
    hasNext: boolean;
    onPrevious: () => void;
    onNext: () => void;
  }

  interface Props {
    // ── UnifiedEmbedFullscreen passthrough props ──
    appId: string;
    skillId?: string;
    embedHeaderTitle?: string;
    embedHeaderSubtitle?: string;
    embedHeaderFaviconUrl?: string;
    skillIconName?: string;
    showSkillIcon?: boolean;
    onClose: () => void;
    currentEmbedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;

    // ── Child embed loading ──
    /** Pipe-separated or array of child embed IDs */
    embedIds?: string | string[];
    /** Transform raw decoded content to typed result */
    childEmbedTransformer?: (embedId: string, content: Record<string, unknown>) => T;
    /** Legacy results fallback (pre-child-embed format) */
    legacyResults?: unknown[];
    /** Transform legacy results to typed results */
    legacyResultTransformer?: (results: unknown[]) => T[];
    /** Initial child embed ID to auto-open (from inline badge click) */
    initialChildEmbedId?: string;
    /** Callback when embed data updates during streaming */
    onEmbedDataUpdated?: (data: { status: string; decodedContent: Record<string, unknown> }) => void;
    /** Callback when results are loaded (for consumers that need access to typed results array) */
    onResultsLoaded?: (results: T[]) => void;

    // ── Template configuration ──
    /** Minimum card width for the CSS grid (default: '280px') */
    minCardWidth?: string;
    /** Max width for the results grid container (default: '1000px') */
    maxGridWidth?: string;
    /** Number of skeleton cards to show while loading (default: 6) */
    skeletonCount?: number;
    /** Error message to display (overrides default) */
    errorMessage?: string;
    /** Current status for error state display */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /**
     * Original search query string. When provided, the empty-results state
     * shows "No results found for '<query>'" instead of a generic message.
     * Introduced for OPE-405 (zero-result web search UX).
     */
    query?: string;

    // ── Consumer snippets ──
    /** Render a single result preview card. Receives the result and a click handler. */
    resultCard: Snippet<[{ result: T; index: number; onSelect: () => void }]>;
    /** Render the child fullscreen overlay. Receives navigation context. */
    childFullscreen: Snippet<[ChildNavContext<T>]>;
    /** Optional: custom content for the EmbedHeader CTA area */
    embedHeaderCta?: Snippet;
  }

  let {
    // Unified passthrough
    appId,
    skillId,
    embedHeaderTitle,
    embedHeaderSubtitle,
    embedHeaderFaviconUrl,
    skillIconName,
    showSkillIcon = true,
    onClose,
    currentEmbedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,

    // Child embed loading
    embedIds,
    childEmbedTransformer,
    legacyResults,
    legacyResultTransformer,
    initialChildEmbedId,
    onEmbedDataUpdated,
    onResultsLoaded,

    // Template config
    minCardWidth = '280px',
    maxGridWidth = '1000px',
    skeletonCount = 6,
    errorMessage: errorMessageProp,
    status = 'finished',
    query,

    // Snippets
    resultCard,
    childFullscreen,
    embedHeaderCta,
  }: Props = $props();

  // ── Drill-down state ──
  /** Index of selected result (-1 = none, show grid) */
  let selectedIndex = $state(-1);
  /** All loaded results for sibling navigation */
  let allResults = $state<T[]>([]);
  let selectedResult = $state<T | null>(null);

  let initialChildLookupComplete = $state(false);
  let isOpeningInitialChild = $derived(
    !!initialChildEmbedId && selectedIndex < 0 && !initialChildLookupComplete
  );
  let isDirectInitialChildOpen = $derived(!!initialChildEmbedId && selectedIndex >= 0);
  let embedIdsForFullscreen = $derived(initialChildEmbedId ? [initialChildEmbedId] : embedIds);

  function selectInitialChildFromResults(results: T[]): boolean {
    if (!initialChildEmbedId || selectedIndex >= 0) return false;

    const index = results.findIndex((result) => result.embed_id === initialChildEmbedId);
    if (index < 0) return false;

    selectedIndex = index;
    selectedResult = results[index] ?? null;
    initialChildLookupComplete = true;
    return true;
  }

  function updateLoadedResults(results: T[]): void {
    allResults = results;
    if (selectedIndex >= 0) {
      selectedResult = results[selectedIndex] ?? null;
    }
    onResultsLoaded?.(results);

    if (initialChildEmbedId && !selectInitialChildFromResults(results)) {
      initialChildLookupComplete = true;
    }
  }

  /**
   * Fallback population for consumers that only supply `legacyResults`
   * (no `embedIds`) — e.g. the app-store skill examples fixture flow.
   *
   * The real-chat path goes through `onChildrenLoaded` after embedStore
   * fetches complete, which reliably sets `allResults`. When there are
   * no child embed ids to load, the content snippet used to assign
   * `allResults = results` inline via `{void ...}`, but that
   * template-assignment pattern didn't reliably persist in Svelte 5,
   * so child drilldown from a legacy-results grid silently never
   * populated `selectedResult`. This effect fixes that by computing
   * the typed results whenever `legacyResults` (or the transformer)
   * changes and no embedIds were provided.
   */
  $effect(() => {
    const hasEmbedIds =
      (typeof embedIds === 'string' && embedIds.trim().length > 0) ||
      (Array.isArray(embedIds) && embedIds.length > 0);
    if (hasEmbedIds) return; // real-chat path handles allResults via callback
    if (!legacyResultTransformer) return;
    if (!legacyResults || legacyResults.length === 0) return;
    updateLoadedResults(legacyResultTransformer(legacyResults));
  });

  let errorText = $derived(errorMessageProp || $text('chat.an_error_occured'));

  // ── Handlers ──

  function handleResultSelect(index: number, resultsForClick: T[] = allResults) {
    allResults = resultsForClick;
    selectedIndex = index;
    // Update URL hash to reflect the child embed ID for shareable deep links
    const result = resultsForClick[index];
    selectedResult = result ?? null;
    if (result?.embed_id) {
      activeEmbedStore.setActiveEmbed(result.embed_id, null);
    }
  }

  function handleChildClose() {
    if (initialChildEmbedId) {
      // Opened via inline badge -- close entire fullscreen
      onClose();
    } else {
      selectedIndex = -1;
      selectedResult = null;
      // Restore parent embed ID in URL hash
      if (currentEmbedId) {
        activeEmbedStore.setActiveEmbed(currentEmbedId, null);
      }
    }
  }

  function handleMainClose() {
    if (selectedIndex >= 0 && !initialChildEmbedId) {
      selectedIndex = -1;
      selectedResult = null;
    } else {
      onClose();
    }
  }

  function handleChildPrevious() {
    if (selectedIndex > 0) {
      selectedIndex -= 1;
      const result = allResults[selectedIndex];
      selectedResult = result ?? null;
      if (result?.embed_id) activeEmbedStore.setActiveEmbed(result.embed_id, null);
    }
  }

  function handleChildNext() {
    if (selectedIndex < allResults.length - 1) {
      selectedIndex += 1;
      const result = allResults[selectedIndex];
      selectedResult = result ?? null;
      if (result?.embed_id) activeEmbedStore.setActiveEmbed(result.embed_id, null);
    }
  }

  /**
   * Get typed results from child embed context.
   * Prefers loaded children (already transformed), falls back to legacy.
   */
  function getResults(ctx: ChildEmbedContext): T[] {
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as T[];
    }
    if (legacyResultTransformer && ctx.legacyResults && ctx.legacyResults.length > 0) {
      return legacyResultTransformer(ctx.legacyResults);
    }
    return [];
  }
</script>

<!--
  Overlay-based rendering keeps the parent grid mounted for user-initiated
  drilldown. Inline child deep-links use a lightweight shell to avoid mounting
  a full search grid behind the child fullscreen.
-->

<UnifiedEmbedFullscreen
  {appId}
  {skillId}
  {embedHeaderTitle}
  {embedHeaderSubtitle}
  {embedHeaderFaviconUrl}
  {skillIconName}
  {showSkillIcon}
  onClose={handleMainClose}
  {currentEmbedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  embedIds={embedIdsForFullscreen}
  {childEmbedTransformer}
  {legacyResults}
  onChildrenLoaded={(children) => updateLoadedResults(children as T[])}
  {initialChildEmbedId}
  onAutoOpenChild={(index, children) => {
    updateLoadedResults(children as T[]);
    selectedIndex = index;
    selectedResult = (children as T[])[index] ?? null;
    initialChildLookupComplete = true;
  }}
  {onEmbedDataUpdated}
  {embedHeaderCta}
>
  {#snippet content(ctx)}
    {@const results = getResults(ctx)}

    {#if isOpeningInitialChild || isDirectInitialChildOpen}
      <div class="search-template-child-transition" data-testid="search-template-child-transition" aria-busy="true"></div>
    {:else if status === 'error'}
      <div class="search-template-error">
        <div class="error-title">{$text('embeds.search_failed')}</div>
        <div class="error-message">{errorText}</div>
      </div>
    {:else if results.length === 0}
      {#if ctx.isLoadingChildren}
        <!-- Skeleton loading grid -->
        <div class="search-template-grid" data-testid="search-template-grid" style="--min-card-width: {minCardWidth}; --max-grid-width: {maxGridWidth};">
          {#each Array.from({ length: skeletonCount }) as _, i (i)}
            <div class="search-template-skeleton">
              <div class="skeleton-body"></div>
            </div>
          {/each}
        </div>
      {:else}
        <div class="search-template-empty" data-testid="search-template-empty">
          <p data-testid="search-no-results-message">
            {#if query}
              {$text('embeds.search_no_results_for_query').replace('{query}', query)}
            {:else}
              {$text('embeds.search_no_results')}
            {/if}
          </p>
        </div>
      {/if}
    {:else}
      <!-- Results grid -->
      <div
        class="search-template-grid"
        data-testid="search-template-grid"
        data-selected-index={selectedIndex}
        style="--min-card-width: {minCardWidth}; --max-grid-width: {maxGridWidth};"
      >
        {#each results as result, i (result.embed_id)}
          {@render resultCard({ result, index: i, onSelect: () => handleResultSelect(i, results) })}
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

{#if isOpeningInitialChild}
  <div class="search-template-initial-child-shield" data-testid="search-template-initial-child-shield" aria-busy="true"></div>
{/if}

<!-- Child fullscreen overlay -->
{#if selectedResult}
  <ChildEmbedOverlay instant={!!initialChildEmbedId}>
    {@render childFullscreen({
      result: selectedResult,
      index: selectedIndex,
      total: allResults.length,
      onClose: handleChildClose,
      hasPrevious: selectedIndex > 0,
      hasNext: selectedIndex < allResults.length - 1,
      onPrevious: handleChildPrevious,
      onNext: handleChildNext,
    })}
  </ChildEmbedOverlay>
{/if}

<style>
  /* Results grid -- responsive auto-fill columns */
  .search-template-grid {
    display: grid;
    gap: var(--spacing-8);
    width: calc(100% - 20px);
    max-width: var(--max-grid-width, 1000px);
    margin: 0 auto;
    padding: var(--spacing-12) var(--spacing-5);
    padding-bottom: 120px;
    grid-template-columns: repeat(auto-fill, minmax(var(--min-card-width, 280px), 1fr));
  }

  .search-template-child-transition {
    min-height: 60vh;
    width: 100%;
  }

  .search-template-initial-child-shield {
    position: absolute;
    inset: 0;
    z-index: 101;
    background: var(--color-grey-20);
    border-radius: 17px;
  }

  /* Container query: narrow fullscreen -> single column */
  @container fullscreen (max-width: 500px) {
    .search-template-grid {
      grid-template-columns: 1fr;
    }
  }

  /* Ensure each embed preview card fills grid cell properly */
  .search-template-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }

  /* Override fixed desktop card dimensions so cards fill their grid cell.
     UnifiedEmbedPreview.desktop has width/min-width/max-width: 300px hardcoded —
     those must be overridden here so cards don't overflow narrower grid columns. */
  .search-template-grid :global(.unified-embed-preview.desktop) {
    width: 100% !important;
    min-width: unset !important;
    max-width: 320px !important;
  }

  /* Skeleton loading cards */
  .search-template-skeleton {
    border-radius: var(--radius-5);
    overflow: hidden;
    background: var(--color-grey-10, #f5f5f5);
  }

  .skeleton-body {
    width: 100%;
    height: 180px;
    background: var(--color-grey-15, #ebebeb);
    animation: search-skeleton-pulse 1.5s ease-in-out infinite;
  }

  @keyframes search-skeleton-pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }

  /* Loading / No Results / Error states */
  .search-template-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-p);
  }

  .search-template-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    padding: var(--spacing-12) var(--spacing-8);
    color: var(--color-font-secondary);
    text-align: center;
  }

  .search-template-error .error-title {
    font-size: var(--font-size-h3-mobile);
    font-weight: 600;
    color: var(--color-error);
  }

  .search-template-error .error-message {
    font-size: var(--font-size-small);
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }
</style>
