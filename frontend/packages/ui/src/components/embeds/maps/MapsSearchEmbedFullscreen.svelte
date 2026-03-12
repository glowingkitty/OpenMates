<!--
  frontend/packages/ui/src/components/embeds/maps/MapsSearchEmbedFullscreen.svelte

  Fullscreen view for Maps Search skill embeds.
  Uses EntryWithMapTemplate for the map-background + left-panel layout.

  Layout (wide, >600px container):
  +-----------------------------------------------+
  | [EmbedHeader — search query + via Google]     |
  +-----------------------------------------------+
  |                                               |
  | +--List panel--+   Leaflet Map (background)  |
  | | [Preview 1]  |   ● marker 1               |
  | | [Preview 2]  |   ● marker 2               |
  | | ...          |   ● marker N               |
  | +--------------+                             |
  |                                               |
  +-----------------------------------------------+

  Layout (narrow, <=600px):
  +-----------------------------------------------+
  | [EmbedHeader]                                |
  +-----------------------------------------------+
  | Leaflet Map (150px)                          |
  +-----------------------------------------------+
  | Scrollable list of place preview cards       |
  +-----------------------------------------------+

  Clicking a MapLocationEmbedPreview card opens a ChildEmbedOverlay with
  MapLocationEmbedFullscreen (location details + single-place map).

  Child embeds are loaded via UnifiedEmbedFullscreen (through EntryWithMapTemplate).
  The list is shown in the detailContent snippet slot.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import MapLocationEmbedPreview from './MapLocationEmbedPreview.svelte';
  import MapLocationEmbedFullscreen from './MapLocationEmbedFullscreen.svelte';
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { MapMarker } from '../EmbedLeafletMap.svelte';

  /**
   * A single place result from the Maps Search skill.
   */
  interface PlaceResult {
    embed_id: string;
    displayName?: string;
    formattedAddress?: string;
    location?: { latitude?: number; longitude?: number };
    rating?: number;
    userRatingCount?: number;
    websiteUri?: string;
    placeId?: string;
    placeType?: string;
  }

  interface Props {
    /** Search query text */
    query: string;
    /** Search provider (e.g. 'Google') */
    provider: string;
    /** Pipe-separated or array of child embed IDs */
    embedIds?: string | string[];
    /** Legacy: inline results (backwards compat) */
    results?: PlaceResult[];
    /** Close handler */
    onClose: () => void;
    /** Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed */
    hasNextEmbed?: boolean;
    /** Navigate to previous embed */
    onNavigatePrevious?: () => void;
    /** Navigate to next embed */
    onNavigateNext?: () => void;
    /** Navigation direction for animation */
    navigateDirection?: 'previous' | 'next';
    /** Whether to show the "chat" restore button */
    showChatButton?: boolean;
    /** Callback to restore chat visibility */
    onShowChat?: () => void;
    /**
     * Child embed ID to auto-select on mount (from inline badge click).
     * Opens that place's fullscreen immediately after results load.
     */
    initialChildEmbedId?: string;
  }

  let {
    query,
    provider,
    embedIds,
    results: resultsProp = [],
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    initialChildEmbedId
  }: Props = $props();

  // ── Derived header text ──────────────────────────────────────────────────
  let viaProvider = $derived(`${$text('embeds.via')} ${provider}`);

  // ── Child overlay state ──────────────────────────────────────────────────
  /** The place currently open in the child fullscreen overlay */
  let selectedPlace = $state<PlaceResult | null>(null);
  let selectedIndex = $state<number>(0);

  function handleOpenPlace(place: PlaceResult, index: number) {
    selectedPlace = place;
    selectedIndex = index;
  }

  function handleClosePlace() {
    selectedPlace = null;
  }

  function handlePreviousPlace(places: PlaceResult[]) {
    if (selectedIndex > 0) {
      selectedIndex -= 1;
      selectedPlace = places[selectedIndex];
    }
  }

  function handleNextPlace(places: PlaceResult[]) {
    if (selectedIndex < places.length - 1) {
      selectedIndex += 1;
      selectedPlace = places[selectedIndex];
    }
  }

  // ── Child embed transformer ──────────────────────────────────────────────
  function transformToPlaceResult(
    embedId: string,
    content: Record<string, unknown>
  ): PlaceResult {
    const location = content.location as Record<string, number> | undefined;
    return {
      embed_id: embedId,
      displayName: content.displayName as string | undefined,
      formattedAddress:
        (content.formattedAddress as string | undefined) ||
        (content.formatted_address as string | undefined),
      location: location
        ? { latitude: location.latitude, longitude: location.longitude }
        : undefined,
      rating: content.rating as number | undefined,
      userRatingCount: content.userRatingCount as number | undefined,
      websiteUri: content.websiteUri as string | undefined,
      placeId: content.placeId as string | undefined,
      placeType: content.placeType as string | undefined,
    };
  }

  /** Transform legacy inline results to PlaceResult[] */
  function transformLegacyResults(results: unknown[]): PlaceResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const location = r.location as Record<string, number> | undefined;
      return {
        embed_id: `legacy-${i}`,
        displayName: (r.displayName as string | undefined) || (r.name as string | undefined),
        formattedAddress: (r.formattedAddress as string | undefined) || (r.address as string | undefined),
        location: location
          ? { latitude: location.latitude, longitude: location.longitude }
          : undefined,
        rating: r.rating as number | undefined,
        userRatingCount: (r.userRatingCount as number | undefined) || (r.reviews as number | undefined),
        websiteUri: r.websiteUri as string | undefined,
        placeId: r.placeId as string | undefined,
        placeType: r.placeType as string | undefined,
      };
    });
  }

  /** Get typed place results from child embed context (children or legacy fallback) */
  function getPlaceResults(ctx: ChildEmbedContext): PlaceResult[] {
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as PlaceResult[];
    }
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }

  /**
   * Called by UnifiedEmbedFullscreen when child embeds finish loading.
   * Handles auto-opening a specific child (from inline badge click).
   */
  function handleChildrenLoaded(children: unknown[]) {
    if (!initialChildEmbedId) return;
    const places = children as PlaceResult[];
    const idx = places.findIndex((p) => p.embed_id === initialChildEmbedId);
    if (idx !== -1) {
      handleOpenPlace(places[idx], idx);
    }
  }

  // ── Map markers derived from place results ───────────────────────────────
  /** Build markers array from place results for EmbedLeafletMap */
  function buildMarkers(places: PlaceResult[]): MapMarker[] {
    return places
      .filter((p) => p.location?.latitude != null && p.location?.longitude != null)
      .map((p) => ({
        lat: p.location!.latitude!,
        lon: p.location!.longitude!,
        label: p.displayName,
      }));
  }

  /** Calculate the geographic center of all valid place locations */
  function buildMapCenter(
    places: PlaceResult[]
  ): { lat: number; lon: number } | undefined {
    const valid = places.filter(
      (p) => p.location?.latitude != null && p.location?.longitude != null
    );
    if (valid.length === 0) return undefined;
    const lats = valid.map((p) => p.location!.latitude!);
    const lons = valid.map((p) => p.location!.longitude!);
    return {
      lat: (Math.min(...lats) + Math.max(...lats)) / 2,
      lon: (Math.min(...lons) + Math.max(...lons)) / 2,
    };
  }
</script>

<!--
  We use UnifiedEmbedFullscreen directly (not via EntryWithMapTemplate) because
  we need to load child embeds (via embedIds) AND render the map + list together.
  EntryWithMapTemplate doesn't support child embed loading — it wraps
  UnifiedEmbedFullscreen without embedIds support.

  The map-background + left-panel layout is replicated inline inside the content snippet,
  matching EntryWithMapTemplate's responsive behavior (wide: absolute map + floating
  panel; narrow <=600px: stacked map + list via @container query).
-->
<UnifiedEmbedFullscreen
  appId="maps"
  skillId="search"
  {onClose}
  currentEmbedId={embedId}
  skillIconName="search"
  embedHeaderTitle={query}
  embedHeaderSubtitle={viaProvider}
  {embedIds}
  childEmbedTransformer={transformToPlaceResult}
  legacyResults={resultsProp}
  onChildrenLoaded={handleChildrenLoaded}
  onAutoOpenChild={(index, children) => {
    const places = children as PlaceResult[];
    if (places[index]) handleOpenPlace(places[index], index);
  }}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const places = getPlaceResults(ctx)}
    {@const markers = buildMarkers(places)}
    {@const mapCenter = buildMapCenter(places)}

    {#if ctx.isLoadingChildren}
      <!-- Loading state: show spinner in the detail card area -->
      <div class="search-layout loading-layout">
        <div class="loading-state">
          <p>{$text('embeds.loading')}</p>
        </div>
      </div>
    {:else if places.length === 0}
      <div class="search-layout loading-layout">
        <div class="no-results">
          <p>{$text('embeds.no_results')}</p>
        </div>
      </div>
    {:else}
      <!--
        Map + list layout.
        Wide (>600px): map fills background absolutely, list panel floats on left.
        Narrow (<=600px): map at top (150px), list scrolls below.
      -->
      <div class="search-layout" class:has-map={!!mapCenter}>
        <!-- Leaflet map fills the background on wide viewports -->
        {#if mapCenter}
          <div class="map-section">
            {#await import('../EmbedLeafletMap.svelte') then { default: EmbedLeafletMap }}
              <EmbedLeafletMap
                center={mapCenter}
                zoom={12}
                {markers}
                scrollWheelZoom={false}
                height="100%"
                minHeight="150px"
              />
            {/await}
          </div>
        {/if}

        <!-- Left-panel list of place preview cards -->
        <div class="results-panel" class:with-map={!!mapCenter}>
          <div class="results-list">
            {#each places as place, index}
              {@const isSelected = selectedPlace?.embed_id === place.embed_id}
              <div
                class="result-item"
                class:selected={isSelected}
                role="button"
                tabindex="0"
                onclick={() => handleOpenPlace(place, index)}
                onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && handleOpenPlace(place, index)}
              >
                <MapLocationEmbedPreview
                  id={place.embed_id}
                  displayName={place.displayName}
                  formattedAddress={place.formattedAddress}
                  rating={place.rating}
                  userRatingCount={place.userRatingCount}
                  placeType={place.placeType}
                  {isSelected}
                  status="finished"
                  isMobile={false}
                />
              </div>
            {/each}
          </div>
        </div>
      </div>

      <!-- Child overlay: opens when a place card is clicked -->
      {#if selectedPlace}
        <ChildEmbedOverlay>
          <MapLocationEmbedFullscreen
            displayName={selectedPlace.displayName}
            formattedAddress={selectedPlace.formattedAddress}
            lat={selectedPlace.location?.latitude}
            lon={selectedPlace.location?.longitude}
            rating={selectedPlace.rating}
            userRatingCount={selectedPlace.userRatingCount}
            placeType={selectedPlace.placeType}
            websiteUri={selectedPlace.websiteUri}
            placeId={selectedPlace.placeId}
            onClose={handleClosePlace}
            hasPreviousEmbed={selectedIndex > 0}
            hasNextEmbed={selectedIndex < places.length - 1}
            onNavigatePrevious={() => handlePreviousPlace(places)}
            onNavigateNext={() => handleNextPlace(places)}
          />
        </ChildEmbedOverlay>
      {/if}
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ── Outer layout container ─────────────────────────────────────────────── */

  .search-layout {
    position: relative;
    width: 100%;
    min-height: calc(100dvh - 240px);
  }

  .search-layout.loading-layout {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 200px;
  }

  /* ── Map section (absolute background on wide viewports) ────────────────── */

  .map-section {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    min-height: calc(100dvh - 240px);
    z-index: 0;
  }

  /* ── Results panel (left floating card on wide, full-width on narrow) ───── */

  .results-panel {
    position: relative;
    z-index: 2;
  }

  .results-panel.with-map {
    position: absolute;
    top: 24px;
    left: 24px;
    width: 360px;
    max-height: calc(100% - 48px);
    background: var(--color-grey-20);
    border-radius: 16px;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .results-list {
    overflow-y: auto;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    /* Prevent the list from overflowing the card */
    max-height: calc(100dvh - 240px - 48px - 24px);
  }

  .results-panel.with-map .results-list {
    max-height: calc(100% - 0px);
  }

  /* ── Individual result item wrapper ─────────────────────────────────────── */

  .result-item {
    cursor: pointer;
    border-radius: 16px;
    border: 2px solid transparent;
    transition: border-color 0.15s ease;
    /* Prevent UnifiedEmbedPreview's own pointer-events block from interfering */
    pointer-events: all;
  }

  .result-item:hover {
    border-color: var(--color-border);
  }

  .result-item.selected {
    border-color: var(--color-primary);
    box-shadow: 0 0 0 2px rgba(var(--color-primary-rgb, 0, 123, 255), 0.15);
  }

  .result-item:focus {
    outline: 2px solid var(--color-primary);
    outline-offset: 2px;
  }

  /* Make the UnifiedEmbedPreview inside fill the wrapper width */
  .result-item :global(.unified-embed-preview.desktop) {
    width: 100% !important;
    min-width: unset !important;
    max-width: unset !important;
  }

  /* ── Loading / no-results states ─────────────────────────────────────────── */

  .loading-state,
  .no-results {
    color: var(--color-font-secondary);
    font-size: 1rem;
    text-align: center;
  }

  /* ── Scrollbar styling ───────────────────────────────────────────────────── */

  .results-list::-webkit-scrollbar {
    width: 6px;
  }

  .results-list::-webkit-scrollbar-track {
    background: transparent;
  }

  .results-list::-webkit-scrollbar-thumb {
    background: var(--color-border);
    border-radius: 3px;
  }

  .results-list::-webkit-scrollbar-thumb:hover {
    background: var(--color-grey-60);
  }

  /* ── Narrow layout (<=600px container): stacked map + list ──────────────── */

  @container fullscreen (max-width: 600px) {
    .search-layout {
      display: flex;
      flex-direction: column;
      min-height: auto;
    }

    .map-section {
      position: relative;
      inset: auto;
      width: 100%;
      height: 150px;
      min-height: 150px;
      flex-shrink: 0;
    }

    .results-panel.with-map {
      position: static;
      width: 100%;
      max-height: none;
      border-radius: 0;
      box-shadow: none;
      background: transparent;
    }

    .results-list {
      max-height: none;
      padding: 12px 16px;
    }

    .result-item :global(.unified-embed-preview.desktop) {
      width: 100% !important;
      min-width: unset !important;
      max-width: unset !important;
    }
  }
</style>
