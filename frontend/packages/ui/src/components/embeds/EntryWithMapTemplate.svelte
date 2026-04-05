<!--
  frontend/packages/ui/src/components/embeds/EntryWithMapTemplate.svelte

  Unified template for single-entry fullscreen embeds with an interactive map.
  Used by: MapsLocation, TravelStay, Event, HealthAppointment, etc.

  Layout (wide container, >600px):
  +------------------------------------------+
  | [EmbedHeader - from UnifiedEmbedFullscreen]
  +------------------------------------------+
  |                                          |
  | +---------+     Leaflet Map              |
  | | Details  |     (full background)       |
  | | Card     |                             |
  | | 345px    |        [marker/path]        |
  | |          |                             |
  | | [CTA]   |                             |
  | +---------+                              |
  |                                          |
  +------------------------------------------+

  Layout (narrow container, <=600px):
  +------------------------------------------+
  | [EmbedHeader]                            |
  +------------------------------------------+
  | Leaflet Map (full width, 150px tall)     |
  +------------------------------------------+
  | Details Content                          |
  | ...                                      |
  | [CTA Button]                             |
  +------------------------------------------+

  When no map coordinates are available, falls back to details-only layout.

  See docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from './UnifiedEmbedFullscreen.svelte';
  import EmbedLeafletMap, { type MapMarker, type MapPathPoint } from './EmbedLeafletMap.svelte';
  import type { Snippet } from 'svelte';

  interface Props {
    // ── UnifiedEmbedFullscreen passthrough ──
    appId: string;
    skillId?: string;
    embedHeaderTitle?: string;
    embedHeaderSubtitle?: string;
    skillIconName?: string;
    showSkillIcon?: boolean;
    onClose: () => void;
    currentEmbedId?: string;
    showShare?: boolean;
    onCopy?: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;

    // ── Child embed loading passthrough (for search-style map pages) ──
    embedIds?: string | string[];
    childEmbedTransformer?: (embedId: string, content: Record<string, unknown>) => unknown;
    legacyResults?: unknown[];
    onChildrenLoaded?: (children: unknown[]) => void;
    initialChildEmbedId?: string;
    onAutoOpenChild?: (index: number, children: unknown[]) => void;
    onEmbedDataUpdated?: (data: { status: string; decodedContent: Record<string, unknown> }) => void;

    // ── Map configuration ──
    /** Map center. If undefined, map is hidden and details-only layout is used. */
    mapCenter?: { lat: number; lon: number };
    /** Map zoom level (default: 15) */
    mapZoom?: number;
    /** Array of markers to display on the map */
    mapMarkers?: MapMarker[];
    /** Optional polyline path for routes */
    mapPath?: MapPathPoint[];
    /** Path color for route line */
    mapPathColor?: string;
    /** Whether scroll wheel zoom is enabled on the map (default: false for embed UX) */
    mapScrollWheelZoom?: boolean;
    /** Callback with raw Leaflet map + L for advanced customization (e.g. flight arcs) */
    onMapReady?: (map: unknown, L: unknown) => void;
    /** Optional static map image URL (shown instead of Leaflet when available) */
    staticMapImageUrl?: string;

    // ── Consumer snippets ──
    /** The detail content to show in the left card (wide) or below map (narrow) */
    detailContent: Snippet<[ChildEmbedContext]>;
    /** Optional: custom content for the EmbedHeader CTA area */
    embedHeaderCta?: Snippet;
  }

  let {
    // Unified passthrough
    appId,
    skillId,
    embedHeaderTitle,
    embedHeaderSubtitle,
    skillIconName,
    showSkillIcon,
    onClose,
    currentEmbedId,
    showShare,
    onCopy,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,

    embedIds,
    childEmbedTransformer,
    legacyResults,
    onChildrenLoaded,
    initialChildEmbedId,
    onAutoOpenChild,
    onEmbedDataUpdated,

    // Map config
    mapCenter,
    mapZoom = 15,
    mapMarkers = [],
    mapPath = [],
    mapPathColor,
    mapScrollWheelZoom = false,
    onMapReady,
    staticMapImageUrl,

    // Snippets
    detailContent,
    embedHeaderCta,
  }: Props = $props();

  let hasMap = $derived(!!mapCenter);
  let imageError = $state(false);
  let hasStaticImage = $derived(!!staticMapImageUrl && !imageError);

  const DETAIL_CARD_LEFT_PX = 24;
  const DETAIL_CARD_WIDTH_PX = 345;
  const MAP_CENTER_OFFSET_X_PX = (DETAIL_CARD_LEFT_PX + DETAIL_CARD_WIDTH_PX) / 2;

  let mapCenterOffsetX = $derived(hasMap ? MAP_CENTER_OFFSET_X_PX : 0);
</script>

<UnifiedEmbedFullscreen
  {appId}
  {skillId}
  {embedHeaderTitle}
  {embedHeaderSubtitle}
  {skillIconName}
  {showSkillIcon}
  onClose={onClose}
  {currentEmbedId}
  {showShare}
  {onCopy}
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
  {onChildrenLoaded}
  {initialChildEmbedId}
  {onAutoOpenChild}
  {onEmbedDataUpdated}
  {embedHeaderCta}
>
  {#snippet content(childEmbedContext)}
    <div class="entry-map-layout" class:has-map={hasMap} class:no-map={!hasMap}>
      <!-- Map section -->
      {#if hasStaticImage}
        <div class="map-section static-image">
          <img
            src={staticMapImageUrl}
            alt={embedHeaderTitle || 'Map'}
            class="static-map-image"
            onerror={() => { imageError = true; }}
          />
        </div>
      {:else if hasMap && mapCenter}
        <div class="map-section interactive">
          <EmbedLeafletMap
            center={mapCenter}
            zoom={mapZoom}
            markers={mapMarkers}
            path={mapPath}
            pathColor={mapPathColor}
            scrollWheelZoom={mapScrollWheelZoom}
            centerOffsetX={mapCenterOffsetX}
            {onMapReady}
            height="100%"
            minHeight="150px"
          />
        </div>
      {/if}

      <!-- Detail card (overlaps map on wide, below map on narrow) -->
      <div class="detail-card" class:with-map={hasMap}>
        <div class="detail-content">
          {@render detailContent(childEmbedContext)}
        </div>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ── Wide layout (>600px container): map background + overlapping detail card ── */
  .entry-map-layout {
    position: relative;
    width: 100%;
    /* Fill the remaining visible area after the gradient header (240px).
       Using min-height so the detail card can push beyond if content overflows. */
    min-height: calc(100dvh - 240px);
  }

  .entry-map-layout.no-map {
    min-height: auto;
  }

  /* Map fills the full area absolutely within the layout container */
  .map-section {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    min-height: calc(100dvh - 240px);
  }

  .map-section.static-image {
    overflow: hidden;
    background: var(--color-bg-secondary);
  }

  .static-map-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  /* Detail card floats on top-left of the map on wide viewports */
  .detail-card.with-map {
    position: absolute;
    top: 24px;
    left: 24px;
    width: 345px;
    max-height: calc(100% - 48px);
    overflow-y: auto;
    background: var(--color-grey-20);
    border-radius: var(--radius-7);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
    z-index: 2;
  }

  /* Without map: detail card is full width, centered */
  .detail-card:not(.with-map) {
    max-width: 640px;
    margin: 0 auto;
    padding-bottom: 120px;
  }

  .detail-content {
    padding: var(--spacing-10);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8);
  }

  /* ── Narrow layout (<=600px container): stacked map + detail ── */
  @container fullscreen (max-width: 600px) {
    .entry-map-layout {
      display: flex;
      flex-direction: column;
      height: auto;
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

    .map-section.interactive {
      min-height: 150px;
    }

    .static-map-image {
      height: 150px;
      min-height: 150px;
    }

    .detail-card.with-map {
      position: static;
      width: 100%;
      max-height: none;
      border-radius: 0;
      box-shadow: none;
      background: var(--color-grey-20);
    }

    .detail-card:not(.with-map) {
      padding: 0 16px 120px;
    }

    .detail-content {
      padding: var(--spacing-10) var(--spacing-8);
    }

  }
</style>
