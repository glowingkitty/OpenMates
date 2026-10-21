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
  import { onDestroy, getContext } from 'svelte';
  import { saveAppsSearchWithNotice } from '../../services/appsWorkspaceLibraryService';
  import { searchResultMapMarkers } from './searchResultMapMarkers';
  import EmbedLeafletMap from './EmbedLeafletMap.svelte';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import AppsRequestComposer from '../apps/AppsRequestComposer.svelte';
  import { get } from 'svelte/store';
  import { activeTeamContext } from '../../stores/teamStore';
  import { authStore } from '../../stores/authState';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  import { APPS_RESULTS_ACTIONS_CONTEXT, runAppsWorkspaceRequest, type AppsResultsActionsContext, type AppsRequestContext } from '../../services/appsWorkspaceRequestService';
  import { queueAppsWorkspaceChatHandoff, queueAppsWorkspaceWorkflowHandoff, captureAppsWorkspaceHandoffGuard } from '../../services/appsWorkspaceChatHandoffService';
  import { activeEmbedStore } from '../../stores/activeEmbedStore';
  import {
    restorePreviousFullscreenRoute,
    setCanonicalFullscreenRoute,
    setChildFullscreenRouteFromParent,
  } from '../../services/embedFullscreenController';
  import type { Snippet } from 'svelte';

  /**
   * Navigation context passed to childFullscreen snippet so the consumer
   * can wire up close/prev/next on the overlay fullscreen component.
   */
  interface ChildNavContext<U> {
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
    testId?: string;
    closeTestId?: string;
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
    /** Optional data-testid for the empty state. */
    emptyTestId?: string;
    /** Current status for error state display */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Original search query string. Kept for callers that also display it elsewhere. */
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
    testId,
    closeTestId,
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
    emptyTestId = 'search-template-empty',
    status = 'finished',
    query,

    // Snippets
    resultCard,
    childFullscreen,
    embedHeaderCta,
  }: Props = $props();

  const resultOwnerCurrent = captureAppsWorkspaceHandoffGuard();
  const actions = getContext<AppsResultsActionsContext | undefined>(APPS_RESULTS_ACTIONS_CONTEXT);
  const sourceChat = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  let parentContent = $state<Record<string, unknown>>({});
  $effect(() => {
    let cancelled = false;
    parentContent = {};
    if (currentEmbedId && !actions) void resolveEmbed(currentEmbedId).then(async embed => {
      const content = embed ? await decodeToonContent(embed.content) : null;
      if (!cancelled && content) parentContent = content;
    }).catch(() => {});
    return () => { cancelled = true; };
  });
  let resultFilter = $state('');
  let submittingRequest = $state(false);
  let requestError = $state(false);
  function requestContext(): AppsRequestContext {
    if (!resultOwnerCurrent()) throw new Error('account_context_changed');
    return { skill_id: skillId, input: parentContent.input && typeof parentContent.input === 'object' ? parentContent.input as Record<string, unknown> : query ? { query } : undefined, embed_id: currentEmbedId,
      chat_id: sourceChat?.chatId ?? (typeof parentContent.chat_id === 'string' ? parentContent.chat_id : undefined), result: { ...parentContent, results: allResults } };
  }
  async function saveSearch(): Promise<void> {
    requestError = false;
    try { const context = requestContext(); if (actions?.onSaveSearch) await actions.onSaveSearch(context); else await saveAppsSearchWithNotice(appId, context, undefined, get(activeTeamContext).teamId ?? undefined); }
    catch { requestError = true; }
  }
  async function createWorkflow(): Promise<void> {
    requestError = false;
    try { const context = requestContext(); if (actions?.onCreateWorkflow) await actions.onCreateWorkflow(context); else await queueAppsWorkspaceWorkflowHandoff({ text: $text('apps_workspace.create_workflow'), context }); }
    catch { requestError = true; }
  }
  function matchesFilter(result: T): boolean {
    if (!resultFilter.trim()) return true;
    // Search only actual preview data; no speculative category/price filters.
    const values = Object.entries(result).filter(([key]) => !['embed_id', 'embed_type'].includes(key));
    return JSON.stringify(values).toLocaleLowerCase().includes(resultFilter.trim().toLocaleLowerCase());
  }
  async function submitFollowup(value: string, attachments: File[]): Promise<boolean> {
    submittingRequest = true; requestError = false;
    try {
      if (actions) return (await actions.onSubmit(value, attachments, requestContext())) !== false;
      const result = await runAppsWorkspaceRequest({ appId, text: value, attachments, guest: !$authStore.isAuthenticated, teamId: get(activeTeamContext).teamId ?? undefined,
        context: requestContext(), onAccepted: ({ embedId }) => { setCanonicalFullscreenRoute(embedId); }, onChat: queueAppsWorkspaceChatHandoff, onWorkflow: queueAppsWorkspaceWorkflowHandoff });
      if (result.action !== 'execute') onClose();
      return true;
    } catch { requestError = true; return false; }
    finally { submittingRequest = false; }
  }

  // ── Drill-down state ──
  /** Index of selected result (-1 = none, show grid) */
  let selectedIndex = $state(-1);
  /** All loaded results for sibling navigation */
  let allResults = $state<T[]>([]);
  const mapMarkers = $derived(searchResultMapMarkers(allResults));
  let selectedResult = $derived(selectedIndex >= 0 ? allResults[selectedIndex] ?? null : null);

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

    allResults = results;
    selectedIndex = index;
    initialChildLookupComplete = true;
    return true;
  }

  function updateLoadedResults(results: T[]): void {
    allResults = results;
    onResultsLoaded?.(results);

    if (initialChildEmbedId && !selectInitialChildFromResults(results)) {
      initialChildLookupComplete = true;
    }
  }

  const unsubscribeActiveEmbed = activeEmbedStore.subscribe((activeEmbedId) => {
    if (!currentEmbedId || allResults.length === 0) return;

    if (activeEmbedId === currentEmbedId && selectedIndex >= 0) {
      selectedIndex = -1;
      return;
    }

    const childIndex = activeEmbedId
      ? allResults.findIndex((result) => result.embed_id === activeEmbedId)
      : -1;
    if (childIndex >= 0 && childIndex !== selectedIndex) {
      selectedIndex = childIndex;
      initialChildLookupComplete = true;
    }
  });

  onDestroy(unsubscribeActiveEmbed);

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
    const result = resultsForClick[index];

    // Real child embeds are shareable deep links. Legacy fallback results use
    // synthetic IDs that are only valid inside this mounted fullscreen; publishing
    // them to the global hash makes the app-level resolver chase an unresolvable
    // embed and can hide the nested child overlay.
    if (result?.embed_id && !isSyntheticLegacyEmbedId(result.embed_id)) {
      if (currentEmbedId) {
        setChildFullscreenRouteFromParent(result.embed_id, currentEmbedId);
      } else {
        setCanonicalFullscreenRoute(result.embed_id);
      }
    }
  }

  function handleChildClose() {
    if (initialChildEmbedId) {
      // Opened via inline badge -- close entire fullscreen
      onClose();
    } else {
      selectedIndex = -1;
      restorePreviousFullscreenRoute(currentEmbedId ?? null);
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
    if (selectedIndex > 0) {
      selectedIndex -= 1;
      const result = allResults[selectedIndex];
      if (result?.embed_id && !isSyntheticLegacyEmbedId(result.embed_id)) {
        if (currentEmbedId) setChildFullscreenRouteFromParent(result.embed_id, currentEmbedId);
        else setCanonicalFullscreenRoute(result.embed_id);
      }
    }
  }

  function handleChildNext() {
    if (selectedIndex < allResults.length - 1) {
      selectedIndex += 1;
      const result = allResults[selectedIndex];
      if (result?.embed_id && !isSyntheticLegacyEmbedId(result.embed_id)) {
        if (currentEmbedId) setChildFullscreenRouteFromParent(result.embed_id, currentEmbedId);
        else setCanonicalFullscreenRoute(result.embed_id);
      }
    }
  }

  function isSyntheticLegacyEmbedId(embedId: string): boolean {
    return embedId.startsWith('legacy-');
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

  {#snippet mapHeader()}
      <EmbedLeafletMap center={mapMarkers[0]} markers={mapMarkers} height="300px" fitBounds={true} scrollWheelZoom={false}
        onMarkerSelect={(ref) => { const index = allResults.findIndex(result => result.embed_id === ref); if (index >= 0) handleResultSelect(index, allResults); }} />
  {/snippet}

  {#snippet followupComposer()}
      <AppsRequestComposer {appId} submitting={submittingRequest} placeholder={$text('apps_workspace.followup_placeholder')} onSubmit={submitFollowup} />
      {#if requestError}<p role="alert">{$text('apps_workspace.request_error')}</p>{/if}
  {/snippet}

<UnifiedEmbedFullscreen
  {testId}
  {closeTestId}
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
  onChildrenLoaded={(children) => {
    const typedChildren = children as T[];
    updateLoadedResults(typedChildren);
    selectInitialChildFromResults(typedChildren);
  }}
  {initialChildEmbedId}
  onAutoOpenChild={(index, children) => {
    updateLoadedResults(children as T[]);
    selectedIndex = index;
    initialChildLookupComplete = true;
  }}
  {onEmbedDataUpdated}
  {embedHeaderCta}
  embedHeaderContent={mapMarkers.length > 0 && !initialChildEmbedId ? mapHeader : undefined}
  fixedBottom={!initialChildEmbedId ? followupComposer : undefined}
>
  {#snippet content(ctx)}
    {@const results = getResults(ctx)}
    {#if !initialChildEmbedId && results.length > 0}
      <div class="search-template-toolbar" data-testid="search-template-toolbar">
        <input type="search" bind:value={resultFilter} placeholder={$text('apps_workspace.filter_results')} aria-label={$text('apps_workspace.filter_results')} data-testid="search-template-filter" />
        {#if skillId && (parentContent.input || query)}<button type="button" onclick={saveSearch}>{$text('apps_workspace.save_search')}</button>{/if}
        <button type="button" onclick={createWorkflow}>{$text('apps_workspace.create_workflow')}</button>
      </div>
    {/if}

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
        <div class="search-template-empty" data-testid={emptyTestId}>
          <p data-testid="search-no-results-message">
            {$text('embeds.search_no_results')}
          </p>
        </div>
      {/if}
    {:else}
      {#if !results.some(matchesFilter)}
        <div class="search-template-empty" role="status">{$text('embeds.search_no_results')}</div>
      {/if}
      <!-- Results grid -->
      <div
        class="search-template-grid"
        data-testid="search-template-grid"
        data-selected-index={selectedIndex}
        style="--min-card-width: {minCardWidth}; --max-grid-width: {maxGridWidth};"
      >
        {#each results as result, i (result.embed_id)}
          {#if matchesFilter(result)}{@render resultCard({ result, index: i, onSelect: () => handleResultSelect(i, results) })}{/if}
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
  .search-template-toolbar { position: sticky; top: 0; z-index: 20; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 12px 64px 12px 20px; background: var(--color-grey-20); }
  .search-template-toolbar input { flex: 1; min-width: 140px; border: 1px solid var(--color-grey-30); border-radius: 12px; padding: 10px 12px; background: var(--color-grey-10); color: var(--color-font-primary); }
  .search-template-toolbar button { border: 0; border-radius: 12px; padding: 10px; color: var(--color-font-primary); background: var(--color-grey-10); cursor: pointer; }
  /* Results grid -- responsive auto-fill columns */
  .search-template-grid {
    display: grid;
    gap: var(--spacing-8);
    width: calc(100% - 20px);
    max-width: var(--max-grid-width, 1000px);
    margin: 0 auto;
    padding: var(--spacing-12) var(--spacing-5);
    padding-bottom: 24px;
    box-sizing: border-box;
    overflow: clip;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, var(--min-card-width, 280px)), 1fr));
  }

  .search-template-child-transition {
    min-height: 60vh;
    width: 100%;
  }

  .search-template-initial-child-shield {
    position: absolute;
    inset: 0;
    z-index: var(--z-index-dropdown);
    background: var(--color-grey-20);
    border-radius: 17px;
  }

  /* Container query: narrow fullscreen -> single column */
  @container fullscreen (max-width: 500px) {
    .search-template-grid {
      width: 100%;
      grid-template-columns: 1fr;
      gap: var(--spacing-5);
      padding: var(--spacing-8) var(--spacing-3) 96px;
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
    background: var(--color-grey-20, #ebebeb);
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
