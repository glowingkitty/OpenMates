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
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from './UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from './ChildEmbedOverlay.svelte';
  import { text } from '@repo/ui';
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

  let selectedResult = $derived(
    selectedIndex >= 0 ? allResults[selectedIndex] ?? null : null
  );

  let errorText = $derived(errorMessageProp || $text('chat.an_error_occured'));

  // ── Handlers ──

  function handleResultSelect(index: number) {
    selectedIndex = index;
  }

  function handleChildClose() {
    if (initialChildEmbedId) {
      // Opened via inline badge -- close entire fullscreen
      onClose();
    } else {
      selectedIndex = -1;
    }
  }

  function handleMainClose() {
    if (selectedIndex >= 0 && !initialChildEmbedId) {
      selectedIndex = -1;
    } else {
      onClose();
    }
  }

  function handleChildPrevious() {
    if (selectedIndex > 0) selectedIndex -= 1;
  }

  function handleChildNext() {
    if (selectedIndex < allResults.length - 1) selectedIndex += 1;
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
  Overlay-based rendering: search results grid is ALWAYS mounted.
  Child detail view renders as overlay on top via ChildEmbedOverlay.
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
  {embedIds}
  {childEmbedTransformer}
  {legacyResults}
  onChildrenLoaded={(children) => { allResults = children as T[]; onResultsLoaded?.(children as T[]); }}
  {initialChildEmbedId}
  onAutoOpenChild={(index, children) => {
    allResults = children as T[];
    onResultsLoaded?.(children as T[]);
    selectedIndex = index;
  }}
  {onEmbedDataUpdated}
  {embedHeaderCta}
>
  {#snippet content(ctx)}
    {@const results = getResults(ctx)}
    <!-- Sync allResults when resolved list changes (enables sibling navigation) -->
    <!-- Note: void suppresses text rendering — {expr} would print the array as "[object Object],..." -->
    {#if results.length > 0 && results !== allResults}
      {void (allResults = results)}
    {/if}

    {#if status === 'error'}
      <div class="search-template-error">
        <div class="error-title">{$text('embeds.search_failed')}</div>
        <div class="error-message">{errorText}</div>
      </div>
    {:else if results.length === 0}
      {#if ctx.isLoadingChildren}
        <!-- Skeleton loading grid -->
        <div class="search-template-grid" style="--min-card-width: {minCardWidth}; --max-grid-width: {maxGridWidth};">
          {#each Array.from({ length: skeletonCount }) as _, i (i)}
            <div class="search-template-skeleton">
              <div class="skeleton-body"></div>
            </div>
          {/each}
        </div>
      {:else}
        <div class="search-template-empty">
          <p>{$text('embeds.search_no_results')}</p>
        </div>
      {/if}
    {:else}
      <!-- Results grid -->
      <div class="search-template-grid" style="--min-card-width: {minCardWidth}; --max-grid-width: {maxGridWidth};">
        {#each results as result, i (result.embed_id)}
          {@render resultCard({ result, index: i, onSelect: () => handleResultSelect(i) })}
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Child fullscreen overlay -->
{#if selectedResult}
  <ChildEmbedOverlay>
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
    gap: 16px;
    width: calc(100% - 20px);
    max-width: var(--max-grid-width, 1000px);
    margin: 0 auto;
    padding: 24px 10px;
    padding-bottom: 120px;
    grid-template-columns: repeat(auto-fill, minmax(var(--min-card-width, 280px), 1fr));
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
    border-radius: 12px;
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
    font-size: 16px;
  }

  .search-template-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }

  .search-template-error .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }

  .search-template-error .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
  }
</style>
