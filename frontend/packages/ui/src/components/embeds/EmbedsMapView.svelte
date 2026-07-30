<!--
  frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte

  Virtual in-chat map/list view over existing location-capable embeds.
  It resolves refs from local embed data and never calls provider/app-skill
  enrichment endpoints. Missing refs stay visible as loading/unavailable rows.
  Spec: docs/specs/embeds-map-view/spec.yml
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import EmbedLeafletMap, { type MapMarker, type MapPathPoint, type MapRoutePath } from './EmbedLeafletMap.svelte';
  import { decodeToonContent, resolveEmbed, type EmbedData } from '../../services/embedResolver';
  import { embedRefIndexVersion, embedStore } from '../../services/embedStore';
  import { dispatchEmbedFullscreen } from '../../services/embedFullscreenController';

  const MAX_VISIBLE_ENTRIES = 40;
  const MAX_TRAVEL_LEGS = 8;
  const MAX_TRAVEL_SEGMENTS_PER_LEG = 32;
  const DEFAULT_ROUTE_COLOR = '#8a92a6';
  const ACTIVE_ROUTE_COLOR = '#6c63ff';

  interface Props {
    id: string;
    title: string;
    embedRefs?: string[];
    sourceRefs?: string[];
    highlightRefs?: string[];
  }

  interface MapViewEntry {
    ref: string;
    embedId: string | null;
    embedType: string | null;
    title: string;
    subtitle: string;
    category: string;
    status: 'loading' | 'ready' | 'unavailable';
    highlighted: boolean;
    lat?: number;
    lon?: number;
    route?: MapPathPoint[];
    embedData?: EmbedData;
    decodedContent?: Record<string, unknown> | null;
  }

  let {
    id,
    title,
    embedRefs = [],
    sourceRefs = [],
    highlightRefs = [],
  }: Props = $props();

  let entries = $state<MapViewEntry[]>([]);
  let isLoading = $state(true);
  let hoveredRef = $state<string | null>(null);
  let activeCategory = $state<string>('all');
  let filtersOpen = $state(false);
  let unsubscribeRefIndex: (() => void) | null = null;
  let lastRefIndexVersion = -1;

  const highlightSet = $derived(new Set(highlightRefs));
  const categories = $derived.by(() => {
    const values = Array.from(new Set(entries.filter((entry) => entry.status === 'ready').map((entry) => entry.category)));
    return ['all', ...values];
  });
  const visibleEntries = $derived.by(() => {
    const filtered = activeCategory === 'all'
      ? entries
      : entries.filter((entry) => entry.category === activeCategory || entry.status !== 'ready');
    return filtered
      .slice()
      .sort((a, b) => Number(b.highlighted) - Number(a.highlighted))
      .slice(0, MAX_VISIBLE_ENTRIES);
  });
  const mapEntries = $derived(visibleEntries.filter((entry) => entry.lat != null && entry.lon != null));
  const mapMarkers = $derived<MapMarker[]>(mapEntries.map((entry) => ({
    lat: entry.lat!,
    lon: entry.lon!,
    label: entry.title,
    iconClass: entry.ref === hoveredRef ? 'embeds-map-view-marker-active' : 'default-map-marker',
    opacity: hoveredRef && entry.ref !== hoveredRef ? 0.5 : 1,
  })));
  const routePaths = $derived<MapRoutePath[]>(visibleEntries
    .filter((entry) => entry.route && entry.route.length > 1)
    .map((entry) => ({
      points: entry.route!,
      color: entry.ref === hoveredRef ? ACTIVE_ROUTE_COLOR : DEFAULT_ROUTE_COLOR,
      weight: 3,
      opacity: hoveredRef && entry.ref !== hoveredRef ? 0.5 : 0.8,
      ref: entry.ref,
      testId: 'embeds-map-view-route-path',
    })));
  const mapCenter = $derived.by(() => {
    const points = [
      ...mapEntries.map((entry) => ({ lat: entry.lat!, lon: entry.lon! })),
      ...routePaths.flatMap((routePath) => routePath.points),
    ];
    if (points.length === 0) return null;
    const lats = points.map((point) => point.lat);
    const lons = points.map((point) => point.lon);
    return {
      lat: (Math.min(...lats) + Math.max(...lats)) / 2,
      lon: (Math.min(...lons) + Math.max(...lons)) / 2,
    };
  });

  function uniqueRefs(refs: string[]): string[] {
    const seen = new Set<string>();
    return refs.filter((ref) => {
      const trimmed = ref.trim();
      if (!trimmed || seen.has(trimmed)) return false;
      seen.add(trimmed);
      return true;
    });
  }

  function firstString(...values: unknown[]): string {
    for (const value of values) {
      if (typeof value === 'string' && value.trim()) return value.trim();
    }
    return '';
  }

  function firstNumber(...values: unknown[]): number | undefined {
    for (const value of values) {
      if (typeof value === 'number' && Number.isFinite(value)) return value;
      if (typeof value === 'string' && value.trim()) {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
      }
    }
    return undefined;
  }

  function arrayFromUnknown(value: unknown): string[] {
    if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
    if (typeof value === 'string') return value.split(/[|,\s]+/).map((item) => item.trim()).filter(Boolean);
    return [];
  }

  function getNestedRecord(record: Record<string, unknown> | null | undefined, key: string): Record<string, unknown> | null {
    const value = record?.[key];
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
  }

  function getCategory(embedType: string | null, content: Record<string, unknown> | null): string {
    const appId = firstString(content?.app_id);
    const skillId = firstString(content?.skill_id);
    const normalized = `${appId}:${skillId}:${embedType || ''}`.toLowerCase();
    if (normalized.includes('event')) return 'event';
    if (normalized.includes('health') || normalized.includes('appointment')) return 'appointment';
    if (normalized.includes('stay') || normalized.includes('hotel') || normalized.includes('home-listing')) return 'stay';
    if (normalized.includes('travel') || normalized.includes('connection') || normalized.includes('flight') || normalized.includes('train')) return 'route';
    if (normalized.includes('map') || normalized.includes('place') || normalized.includes('location')) return 'place';
    return 'place';
  }

  function extractPoint(content: Record<string, unknown> | null): { lat?: number; lon?: number } {
    const location = getNestedRecord(content, 'location');
    const venue = getNestedRecord(content, 'venue');
    const coordinates = getNestedRecord(content, 'coordinates');
    return {
      lat: firstNumber(
        content?.lat,
        content?.latitude,
        content?.location_lat,
        content?.location_latitude,
        content?.venue_lat,
        content?.venue_latitude,
        location?.lat,
        location?.latitude,
        venue?.lat,
        venue?.latitude,
        coordinates?.lat,
        coordinates?.latitude,
      ),
      lon: firstNumber(
        content?.lon,
        content?.lng,
        content?.longitude,
        content?.location_lon,
        content?.location_lng,
        content?.location_longitude,
        content?.venue_lon,
        content?.venue_lng,
        content?.venue_longitude,
        location?.lon,
        location?.lng,
        location?.longitude,
        venue?.lon,
        venue?.lng,
        venue?.longitude,
        coordinates?.lon,
        coordinates?.lng,
        coordinates?.longitude,
      ),
    };
  }

  function addRoutePoint(points: MapPathPoint[], lat: number | undefined, lon: number | undefined): void {
    if (lat == null || lon == null) return;
    const lastPoint = points.at(-1);
    if (lastPoint && lastPoint.lat === lat && lastPoint.lon === lon) return;
    points.push({ lat, lon });
  }

  function extractRouteFromSegmentRecords(segments: unknown[]): MapPathPoint[] {
    const points: MapPathPoint[] = [];
    for (const segment of segments) {
      if (!segment || typeof segment !== 'object' || Array.isArray(segment)) continue;
      const record = segment as Record<string, unknown>;
      addRoutePoint(
        points,
        firstNumber(record.departure_latitude, record.departure_lat),
        firstNumber(record.departure_longitude, record.departure_lng, record.departure_lon),
      );
      addRoutePoint(
        points,
        firstNumber(record.arrival_latitude, record.arrival_lat),
        firstNumber(record.arrival_longitude, record.arrival_lng, record.arrival_lon),
      );
    }
    return points;
  }

  function extractRouteFromStructuredTravelLegs(content: Record<string, unknown> | null): MapPathPoint[] {
    if (!Array.isArray(content?.legs)) return [];
    const segments = content.legs.flatMap((leg) => {
      if (!leg || typeof leg !== 'object' || Array.isArray(leg)) return [];
      const legRecord = leg as Record<string, unknown>;
      return Array.isArray(legRecord.segments) ? legRecord.segments : [];
    });
    return extractRouteFromSegmentRecords(segments);
  }

  function extractRouteFromFlatTravelSegments(content: Record<string, unknown> | null): MapPathPoint[] {
    if (!content) return [];
    const segments: Record<string, unknown>[] = [];

    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let segmentIndex = 0; segmentIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; segmentIndex += 1) {
        const prefix = `legs_${legIndex}_segments_${segmentIndex}`;
        const record = {
          departure_latitude: content[`${prefix}_departure_latitude`],
          departure_longitude: content[`${prefix}_departure_longitude`],
          arrival_latitude: content[`${prefix}_arrival_latitude`],
          arrival_longitude: content[`${prefix}_arrival_longitude`],
        };
        const hasSegmentData = Object.values(record).some((value) => value != null);
        if (!hasSegmentData) {
          if (segmentIndex === 0) break;
          continue;
        }
        segments.push(record);
      }
    }

    return extractRouteFromSegmentRecords(segments);
  }

  function extractRouteFromFlightTrack(content: Record<string, unknown> | null): MapPathPoint[] {
    const flightTrack = getNestedRecord(content, 'flight_track');
    const tracks = flightTrack?.tracks;
    if (!Array.isArray(tracks)) return [];
    return tracks
      .map((point) => {
        if (!point || typeof point !== 'object' || Array.isArray(point)) return null;
        const record = point as Record<string, unknown>;
        const lat = firstNumber(record.lat, record.latitude);
        const lon = firstNumber(record.lon, record.lng, record.longitude);
        return lat != null && lon != null ? { lat, lon } : null;
      })
      .filter((point): point is MapPathPoint => point != null);
  }

  function extractRoute(content: Record<string, unknown> | null): MapPathPoint[] {
    const routeValue = content?.route_points || content?.route || content?.path || content?.polyline_points;
    if (Array.isArray(routeValue)) {
      return routeValue
        .map((point) => {
          if (!point || typeof point !== 'object') return null;
          const record = point as Record<string, unknown>;
          const lat = firstNumber(record.lat, record.latitude);
          const lon = firstNumber(record.lon, record.lng, record.longitude);
          return lat != null && lon != null ? { lat, lon } : null;
        })
        .filter((point): point is MapPathPoint => point != null);
    }

    const structuredTravelRoute = extractRouteFromStructuredTravelLegs(content);
    if (structuredTravelRoute.length > 1) return structuredTravelRoute;

    const flatTravelRoute = extractRouteFromFlatTravelSegments(content);
    if (flatTravelRoute.length > 1) return flatTravelRoute;

    const flightTrackRoute = extractRouteFromFlightTrack(content);
    if (flightTrackRoute.length > 1) return flightTrackRoute;

    const origin = getNestedRecord(content, 'origin');
    const destination = getNestedRecord(content, 'destination');
    const originLat = firstNumber(content?.origin_lat, content?.origin_latitude, origin?.lat, origin?.latitude);
    const originLon = firstNumber(content?.origin_lon, content?.origin_lng, content?.origin_longitude, origin?.lon, origin?.lng, origin?.longitude);
    const destinationLat = firstNumber(content?.destination_lat, content?.destination_latitude, destination?.lat, destination?.latitude);
    const destinationLon = firstNumber(content?.destination_lon, content?.destination_lng, content?.destination_longitude, destination?.lon, destination?.lng, destination?.longitude);
    if (originLat != null && originLon != null && destinationLat != null && destinationLon != null) {
      return [{ lat: originLat, lon: originLon }, { lat: destinationLat, lon: destinationLon }];
    }
    return [];
  }

  function getTitle(ref: string, embedType: string | null, content: Record<string, unknown> | null): string {
    const venue = getNestedRecord(content, 'venue');
    const origin = firstString(content?.origin, content?.origin_name, content?.from);
    const destination = firstString(content?.destination, content?.destination_name, content?.to);
    if (origin && destination) return `${origin} -> ${destination}`;
    return firstString(
      content?.title,
      content?.name,
      content?.displayName,
      content?.display_name,
      venue?.name,
      content?.summary,
      embedType,
      ref,
    );
  }

  function getSubtitle(content: Record<string, unknown> | null, category: string): string {
    const venue = getNestedRecord(content, 'venue');
    const location = getNestedRecord(content, 'location');
    const parts = [
      firstString(content?.date_start, content?.departure, content?.start_time),
      firstString(content?.formattedAddress, content?.formatted_address, content?.address, venue?.address, location?.address),
      firstString(content?.price, content?.formatted_price, content?.provider, content?.booking_provider),
    ].filter(Boolean);
    return parts.length > 0 ? parts.slice(0, 2).join(' | ') : category;
  }

  async function resolveRefToId(ref: string): Promise<string | null> {
    const indexed = await embedStore.resolveByRefDeep(ref);
    return indexed || ref;
  }

  async function resolveEntry(ref: string): Promise<MapViewEntry> {
    const embedId = await resolveRefToId(ref);
    if (!embedId) {
      return { ref, embedId: null, embedType: null, title: ref, subtitle: 'Waiting for embed data', category: 'loading', status: 'loading', highlighted: highlightSet.has(ref) };
    }

    const embedData = await resolveEmbed(embedId);
    if (!embedData) {
      return { ref, embedId, embedType: null, title: ref, subtitle: 'Waiting for embed data', category: 'loading', status: 'loading', highlighted: highlightSet.has(ref) };
    }

    const decodedContent = await decodeToonContent(embedData.content);
    const category = getCategory(embedData.type, decodedContent);
    const point = extractPoint(decodedContent);
    const route = extractRoute(decodedContent);
    return {
      ref,
      embedId,
      embedType: embedData.type,
      title: getTitle(ref, embedData.type, decodedContent),
      subtitle: getSubtitle(decodedContent, category),
      category,
      status: 'ready',
      highlighted: highlightSet.has(ref) || highlightSet.has(embedId),
      lat: point.lat,
      lon: point.lon,
      route,
      embedData,
      decodedContent,
    };
  }

  async function resolveSourceChildren(sourceRef: string): Promise<string[]> {
    const sourceId = await resolveRefToId(sourceRef);
    if (!sourceId) return [];
    const sourceEmbed = await resolveEmbed(sourceId);
    if (!sourceEmbed) return [];
    const decoded = await decodeToonContent(sourceEmbed.content);
    return uniqueRefs([
      ...arrayFromUnknown(sourceEmbed.embed_ids),
      ...arrayFromUnknown(decoded?.embed_ids),
      ...arrayFromUnknown(decoded?.child_embed_ids),
    ]);
  }

  async function loadEntries(): Promise<void> {
    isLoading = true;
    const directRefs = uniqueRefs(embedRefs);
    const sourceChildRefs = (await Promise.all(sourceRefs.map(resolveSourceChildren))).flat();
    const refs = uniqueRefs([...directRefs, ...sourceChildRefs]);

    if (refs.length === 0) {
      entries = sourceRefs.length > 0
        ? sourceRefs.map((ref) => ({ ref, embedId: null, embedType: null, title: ref, subtitle: 'Waiting for source results', category: 'loading', status: 'loading', highlighted: false }))
        : [];
      isLoading = false;
      return;
    }

    entries = await Promise.all(refs.slice(0, MAX_VISIBLE_ENTRIES).map(resolveEntry));
    hoveredRef = null;
    isLoading = false;
  }

  function openEntry(entry: MapViewEntry): void {
    if (!entry.embedId || !entry.embedData) return;
    dispatchEmbedFullscreen({
      embedId: entry.embedId,
      embedType: entry.embedType,
      embedData: entry.embedData,
      decodedContent: entry.decodedContent,
    });
  }

  onMount(() => {
    void loadEntries();
    unsubscribeRefIndex = embedRefIndexVersion.subscribe((version) => {
      if (lastRefIndexVersion === -1) {
        lastRefIndexVersion = version;
        return;
      }
      if (version !== lastRefIndexVersion) {
        lastRefIndexVersion = version;
        void loadEntries();
      }
    });
  });

  onDestroy(() => {
    unsubscribeRefIndex?.();
    unsubscribeRefIndex = null;
  });
</script>

<section class="embeds-map-view" data-testid="embeds-map-view" data-map-view-id={id} aria-label={title}>
  <header class="map-view-toolbar">
    <span class="entry-count" data-testid="embeds-map-view-count">{visibleEntries.length} shown</span>
    {#if categories.length > 1}
      <div class="filter-menu-wrapper">
        <button
          type="button"
          class="filter-button"
          data-testid="embeds-map-view-filter-button"
          aria-haspopup="menu"
          aria-expanded={filtersOpen}
          onclick={() => (filtersOpen = !filtersOpen)}
        >
          <span class="filter-icon" aria-hidden="true"></span>
          <span>{activeCategory === 'all' ? 'Filter' : activeCategory}</span>
        </button>
        {#if filtersOpen}
          <div class="filter-menu" data-testid="embeds-map-view-filter-menu" role="menu">
            {#each categories as category}
              <button
                type="button"
                role="menuitemradio"
                aria-checked={category === activeCategory}
                class:active={category === activeCategory}
                onclick={() => {
                  activeCategory = category;
                  hoveredRef = null;
                  filtersOpen = false;
                }}
              >
                {category === 'all' ? 'All results' : category}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </header>

  <div class="map-view-body">
    <div class="map-view-list" data-testid="embeds-map-view-list">
      {#if isLoading && visibleEntries.length === 0}
        <div class="empty-state">Loading referenced embeds...</div>
      {:else if visibleEntries.length === 0}
        <div class="empty-state">No mappable embeds resolved yet.</div>
      {:else}
        {#each visibleEntries as entry}
          <button
            type="button"
            class="map-view-card"
            class:highlighted={entry.highlighted}
            class:hovered={entry.ref === hoveredRef}
            class:dimmed={hoveredRef != null && entry.ref !== hoveredRef}
            data-testid="embeds-map-view-card"
            data-entry-status={entry.status}
            data-entry-category={entry.category}
            data-highlighted={entry.highlighted ? 'true' : 'false'}
            data-hovered={entry.ref === hoveredRef ? 'true' : 'false'}
            data-dimmed={hoveredRef != null && entry.ref !== hoveredRef ? 'true' : 'false'}
            onclick={() => openEntry(entry)}
            onpointerenter={() => (hoveredRef = entry.ref)}
            onpointerleave={() => {
              if (hoveredRef === entry.ref) hoveredRef = null;
            }}
            onfocus={() => (hoveredRef = entry.ref)}
            onblur={() => {
              if (hoveredRef === entry.ref) hoveredRef = null;
            }}
          >
            <span class="category-pill">{entry.category}</span>
            <strong>{entry.title}</strong>
            <span class="entry-subtitle">{entry.subtitle}</span>
            {#if entry.status !== 'ready'}
              <em>{entry.status === 'loading' ? 'Resolving...' : 'Unavailable'}</em>
            {/if}
          </button>
        {/each}
      {/if}
    </div>

    <div class="map-view-map" data-testid="embeds-map-view-map" data-route-count={routePaths.length}>
      {#if mapCenter}
        <EmbedLeafletMap
          center={mapCenter}
          zoom={12}
          markers={mapMarkers}
          paths={routePaths}
          height="100%"
          minHeight="260px"
          fitBounds={true}
          scrollWheelZoom={false}
        />
      {:else}
        <div class="empty-map">Referenced embeds do not expose coordinates yet.</div>
      {/if}
    </div>
  </div>
</section>

<style>
  .embeds-map-view {
    container-type: inline-size;
    width: 100%;
    border: 1px solid var(--color-grey-25, rgba(0, 0, 0, 0.08));
    border-radius: 18px;
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    overflow: hidden;
    box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.05));
  }

  .map-view-toolbar {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
  }

  .entry-count {
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-xxs);
    white-space: nowrap;
  }

  .filter-menu-wrapper {
    position: relative;
    z-index: var(--z-index-dropdown-1, 10);
  }

  .filter-button {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    border: 1px solid var(--color-grey-30, #e3e3e3);
    border-radius: 999px;
    background: var(--color-grey-10, #f9f9f9);
    color: var(--color-font-primary, #222222);
    padding: 7px 10px;
    font: inherit;
    font-size: var(--font-size-xxs);
    line-height: 1;
    text-transform: capitalize;
    cursor: pointer;
  }

  .filter-icon {
    width: 14px;
    height: 14px;
    background: currentColor;
    -webkit-mask-image: url('@openmates/ui/static/icons/filter.svg');
    mask-image: url('@openmates/ui/static/icons/filter.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .filter-menu {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    display: grid;
    gap: 4px;
    min-width: 150px;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: var(--radius-5, 12px);
    background: var(--color-grey-0, #ffffff);
    box-shadow: var(--shadow-lg, 0 4px 16px rgba(0, 0, 0, 0.15));
    padding: 6px;
  }

  .filter-menu button {
    border: 0;
    border-radius: var(--radius-4, 10px);
    background: transparent;
    color: var(--color-font-primary, #222222);
    padding: 8px 10px;
    font: inherit;
    font-size: var(--font-size-xs);
    text-align: left;
    text-transform: capitalize;
    cursor: pointer;
  }

  .filter-menu button.active,
  .filter-menu button:hover {
    background: var(--color-grey-blue, #e6eaff);
    color: var(--color-font-primary, #222222);
  }

  .filter-menu button[aria-checked='true']::after {
    content: '';
    float: right;
    width: 6px;
    height: 6px;
    margin-top: 5px;
    border-radius: 999px;
    background: currentColor;
  }

  .map-view-body {
    display: grid;
    grid-template-columns: minmax(260px, 34%) minmax(0, 66%);
    min-height: 360px;
    border-top: 1px solid var(--color-grey-20, #f3f3f3);
  }

  .map-view-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
    max-height: 420px;
    overflow: auto;
    padding: 14px;
    background: var(--color-grey-10, #f9f9f9);
    border-right: 1px solid var(--color-grey-20, #f3f3f3);
  }

  .map-view-card {
    display: grid;
    gap: 6px;
    width: 100%;
    min-height: 106px;
    text-align: left;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: var(--radius-6, 14px);
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 12px;
    box-shadow: var(--shadow-xs, 0 2px 4px rgba(0, 0, 0, 0.1));
    cursor: pointer;
    opacity: 1;
    transition: opacity var(--duration-fast, 0.15s) ease, border-color var(--duration-fast, 0.15s) ease;
  }

  .map-view-card.dimmed {
    opacity: 0.5;
  }

  .map-view-card.highlighted,
  .map-view-card.hovered {
    border-color: var(--color-primary, #6c63ff);
  }

  .map-view-card strong {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-small, 0.875rem);
    line-height: 1.28;
    overflow-wrap: anywhere;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .map-view-card .entry-subtitle,
  .map-view-card em {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-xxs, 0.75rem);
    line-height: 1.3;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .category-pill {
    width: fit-content;
    border-radius: 999px;
    padding: 3px 7px;
    background: var(--color-grey-blue, #e6eaff);
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-tiny, 0.6875rem);
    line-height: 1.2;
    text-transform: capitalize;
    white-space: nowrap;
  }

  .map-view-map {
    min-width: 0;
    min-height: 360px;
    background: var(--color-grey-20, #f3f3f3);
  }

  .empty-state,
  .empty-map {
    display: grid;
    min-height: 180px;
    place-items: center;
    padding: 18px;
    color: var(--color-grey-60, #9aa4b5);
    text-align: center;
  }

  :global(.embeds-map-view-marker-active .marker-icon) {
    width: 40px;
    height: 40px;
    background-color: var(--color-primary, #6c63ff);
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
    transition: opacity var(--duration-fast, 0.15s) ease;
  }

  @container (max-width: 720px) {
    .map-view-body {
      display: flex;
      flex-direction: column;
    }

    .map-view-list {
      flex-direction: row;
      max-height: none;
      overflow-x: auto;
      border-right: 0;
      border-bottom: 1px solid var(--color-grey-20, #f3f3f3);
      padding: 14px;
      scroll-snap-type: x mandatory;
    }

    .map-view-card {
      min-width: 240px;
      scroll-snap-align: start;
    }

    .map-view-map {
      min-height: 280px;
    }
  }
</style>
