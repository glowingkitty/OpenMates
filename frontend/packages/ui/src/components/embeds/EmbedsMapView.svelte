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
  let selectedRef = $state<string | null>(null);
  let activeCategory = $state<string>('all');
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
    iconClass: entry.ref === selectedRef || entry.highlighted ? 'embeds-map-view-marker-active' : 'default-map-marker',
  })));
  const routePaths = $derived<MapRoutePath[]>(visibleEntries
    .filter((entry) => entry.route && entry.route.length > 1)
    .map((entry) => ({
      points: entry.route!,
      color: entry.ref === selectedRef || entry.highlighted ? ACTIVE_ROUTE_COLOR : DEFAULT_ROUTE_COLOR,
      weight: entry.ref === selectedRef || entry.highlighted ? 5 : 3,
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
    selectedRef = entries.find((entry) => entry.highlighted)?.ref || entries[0]?.ref || null;
    isLoading = false;
  }

  function openEntry(entry: MapViewEntry): void {
    selectedRef = entry.ref;
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

<section class="embeds-map-view" data-testid="embeds-map-view" data-map-view-id={id}>
  <header class="map-view-header">
    <div>
      <p class="eyebrow">Map view</p>
      <h3>{title}</h3>
    </div>
    <span class="entry-count">{visibleEntries.length} shown</span>
  </header>

  {#if categories.length > 2}
    <div class="map-view-filters" data-testid="embeds-map-view-filters">
      {#each categories as category}
        <button
          type="button"
          class:active={category === activeCategory}
          onclick={() => (activeCategory = category)}
        >
          {category === 'all' ? 'All' : category}
        </button>
      {/each}
    </div>
  {/if}

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
            class:selected={entry.ref === selectedRef}
            data-testid="embeds-map-view-card"
            data-entry-status={entry.status}
            data-entry-category={entry.category}
            data-highlighted={entry.highlighted ? 'true' : 'false'}
            data-selected={entry.ref === selectedRef ? 'true' : 'false'}
            onclick={() => openEntry(entry)}
            onmouseenter={() => (selectedRef = entry.ref)}
            onfocus={() => (selectedRef = entry.ref)}
          >
            <span class="category-pill">{entry.category}</span>
            <strong>{entry.title}</strong>
            <span>{entry.subtitle}</span>
            {#if entry.status !== 'ready'}
              <em>{entry.status === 'loading' ? 'Resolving...' : 'Unavailable'}</em>
            {/if}
          </button>
        {/each}
      {/if}
    </div>

    <div class="map-view-map" data-testid="embeds-map-view-map">
      {#if mapCenter}
        {#key `${selectedRef || 'none'}-${activeCategory}-${visibleEntries.length}`}
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
        {/key}
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
    border: 1px solid var(--color-border, rgba(255, 255, 255, 0.1));
    border-radius: 18px;
    background: color-mix(in srgb, var(--color-background-soft, #111827) 88%, transparent);
    overflow: hidden;
  }

  .map-view-header {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 16px 18px 10px;
  }

  .eyebrow {
    margin: 0 0 4px;
    font-size: var(--font-size-tiny);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--color-grey-50, #8b95a7);
  }

  h3 {
    margin: 0;
    font-size: var(--font-size-lg);
    line-height: 1.25;
  }

  .entry-count {
    align-self: flex-start;
    border-radius: 999px;
    padding: 5px 9px;
    font-size: var(--font-size-xxs);
    background: color-mix(in srgb, var(--color-primary, #6c63ff) 16%, transparent);
    color: var(--color-primary, #6c63ff);
    white-space: nowrap;
  }

  .map-view-filters {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding: 0 18px 12px;
  }

  .map-view-filters button {
    border: 1px solid var(--color-border, rgba(255, 255, 255, 0.12));
    border-radius: 999px;
    background: transparent;
    color: inherit;
    padding: 6px 10px;
    text-transform: capitalize;
    cursor: pointer;
  }

  .map-view-filters button.active {
    border-color: var(--color-primary, #6c63ff);
    background: color-mix(in srgb, var(--color-primary, #6c63ff) 18%, transparent);
  }

  .map-view-body {
    display: grid;
    grid-template-columns: minmax(180px, 30%) minmax(0, 70%);
    min-height: 320px;
  }

  .map-view-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 0 12px 14px 18px;
    overflow: auto;
    max-height: 420px;
  }

  .map-view-card {
    display: grid;
    gap: 4px;
    width: 100%;
    text-align: left;
    border: 1px solid var(--color-border, rgba(255, 255, 255, 0.12));
    border-radius: var(--radius-6);
    background: color-mix(in srgb, var(--color-background, #0b1020) 84%, transparent);
    color: inherit;
    padding: 12px;
    cursor: pointer;
  }

  .map-view-card.highlighted {
    border-color: var(--color-primary, #6c63ff);
  }

  .map-view-card.selected {
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary, #6c63ff) 38%, transparent);
  }

  .map-view-card span,
  .map-view-card em {
    color: var(--color-grey-60, #9aa4b5);
    font-size: var(--font-size-xxs);
  }

  .category-pill {
    width: fit-content;
    border-radius: 999px;
    padding: 3px 7px;
    background: color-mix(in srgb, var(--color-primary, #6c63ff) 14%, transparent);
    text-transform: capitalize;
  }

  .map-view-map {
    min-width: 0;
    min-height: 320px;
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
    width: 44px;
    height: 44px;
    background-color: var(--color-primary, #6c63ff);
    filter: drop-shadow(0 0 12px color-mix(in srgb, var(--color-primary, #6c63ff) 70%, transparent));
    -webkit-mask-image: url('@openmates/ui/static/icons/pin.svg');
    mask-image: url('@openmates/ui/static/icons/pin.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
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
      padding: 0 14px 12px;
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
