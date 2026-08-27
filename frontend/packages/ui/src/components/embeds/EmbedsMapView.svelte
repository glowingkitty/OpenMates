<!--
  frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte

  Virtual in-chat results view over existing location/schedule-capable embeds.
  It resolves refs from local embed data and never calls provider/app-skill
  enrichment endpoints. Missing refs stay visible as loading/unavailable rows.
  Spec: docs/specs/embeds-map-view/spec.yml
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import type { Component } from 'svelte';
  import EmbedLeafletMap, { type MapMarker, type MapPathPoint, type MapRoutePath } from './EmbedLeafletMap.svelte';
  import { decodeToonContent, resolveEmbed, type EmbedData } from '../../services/embedResolver';
  import { embedAvailabilityVersion, embedRefIndexVersion, embedStore } from '../../services/embedStore';
  import { dispatchEmbedFullscreen } from '../../services/embedFullscreenController';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
  import { incrementStreamingRenderMetric } from '../../message_parsing/streamingRenderMetrics';
  import type { EmbedNodeAttributes } from '../../message_parsing/types';

  const MAX_VISIBLE_ENTRIES = 40;
  const MAX_TRAVEL_LEGS = 8;
  const MAX_TRAVEL_SEGMENTS_PER_LEG = 32;
  const DEFAULT_ROUTE_COLOR = 'var(--color-app-travel-start)';
  const ACTIVE_ROUTE_COLOR = 'var(--color-app-travel-end)';
  const INACTIVE_ROUTE_COLOR = 'var(--color-grey-50)';
  const ROUTE_DASH_ARRAY = '10 10';
  const MAP_HYDRATION_ROOT_MARGIN = '320px';
  const HISTOGRAM_BUCKETS = 12;
  const CALENDAR_WEEK_DAYS = 7;
  const CALENDAR_VISIBLE_HOURS = 8;
  const CALENDAR_MINUTES_PER_HOUR = 60;
  const CALENDAR_MIN_EVENT_MINUTES = 38;
  const CALENDAR_DEFAULT_EVENT_MINUTES = 45;
  const CALENDAR_EVENT_STACK_MINUTES = 45;

  interface Props {
    id: string;
    title: string;
    embedRefs?: string[];
    sourceRefs?: string[];
    highlightRefs?: string[];
    interactionMode?: 'open' | 'select';
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
    preview?: EntryPreview | null;
    facets: EntryFacets;
  }

  interface EntryPreview {
    component: unknown;
    props: Record<string, unknown>;
  }

  interface MapViewportBounds {
    north: number;
    south: number;
    east: number;
    west: number;
  }

  interface CoordinatePair {
    lat: number;
    lon: number;
  }

  interface EntryFacets {
    category: string;
    dateOrdinal?: number;
    departureMinutes?: number;
    arrivalMinutes?: number;
    durationMinutes?: number;
    transferMinutes?: number;
    stops?: number;
    price?: number;
    rsvpCount?: number;
    rating?: number;
    providers: string[];
    transportModes: string[];
    trainTypes: string[];
    carriers: string[];
    lines: string[];
    amenities: string[];
    fareCoverage: string[];
  }

  interface RangeFilterControl {
    key: keyof EntryFacets & string;
    label: string;
    type: 'number' | 'time' | 'date';
    min: number;
    max: number;
    values: number[];
    unit?: string;
  }

  interface OptionFilterControl {
    key: keyof EntryFacets & string;
    label: string;
    options: { value: string; label: string; count: number }[];
  }

  type VisualTabId = 'map' | 'calendar';

  interface VisualTab {
    id: VisualTabId;
    label: string;
  }

  interface CalendarEntry {
    entry: MapViewEntry;
    dateOrdinal: number;
    startMinutes: number;
    endMinutes?: number;
  }

  interface CalendarWeekDay {
    dateOrdinal: number;
    entries: CalendarEntry[];
    isToday: boolean;
  }

  let {
    id,
    title,
    embedRefs = [],
    sourceRefs = [],
    highlightRefs = [],
    interactionMode = 'open',
  }: Props = $props();

  let entries = $state<MapViewEntry[]>([]);
  let isLoading = $state(true);
  let hoveredRef = $state<string | null>(null);
  let activeCategory = $state<string>('all');
  let activeVisualTab = $state<VisualTabId>('map');
  let rangeFilters = $state<Record<string, { min: number; max: number }>>({});
  let optionFilters = $state<Record<string, string[]>>({});
  let filtersOpen = $state(false);
  let shouldHydrateMap = $state(false);
  let mapShellElement = $state<HTMLDivElement | null>(null);
  let mapViewportEntryRefs = $state<string[] | null>(null);
  let mapSelectionRefs = $state<string[]>([]);
  let mapSelectionKey = $state<string | null>(null);
  let calendarWeekStartOrdinal = $state<number | null>(null);
  let unsubscribeRefIndex: (() => void) | null = null;
  let unsubscribeEmbedAvailability: (() => void) | null = null;
  let mapHydrationObserver: IntersectionObserver | null = null;
  let mapHydrationTimer: ReturnType<typeof setTimeout> | null = null;
  let mapHydrationIdleCallback: number | null = null;
  let selectedRef = $state<string | null>(null);
  let lastRefIndexVersion = -1;
  let lastEmbedAvailabilityVersion = -1;
  let loadGeneration = 0;

  const entryCache = new Map<string, { signature: string; entry: MapViewEntry }>();
  const sourceChildrenCache = new Map<string, { signature: string; refs: string[] }>();

  export function updateDescriptor(attrs: EmbedNodeAttributes): void {
    id = attrs.id;
    title = attrs.title || 'Results view';
    embedRefs = [...(attrs.mapEmbedRefs || [])];
    sourceRefs = [...(attrs.mapSourceRefs || [])];
    highlightRefs = [...(attrs.mapHighlightRefs || [])];
    void loadEntries();
  }

  const highlightSet = $derived(new Set(highlightRefs));
  const categories = $derived.by(() => {
    const values = Array.from(new Set(entries.filter((entry) => entry.status === 'ready').map((entry) => entry.category)));
    return ['all', ...values];
  });
  const categoryFilteredEntries = $derived.by(() => {
    if (activeCategory === 'all') return entries;
    return entries.filter((entry) => entry.category === activeCategory || entry.status !== 'ready');
  });
  const rangeFilterControls = $derived(deriveRangeControls(categoryFilteredEntries));
  const optionFilterControls = $derived(deriveOptionControls(categoryFilteredEntries));
  const activeFilterCount = $derived(countActiveFilters(rangeFilterControls, optionFilterControls));
  const hasAvailableFilters = $derived(categories.length > 1 || rangeFilterControls.length > 0 || optionFilterControls.length > 0);
  const visibleEntries = $derived.by(() => {
    return categoryFilteredEntries
      .filter(matchesActiveFilters)
      .slice()
      .sort((a, b) => Number(b.highlighted) - Number(a.highlighted))
      .slice(0, MAX_VISIBLE_ENTRIES);
  });
  const carouselEntries = $derived.by(() => {
    if (mapSelectionRefs.length > 0) {
      const selectionSet = new Set(mapSelectionRefs);
      return visibleEntries.filter((entry) => selectionSet.has(entry.ref));
    }
    if (mapViewportEntryRefs && mapViewportEntryRefs.length > 0) {
      const viewportSet = new Set(mapViewportEntryRefs);
      const viewportEntries = visibleEntries.filter((entry) => viewportSet.has(entry.ref));
      if (viewportEntries.length > 0 && viewportEntries.length < visibleEntries.length) return viewportEntries;
    }
    return visibleEntries;
  });
  const isCarouselScoped = $derived(carouselEntries.length < visibleEntries.length || mapSelectionRefs.length > 0);
  const activeGeometryRefs = $derived(mapSelectionRefs.length > 0
    ? new Set(mapSelectionRefs)
    : new Set([hoveredRef ?? selectedRef].filter((ref): ref is string => ref != null)));
  const mapMarkers = $derived<MapMarker[]>(buildMapMarkers(visibleEntries, activeGeometryRefs, mapSelectionKey));
  const endpointMarkerCount = $derived(mapMarkers.filter((marker) => marker.iconClass?.includes('marker-endpoint')).length);
  const stopMarkerCount = $derived(mapMarkers.filter((marker) => marker.iconClass?.includes('marker-stop')).length);
  const routePaths = $derived<MapRoutePath[]>(visibleEntries
    .filter((entry) => entry.route && entry.route.length > 1)
    .map((entry) => ({
      points: entry.route!,
      color: activeGeometryRefs.size === 0
        ? DEFAULT_ROUTE_COLOR
        : activeGeometryRefs.has(entry.ref) ? ACTIVE_ROUTE_COLOR : INACTIVE_ROUTE_COLOR,
      weight: 5,
      opacity: activeGeometryRefs.size > 0 && !activeGeometryRefs.has(entry.ref) ? 0.5 : 0.8,
      dashArray: ROUTE_DASH_ARRAY,
      ref: entry.ref,
      testId: 'embeds-map-view-route-path',
    })));
  const calendarEntries = $derived<CalendarEntry[]>(visibleEntries
    .map(calendarEntryFromMapEntry)
    .filter((entry): entry is CalendarEntry => entry != null)
    .sort((a, b) => a.dateOrdinal - b.dateOrdinal || a.startMinutes - b.startMinutes || a.entry.title.localeCompare(b.entry.title)));
  const firstCalendarWeekStart = $derived(calendarEntries.length > 0 ? weekStartOrdinal(calendarEntries[0].dateOrdinal) : null);
  const activeCalendarWeekStart = $derived(calendarWeekStartOrdinal ?? firstCalendarWeekStart);
  const calendarWeekDays = $derived<CalendarWeekDay[]>(activeCalendarWeekStart == null ? [] : buildCalendarWeekDays(activeCalendarWeekStart, calendarEntries));
  const calendarTimelineStartMinutes = $derived.by(() => {
    if (calendarEntries.length === 0) return 0;
    const earliestStart = Math.min(...calendarEntries.map((entry) => entry.startMinutes));
    return Math.floor(earliestStart / CALENDAR_MINUTES_PER_HOUR) * CALENDAR_MINUTES_PER_HOUR;
  });
  const calendarHourLabels = $derived(Array.from({ length: CALENDAR_VISIBLE_HOURS }, (_, index) => calendarTimelineStartMinutes + (index * CALENDAR_MINUTES_PER_HOUR)));
  const mapCenter = $derived.by(() => {
    const points = [
      ...mapMarkers.map((marker) => ({ lat: marker.lat, lon: marker.lon })),
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
  const visualTabs = $derived<VisualTab[]>(deriveVisualTabs(Boolean(mapCenter), calendarEntries.length > 0));
  const selectedVisualTab = $derived.by(() => {
    if (visualTabs.some((tab) => tab.id === activeVisualTab)) return activeVisualTab;
    return visualTabs[0]?.id ?? 'map';
  });
  const showVisualTabs = $derived(visualTabs.length > 1);

  function normalizeMapViewRef(ref: string): string {
    const trimmed = ref.trim();
    return trimmed.startsWith('embed:') ? trimmed.slice('embed:'.length) : trimmed;
  }

  function uniqueRefs(refs: string[]): string[] {
    const seen = new Set<string>();
    const output: string[] = [];
    for (const ref of refs) {
      const trimmed = normalizeMapViewRef(ref);
      if (!trimmed || seen.has(trimmed)) continue;
      seen.add(trimmed);
      output.push(trimmed);
    }
    return output;
  }

  function markerCoordinateKey(point: MapPathPoint): string {
    return `${point.lat.toFixed(6)}:${point.lon.toFixed(6)}`;
  }

  function buildMapMarkers(sourceEntries: MapViewEntry[], activeRefs: Set<string>, selectedMarkerKey: string | null): MapMarker[] {
    const markers = new Map<string, {
      point: MapPathPoint;
      role: 'endpoint-start' | 'endpoint-end' | 'stop' | 'location';
      ref: string;
      refs: Set<string>;
      label: string;
    }>();

    const addMarker = (
      entry: MapViewEntry,
      point: MapPathPoint,
      role: 'endpoint-start' | 'endpoint-end' | 'stop' | 'location',
      label: string,
    ) => {
      const key = markerCoordinateKey(point);
      const existing = markers.get(key);
      if (!existing) {
        markers.set(key, { point, role, ref: entry.ref, refs: new Set([entry.ref]), label });
        return;
      }
      existing.refs.add(entry.ref);
      if (role.startsWith('endpoint-') && existing.role === 'stop') {
        existing.role = 'endpoint';
        existing.ref = entry.ref;
        existing.label = label;
      }
    };

    for (const entry of sourceEntries) {
      if (entry.route && entry.route.length > 1) {
        entry.route.forEach((point, index) => {
          const isEndpoint = index === 0 || index === entry.route!.length - 1;
          addMarker(
            entry,
            point,
            isEndpoint ? (index === 0 ? 'endpoint-start' : 'endpoint-end') : 'stop',
            point.label || `${entry.title} ${isEndpoint ? (index === 0 ? 'start' : 'end') : 'stop'}`,
          );
        });
      } else if (entry.lat != null && entry.lon != null) {
        addMarker(entry, { lat: entry.lat, lon: entry.lon }, 'location', entry.title);
      }
    }

    return Array.from(markers.values()).map((marker) => {
      const key = markerCoordinateKey(marker.point);
      const relatedRefs = Array.from(marker.refs);
      const isActive = relatedRefs.some((ref) => activeRefs.has(ref));
      return {
        lat: marker.point.lat,
        lon: marker.point.lon,
        label: marker.label,
        ref: isActive ? relatedRefs.find((ref) => activeRefs.has(ref)) ?? marker.ref : marker.ref,
        relatedRefs,
        selectionKey: key,
        selected: selectedMarkerKey === key,
        testId: marker.role === 'stop' ? 'embeds-map-view-stop-marker' : 'embeds-map-view-endpoint-marker',
        iconClass: `embeds-map-view-marker embeds-map-view-marker-${marker.role}${isActive ? ' embeds-map-view-marker-active' : ''}${selectedMarkerKey === key ? ' embeds-map-view-marker-selected' : ''}`,
        opacity: activeRefs.size > 0 && !isActive ? 0.5 : 1,
      };
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

  function coordinatePair(latValue: unknown, lonValue: unknown): CoordinatePair | null {
    const lat = firstNumber(latValue);
    const lon = firstNumber(lonValue);
    if (lat == null || lon == null) return null;
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
    return { lat, lon };
  }

  function firstCoordinatePair(...pairs: Array<[unknown, unknown]>): CoordinatePair | null {
    for (const [latValue, lonValue] of pairs) {
      const point = coordinatePair(latValue, lonValue);
      if (point) return point;
    }
    return null;
  }

  function emptyFacets(category = 'loading'): EntryFacets {
    return {
      category,
      providers: [],
      transportModes: [],
      trainTypes: [],
      carriers: [],
      lines: [],
      amenities: [],
      fareCoverage: [],
    };
  }

  function contentSignature(embedId: string, embedData: EmbedData): string {
    const content = typeof embedData.content === 'string'
      ? embedData.content
      : JSON.stringify(embedData.content ?? null);
    return [
      embedId,
      embedData.type ?? '',
      embedData.updatedAt ?? '',
      content,
      JSON.stringify(embedData.embed_ids ?? []),
    ].join(':');
  }

  function uniqueStrings(values: unknown[]): string[] {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const value of values.flatMap((item) => Array.isArray(item) ? item : [item])) {
      if (typeof value !== 'string' && typeof value !== 'number') continue;
      const normalized = String(value).trim();
      if (!normalized || normalized.toLowerCase() === 'null' || seen.has(normalized)) continue;
      seen.add(normalized);
      result.push(normalized);
    }
    return result;
  }

  function extractArrayRecords(value: unknown): Record<string, unknown>[] {
    if (!Array.isArray(value)) return [];
    return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)));
  }

  function extractTravelSegments(content: Record<string, unknown> | null): Record<string, unknown>[] {
    if (!content) return [];
    const structuredSegments = extractArrayRecords(content.legs).flatMap((leg) => extractArrayRecords(leg.segments));
    if (structuredSegments.length > 0) return structuredSegments;

    const flatSegments: Record<string, unknown>[] = [];
    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let segmentIndex = 0; segmentIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; segmentIndex += 1) {
        const prefix = `legs_${legIndex}_segments_${segmentIndex}`;
        const record = {
          carrier: content[`${prefix}_carrier`],
          carrier_code: content[`${prefix}_carrier_code`],
          mode: content[`${prefix}_mode`],
          line: content[`${prefix}_line`],
          operator: content[`${prefix}_operator`],
          source_provider: content[`${prefix}_source_provider`],
          fare_coverage: content[`${prefix}_fare_coverage`],
          departure_latitude: content[`${prefix}_departure_latitude`],
          departure_longitude: content[`${prefix}_departure_longitude`],
          arrival_latitude: content[`${prefix}_arrival_latitude`],
          arrival_longitude: content[`${prefix}_arrival_longitude`],
        };
        const hasSegmentData = Object.values(record).some((item) => item != null);
        if (!hasSegmentData) {
          if (segmentIndex === 0) break;
          continue;
        }
        flatSegments.push(record);
      }
    }
    return flatSegments;
  }

  function extractTravelLayovers(content: Record<string, unknown> | null): Record<string, unknown>[] {
    if (!content) return [];
    const structuredLayovers = extractArrayRecords(content.legs).flatMap((leg) => extractArrayRecords(leg.layovers));
    if (structuredLayovers.length > 0) return structuredLayovers;

    const flatLayovers: Record<string, unknown>[] = [];
    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let layoverIndex = 0; layoverIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; layoverIndex += 1) {
        const prefix = `legs_${legIndex}_layovers_${layoverIndex}`;
        const record = {
          airport: content[`${prefix}_airport`],
          duration: content[`${prefix}_duration`],
          duration_minutes: content[`${prefix}_duration_minutes`],
          meets_min_transfer: content[`${prefix}_meets_min_transfer`],
        };
        const hasLayoverData = Object.values(record).some((item) => item != null);
        if (!hasLayoverData) {
          if (layoverIndex === 0) break;
          continue;
        }
        flatLayovers.push(record);
      }
    }
    return flatLayovers;
  }

  function minutesFromIsoLike(value: unknown): number | undefined {
    if (typeof value !== 'string') return undefined;
    const match = value.match(/(?:T|\s|^)(\d{1,2}):(\d{2})/);
    if (!match) return undefined;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return undefined;
    return hours * 60 + minutes;
  }

  function minutesFromTimeRange(value: unknown, index: 0 | 1): number | undefined {
    if (typeof value !== 'string') return undefined;
    const matches = Array.from(value.matchAll(/\b(\d{1,2}):(\d{2})\b/g));
    const match = matches[index];
    if (!match) return undefined;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (!Number.isFinite(hours) || !Number.isFinite(minutes) || hours > 23 || minutes > 59) return undefined;
    return hours * 60 + minutes;
  }

  function dateOrdinalFromValue(value: unknown): number | undefined {
    if (typeof value !== 'string') return undefined;
    const match = value.match(/(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return undefined;
    return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / 86400000;
  }

  function durationMinutesFromValue(value: unknown): number | undefined {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value !== 'string') return undefined;
    const hours = value.match(/(\d+(?:\.\d+)?)\s*h/i);
    const minutes = value.match(/(\d+(?:\.\d+)?)\s*m/i);
    const total = (hours ? Number(hours[1]) * 60 : 0) + (minutes ? Number(minutes[1]) : 0);
    return total > 0 ? total : firstNumber(value);
  }

  function shortestTransferMinutes(layovers: Record<string, unknown>[]): number | undefined {
    const values = layovers
      .map((layover) => firstNumber(layover.duration_minutes) ?? durationMinutesFromValue(layover.duration))
      .filter((value): value is number => value != null);
    if (values.length === 0) return undefined;
    return Math.min(...values);
  }

  function dateOrdinalFromContent(content: Record<string, unknown> | null): number | undefined {
    return dateOrdinalFromValue(firstString(
      content?.date,
      content?.slot_datetime,
      content?.date_start,
      content?.departure,
      content?.start_time,
      content?.check_in_date,
      content?.check_in,
    ));
  }

  function departureMinutesFromContent(content: Record<string, unknown> | null): number | undefined {
    return minutesFromIsoLike(firstString(
      content?.departure,
      content?.scheduled_departure,
      content?.slot_datetime,
      content?.start_time,
      content?.date_start,
    )) ?? minutesFromTimeRange(content?.time_range, 0);
  }

  function arrivalMinutesFromContent(content: Record<string, unknown> | null): number | undefined {
    return minutesFromIsoLike(firstString(
      content?.arrival,
      content?.scheduled_arrival,
      content?.end_time,
      content?.date_end,
    )) ?? minutesFromTimeRange(content?.time_range, 1);
  }

  function extractProviders(content: Record<string, unknown> | null, segments: Record<string, unknown>[]): string[] {
    const providerRecords = extractArrayRecords(content?.providers);
    return uniqueStrings([
      content?.provider,
      content?.booking_provider,
      content?.source_provider,
      ...providerRecords.flatMap((provider) => [provider.id, provider.name]),
      ...segments.map((segment) => segment.source_provider),
    ]);
  }

  function extractFacets(category: string, content: Record<string, unknown> | null): EntryFacets {
    const segments = extractTravelSegments(content);
    const layovers = extractTravelLayovers(content);
    const amenities = arrayFromUnknown(content?.amenities ?? content?.required_amenities);
    return {
      category,
      dateOrdinal: dateOrdinalFromContent(content),
      departureMinutes: departureMinutesFromContent(content),
      arrivalMinutes: arrivalMinutesFromContent(content),
      durationMinutes: durationMinutesFromValue(content?.duration ?? content?.duration_minutes),
      transferMinutes: shortestTransferMinutes(layovers),
      stops: firstNumber(content?.stops, content?.transfers, content?.transfer_count),
      price: firstNumber(content?.price, content?.total_price, content?.min_price, content?.max_price),
      rsvpCount: firstNumber(content?.rsvp_count, content?.attendee_count, content?.going_count, content?.capacity_used),
      rating: firstNumber(content?.rating, content?.stars, content?.review_score),
      providers: extractProviders(content, segments),
      transportModes: uniqueStrings([content?.transport_method, content?.mode, ...segments.map((segment) => segment.mode)]),
      trainTypes: uniqueStrings([content?.train_type, content?.carrier, ...segments.map((segment) => segment.carrier)]),
      carriers: uniqueStrings([content?.carrier, content?.carrier_code, ...segments.flatMap((segment) => [segment.carrier, segment.carrier_code])]),
      lines: uniqueStrings([content?.line, content?.number, ...segments.flatMap((segment) => [segment.line, segment.number])]),
      amenities,
      fareCoverage: uniqueStrings([content?.fare_coverage, ...segments.map((segment) => segment.fare_coverage)]),
    };
  }

  function numberFacet(entry: MapViewEntry, key: string): number | undefined {
    const value = entry.facets[key as keyof EntryFacets];
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
  }

  function optionFacet(entry: MapViewEntry, key: string): string[] {
    const value = entry.facets[key as keyof EntryFacets];
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.length > 0) : [];
  }

  function makeRangeControl(
    entriesToInspect: MapViewEntry[],
    key: keyof EntryFacets & string,
    label: string,
    type: RangeFilterControl['type'],
    unit?: string,
  ): RangeFilterControl | null {
    const values = entriesToInspect
      .filter((entry) => entry.status === 'ready')
      .map((entry) => numberFacet(entry, key))
      .filter((value): value is number => value != null);
    if (values.length === 0) return null;
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (min === max) return null;
    return { key, label, type, min, max, values, unit };
  }

  function entriesWithNumberFacet(entriesToInspect: MapViewEntry[], key: keyof EntryFacets & string): MapViewEntry[] {
    return entriesToInspect.filter((entry) => entry.status === 'ready' && numberFacet(entry, key) != null);
  }

  function rangeTimeLabel(entriesToInspect: MapViewEntry[], key: 'departureMinutes' | 'arrivalMinutes'): string {
    const timedEntries = entriesWithNumberFacet(entriesToInspect, key);
    const routeOnly = timedEntries.length > 0 && timedEntries.every((entry) => entry.category === 'route');
    const scheduleOnly = timedEntries.length > 0 && timedEntries.every((entry) => entry.category === 'event' || entry.category === 'appointment');
    if (key === 'departureMinutes') {
      if (routeOnly) return 'Departure time';
      if (scheduleOnly) return 'Time';
      return 'Start time';
    }
    return routeOnly ? 'Arrival time' : 'End time';
  }

  function deriveRangeControls(entriesToInspect: MapViewEntry[]): RangeFilterControl[] {
    return [
      makeRangeControl(entriesToInspect, 'departureMinutes', rangeTimeLabel(entriesToInspect, 'departureMinutes'), 'time'),
      makeRangeControl(entriesToInspect, 'arrivalMinutes', rangeTimeLabel(entriesToInspect, 'arrivalMinutes'), 'time'),
      makeRangeControl(entriesToInspect, 'dateOrdinal', 'Date', 'date'),
      makeRangeControl(entriesToInspect, 'durationMinutes', 'Duration', 'number', 'min'),
      makeRangeControl(entriesToInspect, 'transferMinutes', 'Transfer time', 'number', 'min'),
      makeRangeControl(entriesToInspect, 'stops', 'Stops', 'number'),
      makeRangeControl(entriesToInspect, 'price', 'Price', 'number'),
      makeRangeControl(entriesToInspect, 'rsvpCount', 'RSVP count', 'number'),
      makeRangeControl(entriesToInspect, 'rating', 'Rating', 'number'),
    ].filter((control): control is RangeFilterControl => control != null);
  }

  function makeOptionControl(
    entriesToInspect: MapViewEntry[],
    key: keyof EntryFacets & string,
    label: string,
  ): OptionFilterControl | null {
    const counts = new Map<string, number>();
    for (const entry of entriesToInspect) {
      if (entry.status !== 'ready') continue;
      for (const value of optionFacet(entry, key)) {
        counts.set(value, (counts.get(value) ?? 0) + 1);
      }
    }
    if (counts.size < 2) return null;
    const options = Array.from(counts.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([value, count]) => ({ value, count, label: formatOptionLabel(value) }));
    return { key, label, options };
  }

  function deriveOptionControls(entriesToInspect: MapViewEntry[]): OptionFilterControl[] {
    return [
      makeOptionControl(entriesToInspect, 'providers', 'Provider'),
      makeOptionControl(entriesToInspect, 'transportModes', 'Transport'),
      makeOptionControl(entriesToInspect, 'trainTypes', 'Train type'),
      makeOptionControl(entriesToInspect, 'carriers', 'Carrier'),
      makeOptionControl(entriesToInspect, 'lines', 'Train line'),
      makeOptionControl(entriesToInspect, 'amenities', 'Amenities'),
      makeOptionControl(entriesToInspect, 'fareCoverage', 'Fare coverage'),
    ].filter((control): control is OptionFilterControl => control != null);
  }

  function getRangeValue(control: RangeFilterControl): { min: number; max: number } {
    return rangeFilters[control.key] ?? { min: control.min, max: control.max };
  }

  function clearMapViewportScope(): void {
    mapViewportEntryRefs = null;
    mapSelectionRefs = [];
    mapSelectionKey = null;
    hoveredRef = null;
  }

  function isRangeFilterActive(control: RangeFilterControl): boolean {
    const value = rangeFilters[control.key];
    if (!value) return false;
    return value.min > control.min || value.max < control.max;
  }

  function countActiveFilters(rangeControls: RangeFilterControl[], optionControls: OptionFilterControl[]): number {
    return Number(activeCategory !== 'all')
      + rangeControls.filter(isRangeFilterActive).length
      + optionControls.reduce((count, control) => count + (optionFilters[control.key]?.length ? 1 : 0), 0);
  }

  function matchesActiveFilters(entry: MapViewEntry): boolean {
    if (entry.status !== 'ready') return true;
    for (const control of rangeFilterControls) {
      if (!isRangeFilterActive(control)) continue;
      const facetValue = numberFacet(entry, control.key);
      const rangeValue = getRangeValue(control);
      if (facetValue == null || facetValue < rangeValue.min || facetValue > rangeValue.max) return false;
    }
    for (const control of optionFilterControls) {
      const selectedValues = optionFilters[control.key] ?? [];
      if (selectedValues.length === 0) continue;
      const values = optionFacet(entry, control.key);
      if (!selectedValues.some((value) => values.includes(value))) return false;
    }
    return true;
  }

  function updateRangeFilter(key: string, side: 'min' | 'max', value: number): void {
    const control = rangeFilterControls.find((candidate) => candidate.key === key);
    if (!control) return;
    const current = getRangeValue(control);
    const next = { ...current, [side]: value };
    if (next.min > next.max) {
      if (side === 'min') next.max = next.min;
      else next.min = next.max;
    }
    rangeFilters = { ...rangeFilters, [key]: next };
    clearMapViewportScope();
  }

  function toggleOptionFilter(key: string, value: string): void {
    const current = optionFilters[key] ?? [];
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    optionFilters = { ...optionFilters, [key]: next };
    clearMapViewportScope();
  }

  function clearFilters(): void {
    activeCategory = 'all';
    rangeFilters = {};
    optionFilters = {};
    clearMapViewportScope();
  }

  function deriveVisualTabs(hasMap: boolean, hasCalendar: boolean): VisualTab[] {
    const tabs: VisualTab[] = [];
    if (hasMap) tabs.push({ id: 'map', label: 'Map' });
    if (hasCalendar) tabs.push({ id: 'calendar', label: 'Calendar' });
    return tabs;
  }

  function calendarEntryFromMapEntry(entry: MapViewEntry): CalendarEntry | null {
    if (entry.status !== 'ready') return null;
    const dateOrdinal = numberFacet(entry, 'dateOrdinal');
    const startMinutes = numberFacet(entry, 'departureMinutes');
    if (dateOrdinal == null || startMinutes == null) return null;
    const rawEndMinutes = numberFacet(entry, 'arrivalMinutes');
    const endMinutes = rawEndMinutes != null && rawEndMinutes !== startMinutes ? rawEndMinutes : undefined;
    return { entry, dateOrdinal, startMinutes, endMinutes };
  }

  function weekStartOrdinal(dateOrdinal: number): number {
    const day = new Date(dateOrdinal * 86400000).getUTCDay();
    return dateOrdinal - ((day + 6) % CALENDAR_WEEK_DAYS);
  }

  function todayOrdinal(): number {
    const now = new Date();
    return Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) / 86400000;
  }

  function buildCalendarWeekDays(weekStart: number, items: CalendarEntry[]): CalendarWeekDay[] {
    const today = todayOrdinal();
    return Array.from({ length: CALENDAR_WEEK_DAYS }, (_, index) => {
      const dateOrdinal = weekStart + index;
      return {
        dateOrdinal,
        entries: items.filter((item) => item.dateOrdinal === dateOrdinal),
        isToday: dateOrdinal === today,
      };
    });
  }

  function formatOptionLabel(value: string): string {
    return value
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function formatTimeMinutes(value: number): string {
    const hours = Math.floor(value / 60).toString().padStart(2, '0');
    const minutes = Math.round(value % 60).toString().padStart(2, '0');
    return `${hours}:${minutes}`;
  }

  function formatRangeValue(control: RangeFilterControl, value: number): string {
    if (control.type === 'time') {
      return formatTimeMinutes(value);
    }
    if (control.type === 'date') return dateFromOrdinal(value);
    return `${Math.round(value)}${control.unit ? ` ${control.unit}` : ''}`;
  }

  function formatCalendarTime(item: CalendarEntry): string {
    if (item.endMinutes == null) return formatTimeMinutes(item.startMinutes);
    return `${formatTimeMinutes(item.startMinutes)} - ${formatTimeMinutes(item.endMinutes)}`;
  }

  function formatCalendarHour(value: number): string {
    return `${Math.floor(value / CALENDAR_MINUTES_PER_HOUR).toString().padStart(2, '0')}:00`;
  }

  function calendarItemStyle(item: CalendarEntry, dayItemIndex: number): string {
    const visibleRangeMinutes = CALENDAR_VISIBLE_HOURS * CALENDAR_MINUTES_PER_HOUR;
    const scheduledTopMinutes = Math.max(0, item.startMinutes - calendarTimelineStartMinutes);
    const stackedTopMinutes = dayItemIndex * CALENDAR_EVENT_STACK_MINUTES;
    const topMinutes = Math.min(
      Math.max(scheduledTopMinutes, stackedTopMinutes),
      visibleRangeMinutes - CALENDAR_MIN_EVENT_MINUTES,
    );
    const rawEndMinutes = item.endMinutes != null && item.endMinutes > item.startMinutes
      ? item.endMinutes
      : item.startMinutes + CALENDAR_DEFAULT_EVENT_MINUTES;
    const heightMinutes = Math.min(
      Math.max(rawEndMinutes - item.startMinutes, CALENDAR_MIN_EVENT_MINUTES),
      CALENDAR_EVENT_STACK_MINUTES - 4,
    );

    return `--calendar-item-top-hours: ${topMinutes / CALENDAR_MINUTES_PER_HOUR}; --calendar-item-height-hours: ${heightMinutes / CALENDAR_MINUTES_PER_HOUR};`;
  }

  function formatCalendarDayLabel(value: number): string {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC',
      weekday: 'short',
    }).format(new Date(value * 86400000));
  }

  function formatCalendarDayNumber(value: number): string {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC',
      month: 'short',
      day: 'numeric',
    }).format(new Date(value * 86400000));
  }

  function calendarIsoWeekInfo(value: number): { week: number; year: number } {
    const date = new Date(value * 86400000);
    const day = date.getUTCDay() || CALENDAR_WEEK_DAYS;
    date.setUTCDate(date.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((date.getTime() - yearStart.getTime()) / 86400000) + 1) / CALENDAR_WEEK_DAYS);
    return { week, year: date.getUTCFullYear() };
  }

  function formatCalendarWeekTitle(weekStart: number): string {
    const { week, year } = calendarIsoWeekInfo(weekStart);
    return `Week ${week} ${year}`;
  }

  function formatCalendarWeekLabel(weekStart: number): string {
    const weekEnd = weekStart + CALENDAR_WEEK_DAYS - 1;
    return `${formatCalendarDayNumber(weekStart)} - ${formatCalendarDayNumber(weekEnd)}`;
  }

  function formatProviderLabel(value: string): string {
    return value
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function formatSubtitleDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZone: 'UTC',
    }).format(date);
  }

  function dateFromOrdinal(value: number): string {
    return new Date(value * 86400000).toISOString().slice(0, 10);
  }

  function testIdPart(value: string): string {
    return value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  }

  function histogramBuckets(control: RangeFilterControl): number[] {
    const buckets = Array.from({ length: HISTOGRAM_BUCKETS }, () => 0);
    const span = Math.max(control.max - control.min, 1);
    for (const value of control.values) {
      const index = Math.min(HISTOGRAM_BUCKETS - 1, Math.floor(((value - control.min) / span) * HISTOGRAM_BUCKETS));
      buckets[index] += 1;
    }
    return buckets;
  }

  function histogramBarHeight(control: RangeFilterControl, count: number): number {
    const max = Math.max(1, ...histogramBuckets(control));
    return Math.max(12, Math.round((count / max) * 100));
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
    const gpsCoordinates = getNestedRecord(content, 'gps_coordinates');
    const onlineEventType = firstString(content?.event_type, content?.eventType).toLowerCase() === 'online';
    const onlineVenue = firstString(content?.venue_name, venue?.name).toLowerCase() === 'online event';
    if (onlineEventType || onlineVenue) return {};

    const point = firstCoordinatePair(
      [content?.venue_lat, content?.venue_lon],
      [content?.venue_lat, content?.venue_lng],
      [content?.venue_latitude, content?.venue_longitude],
      [venue?.lat, venue?.lon],
      [venue?.lat, venue?.lng],
      [venue?.latitude, venue?.longitude],
      [content?.location_lat, content?.location_lon],
      [content?.location_lat, content?.location_lng],
      [content?.location_latitude, content?.location_longitude],
      [location?.lat, location?.lon],
      [location?.lat, location?.lng],
      [location?.latitude, location?.longitude],
      [content?.gps_coordinates_latitude, content?.gps_coordinates_longitude],
      [content?.gps_coordinates_latitude, content?.gps_coordinates_lon],
      [content?.gps_coordinates_latitude, content?.gps_coordinates_lng],
      [gpsCoordinates?.latitude, gpsCoordinates?.longitude],
      [gpsCoordinates?.lat, gpsCoordinates?.lon],
      [gpsCoordinates?.lat, gpsCoordinates?.lng],
      [coordinates?.latitude, coordinates?.longitude],
      [coordinates?.lat, coordinates?.lon],
      [coordinates?.lat, coordinates?.lng],
      [content?.latitude, content?.longitude],
      [content?.lat, content?.lon],
      [content?.lat, content?.lng],
    );
    return point ?? {};
  }

  function addRoutePoint(points: MapPathPoint[], lat: number | undefined, lon: number | undefined, label = ''): void {
    if (lat == null || lon == null) return;
    const lastPoint = points.at(-1);
    if (lastPoint && lastPoint.lat === lat && lastPoint.lon === lon) {
      if (!lastPoint.label && label) lastPoint.label = label;
      return;
    }
    points.push({ lat, lon, ...(label ? { label } : {}) });
  }

  function travelLocationLabels(content: Record<string, unknown> | null): Map<string, string> {
    const labels = new Map<string, string>();
    const addLabel = (codeValue: unknown, nameValue: unknown) => {
      const code = firstString(codeValue);
      const name = firstString(nameValue);
      if (!code || !name) return;
      labels.set(code, name.includes(code) ? name : `${name} (${code})`);
    };
    for (const leg of extractArrayRecords(content?.legs)) {
      for (const layover of extractArrayRecords(leg.layovers)) {
        addLabel(layover.airport_code ?? layover.station_code ?? layover.code, layover.airport ?? layover.station ?? layover.name);
      }
    }
    if (!content) return labels;
    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let layoverIndex = 0; layoverIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; layoverIndex += 1) {
        const prefix = `legs_${legIndex}_layovers_${layoverIndex}`;
        const code = content[`${prefix}_airport_code`] ?? content[`${prefix}_station_code`] ?? content[`${prefix}_code`];
        const name = content[`${prefix}_airport`] ?? content[`${prefix}_station`] ?? content[`${prefix}_name`];
        if (code == null && name == null) {
          if (layoverIndex === 0) break;
          continue;
        }
        addLabel(code, name);
      }
    }
    return labels;
  }

  function extractRouteFromSegmentRecords(segments: unknown[], locationLabels: Map<string, string>): MapPathPoint[] {
    const points: MapPathPoint[] = [];
    for (const segment of segments) {
      if (!segment || typeof segment !== 'object' || Array.isArray(segment)) continue;
      const record = segment as Record<string, unknown>;
      addRoutePoint(
        points,
        firstNumber(record.departure_latitude, record.departure_lat),
        firstNumber(record.departure_longitude, record.departure_lng, record.departure_lon),
        locationLabels.get(firstString(record.departure_station)) ?? firstString(record.departure_station),
      );
      addRoutePoint(
        points,
        firstNumber(record.arrival_latitude, record.arrival_lat),
        firstNumber(record.arrival_longitude, record.arrival_lng, record.arrival_lon),
        locationLabels.get(firstString(record.arrival_station)) ?? firstString(record.arrival_station),
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
    return extractRouteFromSegmentRecords(segments, travelLocationLabels(content));
  }

  function extractRouteFromFlatTravelSegments(content: Record<string, unknown> | null): MapPathPoint[] {
    if (!content) return [];
    const segments: Record<string, unknown>[] = [];

    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let segmentIndex = 0; segmentIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; segmentIndex += 1) {
        const prefix = `legs_${legIndex}_segments_${segmentIndex}`;
        const record = {
          departure_station: content[`${prefix}_departure_station`],
          departure_latitude: content[`${prefix}_departure_latitude`],
          departure_longitude: content[`${prefix}_departure_longitude`],
          arrival_station: content[`${prefix}_arrival_station`],
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

    return extractRouteFromSegmentRecords(segments, travelLocationLabels(content));
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
          const label = firstString(record.label, record.name, record.station, record.city);
          return lat != null && lon != null ? { lat, lon, ...(label ? { label } : {}) } : null;
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
      return [
        { lat: originLat, lon: originLon, ...(firstString(content?.origin_name, content?.origin) ? { label: firstString(content?.origin_name, content?.origin) } : {}) },
        { lat: destinationLat, lon: destinationLon, ...(firstString(content?.destination_name, content?.destination) ? { label: firstString(content?.destination_name, content?.destination) } : {}) },
      ];
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
    const dateValue = firstString(content?.date_start, content?.departure, content?.start_time);
    const providerValue = firstString(content?.provider, content?.booking_provider);
    const parts = [
      dateValue ? formatSubtitleDate(dateValue) : '',
      firstString(content?.formattedAddress, content?.formatted_address, content?.address, venue?.address, location?.address),
      firstString(content?.price, content?.formatted_price, providerValue ? formatProviderLabel(providerValue) : ''),
    ].filter(Boolean);
    return parts.length > 0 ? parts.slice(0, 2).join(' | ') : category;
  }

  async function resolveRefToId(ref: string): Promise<string | null> {
    const normalizedRef = normalizeMapViewRef(ref);
    const indexed = await embedStore.resolveByRefDeep(normalizedRef);
    return indexed || normalizedRef;
  }

  async function resolveEntryPreview(entry: MapViewEntry): Promise<EntryPreview | null> {
    if (!entry.embedId || !entry.embedData || !entry.decodedContent) return null;
    const preview = await embedPreviewRegistry.resolve({
      embedId: entry.embedId,
      embedData: {
        ...entry.embedData,
        app_id: entry.decodedContent.app_id ?? entry.embedData.app_id,
        skill_id: entry.decodedContent.skill_id ?? entry.embedData.skill_id,
      },
      decodedContent: entry.decodedContent,
      onFullscreen: () => openEntry(entry),
    });
    if (preview && ['connection', 'travel-connection', 'travel-route'].includes(entry.embedType ?? '')) {
      preview.props.customHeight = 200;
    }
    return preview;
  }

  async function resolveEntry(ref: string): Promise<MapViewEntry> {
    const embedId = await resolveRefToId(ref);
    if (!embedId) {
      return { ref, embedId: null, embedType: null, title: ref, subtitle: 'Waiting for embed data', category: 'loading', status: 'loading', highlighted: highlightSet.has(ref), facets: emptyFacets() };
    }

    const embedData = await resolveEmbed(embedId);
    if (!embedData) {
      return { ref, embedId, embedType: null, title: ref, subtitle: 'Waiting for embed data', category: 'loading', status: 'loading', highlighted: highlightSet.has(ref), facets: emptyFacets() };
    }

    const signature = contentSignature(embedId, embedData);
    const cached = entryCache.get(ref);
    if (cached?.signature === signature) {
      return {
        ...cached.entry,
        highlighted: highlightSet.has(ref) || highlightSet.has(embedId),
      };
    }

    const decodedContent = await decodeToonContent(embedData.content);
    const category = getCategory(embedData.type, decodedContent);
    const point = extractPoint(decodedContent);
    const route = extractRoute(decodedContent);
    const entry = {
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
      preview: null,
      facets: extractFacets(category, decodedContent),
    } satisfies MapViewEntry;
    entry.preview = await resolveEntryPreview(entry);
    entryCache.set(ref, { signature, entry });
    return entry;
  }

  async function resolveSourceChildren(sourceRef: string): Promise<string[]> {
    const sourceId = await resolveRefToId(sourceRef);
    if (!sourceId) return [];
    const sourceEmbed = await resolveEmbed(sourceId);
    if (!sourceEmbed) return [];
    const signature = contentSignature(sourceId, sourceEmbed);
    const cached = sourceChildrenCache.get(sourceRef);
    if (cached?.signature === signature) return cached.refs;
    const decoded = await decodeToonContent(sourceEmbed.content);
    const refs = uniqueRefs([
      ...arrayFromUnknown(sourceEmbed.embed_ids),
      ...arrayFromUnknown(decoded?.embed_ids),
      ...arrayFromUnknown(decoded?.child_embed_ids),
    ]);
    sourceChildrenCache.set(sourceRef, { signature, refs });
    return refs;
  }

  async function loadEntries(): Promise<void> {
    const generation = loadGeneration + 1;
    loadGeneration = generation;
    isLoading = true;
    const directRefs = uniqueRefs(embedRefs);
    const sourceChildRefs = (await Promise.all(sourceRefs.map(resolveSourceChildren))).flat();
    const refs = uniqueRefs([...directRefs, ...sourceChildRefs]);

    if (generation !== loadGeneration) return;

    if (refs.length === 0) {
      entries = sourceRefs.length > 0
        ? sourceRefs.map((ref) => ({ ref, embedId: null, embedType: null, title: ref, subtitle: 'Waiting for source results', category: 'loading', status: 'loading', highlighted: false, facets: emptyFacets() }))
        : [];
      isLoading = false;
      return;
    }

    const resolvedEntries = await Promise.all(refs.slice(0, MAX_VISIBLE_ENTRIES).map(resolveEntry));
    if (generation !== loadGeneration) return;
    entries = resolvedEntries;
    hoveredRef = null;
    isLoading = false;
  }

  function openEntry(entry: MapViewEntry): void {
    if (!entry.embedId || !entry.embedData) return;
    if (interactionMode === 'select') {
      selectedRef = entry.ref;
      return;
    }
    dispatchEmbedFullscreen({
      embedId: entry.embedId,
      embedType: entry.embedType,
      embedData: entry.embedData,
      decodedContent: entry.decodedContent,
    });
  }

  function selectMapEntry(ref: string, relatedRefs = [ref], selectionKey?: string): void {
    const visibleRefSet = new Set(visibleEntries.map((entry) => entry.ref));
    const matchingRefs = relatedRefs.filter((candidate) => visibleRefSet.has(candidate));
    if (matchingRefs.length === 0) return;
    selectedRef = matchingRefs[0];
    mapSelectionRefs = matchingRefs;
    mapSelectionKey = selectionKey ?? null;
    hoveredRef = null;
  }

  function showAllResults(): void {
    mapViewportEntryRefs = null;
    mapSelectionRefs = [];
    mapSelectionKey = null;
    selectedRef = null;
    hoveredRef = null;
  }

  function handleEntryPointerLeave(ref: string): void {
    if (hoveredRef === ref) hoveredRef = null;
  }

  function pointIsInBounds(point: MapPathPoint, bounds: MapViewportBounds): boolean {
    const inLatitude = point.lat >= bounds.south && point.lat <= bounds.north;
    const inLongitude = bounds.west <= bounds.east
      ? point.lon >= bounds.west && point.lon <= bounds.east
      : point.lon >= bounds.west || point.lon <= bounds.east;
    return inLatitude && inLongitude;
  }

  function entryIntersectsBounds(entry: MapViewEntry, bounds: MapViewportBounds): boolean {
    if (entry.lat != null && entry.lon != null && pointIsInBounds({ lat: entry.lat, lon: entry.lon }, bounds)) return true;
    return entry.route?.some((point) => pointIsInBounds(point, bounds)) ?? false;
  }

  function handleMapBoundsChange(bounds: MapViewportBounds): void {
    if (mapSelectionRefs.length > 0) return;
    const refsInBounds = visibleEntries
      .filter((entry) => entryIntersectsBounds(entry, bounds))
      .map((entry) => entry.ref);
    mapViewportEntryRefs = refsInBounds.length > 0 && refsInBounds.length < visibleEntries.length ? refsInBounds : null;
  }

  function moveCalendarWeek(delta: -1 | 1): void {
    if (activeCalendarWeekStart == null) return;
    calendarWeekStartOrdinal = activeCalendarWeekStart + (delta * CALENDAR_WEEK_DAYS);
  }

  // Svelte's dynamic component type needs a permissive cast because registry
  // entries point at heterogeneous preview components with different props.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function getRenderableComponent(component: unknown): Component<any, any, any> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return component as Component<any, any, any>;
  }

  function scheduleMapHydration(): void {
    if (shouldHydrateMap || mapHydrationTimer || mapHydrationIdleCallback !== null) return;
    const hydrate = () => {
      mapHydrationTimer = null;
      mapHydrationIdleCallback = null;
      shouldHydrateMap = true;
      incrementStreamingRenderMetric('mapHydrations');
      mapHydrationObserver?.disconnect();
      mapHydrationObserver = null;
    };
    const requestIdle = (globalThis as typeof globalThis & { requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number }).requestIdleCallback;
    if (requestIdle) {
      mapHydrationIdleCallback = requestIdle(hydrate, { timeout: 600 });
      return;
    }
    mapHydrationTimer = setTimeout(hydrate, 80);
  }

  function setupMapHydrationObserver(): void {
    if (!mapShellElement || shouldHydrateMap || mapHydrationObserver) return;
    if (typeof IntersectionObserver === 'undefined') {
      scheduleMapHydration();
      return;
    }

    mapHydrationObserver = new IntersectionObserver((observedEntries) => {
      if (observedEntries.some((entry) => entry.isIntersecting)) scheduleMapHydration();
    }, { rootMargin: MAP_HYDRATION_ROOT_MARGIN });
    mapHydrationObserver.observe(mapShellElement);
  }

  onMount(() => {
    unsubscribeRefIndex = embedRefIndexVersion.subscribe((version) => {
      if (lastRefIndexVersion === -1) {
        lastRefIndexVersion = version;
        return;
      }
      if (version !== lastRefIndexVersion) {
        lastRefIndexVersion = version;
        if (isLoading || entries.some((entry) => entry.status !== 'ready')) void loadEntries();
      }
    });
    unsubscribeEmbedAvailability = embedAvailabilityVersion.subscribe((version) => {
      if (lastEmbedAvailabilityVersion === -1) {
        lastEmbedAvailabilityVersion = version;
        return;
      }
      if (version !== lastEmbedAvailabilityVersion) {
        lastEmbedAvailabilityVersion = version;
        if (isLoading || entries.some((entry) => entry.status !== 'ready')) void loadEntries();
      }
    });
    void loadEntries();
  });

  onDestroy(() => {
    unsubscribeRefIndex?.();
    unsubscribeRefIndex = null;
    unsubscribeEmbedAvailability?.();
    unsubscribeEmbedAvailability = null;
    mapHydrationObserver?.disconnect();
    mapHydrationObserver = null;
    if (mapHydrationTimer) clearTimeout(mapHydrationTimer);
    mapHydrationTimer = null;
    const cancelIdle = (globalThis as typeof globalThis & { cancelIdleCallback?: (handle: number) => void }).cancelIdleCallback;
    if (mapHydrationIdleCallback !== null && cancelIdle) cancelIdle(mapHydrationIdleCallback);
    mapHydrationIdleCallback = null;
  });

  $effect(() => {
    if (!mapShellElement || !mapCenter || shouldHydrateMap) return;
    if (selectedVisualTab === 'map') {
      scheduleMapHydration();
      return;
    }
    setupMapHydrationObserver();
  });

  $effect(() => {
    if (visualTabs.length > 0 && !visualTabs.some((tab) => tab.id === activeVisualTab)) {
      activeVisualTab = visualTabs[0].id;
    }
  });

  $effect(() => {
    if (firstCalendarWeekStart == null) {
      calendarWeekStartOrdinal = null;
      return;
    }
    if (calendarWeekStartOrdinal == null) {
      calendarWeekStartOrdinal = firstCalendarWeekStart;
    }
  });

  $effect(() => {
    if (mapSelectionRefs.length > 0) {
      const visibleRefSet = new Set(visibleEntries.map((entry) => entry.ref));
      const nextSelectionRefs = mapSelectionRefs.filter((ref) => visibleRefSet.has(ref));
      if (nextSelectionRefs.length !== mapSelectionRefs.length) mapSelectionRefs = nextSelectionRefs;
      if (nextSelectionRefs.length === 0) mapSelectionKey = null;
    }
    if (selectedRef && !visibleEntries.some((entry) => entry.ref === selectedRef)) {
      selectedRef = null;
    }
  });
</script>

<section class="embeds-results-view embeds-map-view" data-testid="embeds-map-view" data-results-view-id={id} data-map-view-id={id} data-loading={isLoading ? 'true' : 'false'} aria-label={title}>
  <header class="map-view-toolbar">
    <span class="entry-count" data-testid="embeds-map-view-count">{visibleEntries.length} shown</span>
    {#if showVisualTabs}
      <div class="results-view-tabs" data-testid="embeds-results-view-tabs" role="tablist" aria-label="Result views">
        {#each visualTabs as tab}
          <button
            type="button"
            class:active={selectedVisualTab === tab.id}
            data-testid={`embeds-results-view-tab-${tab.id}`}
            role="tab"
            aria-label={tab.label}
            aria-selected={selectedVisualTab === tab.id}
            aria-controls={`embeds-results-view-panel-${tab.id}`}
            onclick={() => (activeVisualTab = tab.id)}
          >
            <span class={`results-view-tab-icon results-view-tab-icon-${tab.id}`} data-testid={`embeds-results-view-tab-${tab.id}-icon`} aria-hidden="true"></span>
            <span class="visually-hidden">{tab.label}</span>
          </button>
        {/each}
      </div>
    {/if}
    {#if hasAvailableFilters}
      <div class="filter-menu-wrapper">
        <button
          type="button"
          class="filter-button"
          data-testid="embeds-map-view-filter-button"
          data-icon={filtersOpen ? 'close' : 'filter'}
          aria-label={activeFilterCount === 0 ? 'Filter results' : `Filter results, ${activeFilterCount} active`}
          aria-controls={`${id}-filter-panel`}
          aria-expanded={filtersOpen}
          onclick={() => (filtersOpen = !filtersOpen)}
        >
          <span class:filter-icon={!filtersOpen} class:close-icon={filtersOpen} aria-hidden="true"></span>
          <span class="visually-hidden">{activeFilterCount === 0 ? 'Filter' : `Filter (${activeFilterCount})`}</span>
        </button>
        {#if filtersOpen}
          <div id={`${id}-filter-panel`} class="filter-menu" data-testid="embeds-map-view-filter-menu" data-layout="results-panel" role="region" aria-label="Filter results">
            <div class="filter-menu-header">
              <strong>Filters</strong>
              {#if activeFilterCount > 0}
                <button type="button" data-testid="embeds-map-view-clear-filters" onclick={clearFilters}>Clear all</button>
              {/if}
            </div>
            <p class="filter-summary" data-testid="embeds-map-view-filter-summary">
              {visibleEntries.length} of {categoryFilteredEntries.length} results remain
            </p>

            <div class="filter-controls" data-testid="embeds-map-view-filter-controls">
              {#if categories.length > 1}
                <div class="filter-section">
                  <span class="filter-section-title">Type</span>
                  <div class="filter-category-options">
                    {#each categories as category}
                      <button
                        type="button"
                        aria-pressed={category === activeCategory}
                        class:active={category === activeCategory}
                        onclick={() => {
                          activeCategory = category;
                          clearMapViewportScope();
                        }}
                      >
                        {category === 'all' ? 'All results' : category}
                      </button>
                    {/each}
                  </div>
                </div>
              {/if}

              {#each rangeFilterControls as control}
                {@const rangeValue = getRangeValue(control)}
                <div class="filter-section" data-testid={`embeds-map-view-filter-${control.key}`}>
                  <div class="range-label-row">
                    <span class="filter-section-title">{control.label}</span>
                    <span>{formatRangeValue(control, rangeValue.min)} - {formatRangeValue(control, rangeValue.max)}</span>
                  </div>
                  {#if control.type === 'time'}
                    <div class="filter-histogram" aria-hidden="true">
                      {#each histogramBuckets(control) as bucket}
                        <span style={`height: ${histogramBarHeight(control, bucket)}%;`}></span>
                      {/each}
                    </div>
                  {/if}
                  <div class="range-inputs">
                    {#if control.type === 'date'}
                      <input
                        data-testid={`embeds-map-view-filter-${control.key}-min`}
                        aria-label={`${control.label} minimum`}
                        type="date"
                        min={dateFromOrdinal(control.min)}
                        max={dateFromOrdinal(control.max)}
                        value={dateFromOrdinal(rangeValue.min)}
                        oninput={(event) => updateRangeFilter(control.key, 'min', dateOrdinalFromValue((event.currentTarget as HTMLInputElement).value) ?? control.min)}
                      />
                      <input
                        data-testid={`embeds-map-view-filter-${control.key}-max`}
                        aria-label={`${control.label} maximum`}
                        type="date"
                        min={dateFromOrdinal(control.min)}
                        max={dateFromOrdinal(control.max)}
                        value={dateFromOrdinal(rangeValue.max)}
                        oninput={(event) => updateRangeFilter(control.key, 'max', dateOrdinalFromValue((event.currentTarget as HTMLInputElement).value) ?? control.max)}
                      />
                    {:else}
                      <input
                        data-testid={`embeds-map-view-filter-${control.key}-min`}
                        aria-label={`${control.label} minimum`}
                        type="range"
                        min={control.min}
                        max={control.max}
                        step={control.type === 'time' ? 5 : 1}
                        value={rangeValue.min}
                        oninput={(event) => updateRangeFilter(control.key, 'min', Number((event.currentTarget as HTMLInputElement).value))}
                      />
                      <input
                        data-testid={`embeds-map-view-filter-${control.key}-max`}
                        aria-label={`${control.label} maximum`}
                        type="range"
                        min={control.min}
                        max={control.max}
                        step={control.type === 'time' ? 5 : 1}
                        value={rangeValue.max}
                        oninput={(event) => updateRangeFilter(control.key, 'max', Number((event.currentTarget as HTMLInputElement).value))}
                      />
                    {/if}
                  </div>
                </div>
              {/each}

              {#each optionFilterControls as control}
                <div class="filter-section" data-testid={`embeds-map-view-filter-${control.key}`}>
                  <span class="filter-section-title">{control.label}</span>
                  <div class="option-chips">
                    {#each control.options as option}
                      <button
                        type="button"
                        data-testid={`embeds-map-view-option-${testIdPart(control.label)}-${testIdPart(option.value)}`}
                        class:active={(optionFilters[control.key] ?? []).includes(option.value)}
                        aria-pressed={(optionFilters[control.key] ?? []).includes(option.value)}
                        onclick={() => toggleOptionFilter(control.key, option.value)}
                      >
                        {option.label} <span>{option.count}</span>
                      </button>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </header>

  <div class="map-view-body" class:calendar-active={selectedVisualTab === 'calendar'} aria-hidden={filtersOpen}>
    {#if selectedVisualTab === 'map'}
      <div class="map-view-list" data-testid="embeds-map-view-list">
      <div class="map-view-carousel" data-testid="embeds-map-view-carousel" aria-label="Result previews">
        {#if isLoading && carouselEntries.length === 0}
          <div class="empty-state">Loading referenced embeds...</div>
        {:else if carouselEntries.length === 0}
          <div class="empty-state">No mappable embeds resolved yet.</div>
        {:else}
          {#each carouselEntries as entry}
            <div
              class="map-view-card"
              class:highlighted={entry.highlighted}
              class:selected={selectedRef === entry.ref}
              class:hovered={entry.ref === hoveredRef}
              class:dimmed={activeGeometryRefs.size > 0 && !activeGeometryRefs.has(entry.ref)}
              data-testid="embeds-map-view-card"
              data-entry-status={entry.status}
              data-entry-category={entry.category}
              data-highlighted={entry.highlighted ? 'true' : 'false'}
              data-selected={selectedRef === entry.ref ? 'true' : 'false'}
              data-hovered={entry.ref === hoveredRef ? 'true' : 'false'}
              data-dimmed={activeGeometryRefs.size > 0 && !activeGeometryRefs.has(entry.ref) ? 'true' : 'false'}
              role="group"
              aria-label={entry.title}
              onpointerenter={() => (hoveredRef = entry.ref)}
              onpointerleave={() => handleEntryPointerLeave(entry.ref)}
              onfocusin={() => (hoveredRef = entry.ref)}
              onfocusout={() => handleEntryPointerLeave(entry.ref)}
            >
              {#if entry.preview}
                {@const Component = getRenderableComponent(entry.preview.component)}
                <Component {...entry.preview.props} />
              {:else}
                <button type="button" class="fallback-card" data-testid="embeds-map-view-fallback-card" onclick={() => openEntry(entry)}>
                  <span class="category-pill">{entry.category}</span>
                  <strong>{entry.title}</strong>
                  <span class="entry-subtitle">{entry.subtitle}</span>
                  {#if entry.status !== 'ready'}
                    <em>{entry.status === 'loading' ? 'Resolving...' : 'Unavailable'}</em>
                  {/if}
                </button>
              {/if}
            </div>
          {/each}
        {/if}
      </div>
      {#if isCarouselScoped}
        <button type="button" class="show-all-results" data-testid="embeds-map-view-show-all-results" onclick={showAllResults}>
          Show all results
        </button>
      {/if}
      </div>
    {/if}

    <div class="results-view-pane" data-testid="embeds-results-view-pane" data-active-tab={selectedVisualTab}>
      {#if selectedVisualTab === 'calendar'}
        <div class="results-view-calendar" data-testid="embeds-results-view-calendar" id="embeds-results-view-panel-calendar" role="tabpanel" aria-label="Calendar results">
          {#if activeCalendarWeekStart != null}
            <header class="calendar-week-toolbar">
              <button type="button" aria-label="Previous week" onclick={() => moveCalendarWeek(-1)}><span aria-hidden="true">&lt;</span></button>
              <strong data-testid="embeds-results-view-calendar-week-label">
                {formatCalendarWeekTitle(activeCalendarWeekStart)}
                <span class="visually-hidden"> {formatCalendarWeekLabel(activeCalendarWeekStart)}</span>
              </strong>
              <button type="button" aria-label="Next week" onclick={() => moveCalendarWeek(1)}><span aria-hidden="true">&gt;</span></button>
            </header>
            <div class="calendar-week" data-testid="embeds-results-view-calendar-week">
              <div class="calendar-time-column" aria-hidden="true">
                <span class="calendar-time-column-spacer"></span>
                <div class="calendar-time-slots">
                  {#each calendarHourLabels as hour}
                    <span>{formatCalendarHour(hour)}</span>
                  {/each}
                </div>
              </div>
              {#each calendarWeekDays as day}
                <section class="calendar-day" class:today={day.isToday} data-testid="embeds-results-view-calendar-day">
                  <header class="calendar-day-header">
                    <span>{formatCalendarDayLabel(day.dateOrdinal)}</span>
                    <strong>{formatCalendarDayNumber(day.dateOrdinal)}</strong>
                  </header>
                  <div class="calendar-items">
                    {#each day.entries as item, itemIndex}
                      <button
                        type="button"
                        class="calendar-item"
                        class:highlighted={item.entry.highlighted}
                        class:selected={selectedRef === item.entry.ref}
                        class:hovered={item.entry.ref === hoveredRef}
                        data-testid="embeds-results-view-calendar-item"
                        data-entry-category={item.entry.category}
                        data-selected={selectedRef === item.entry.ref ? 'true' : 'false'}
                        style={calendarItemStyle(item, itemIndex)}
                        onclick={() => openEntry(item.entry)}
                        onpointerenter={() => (hoveredRef = item.entry.ref)}
                        onpointerleave={() => handleEntryPointerLeave(item.entry.ref)}
                        onfocus={() => (hoveredRef = item.entry.ref)}
                        onblur={() => handleEntryPointerLeave(item.entry.ref)}
                      >
                        <span class="calendar-time">{formatCalendarTime(item)}</span>
                        <span class="calendar-copy">
                          <strong>{item.entry.title}</strong>
                          <span>{item.entry.subtitle}</span>
                        </span>
                      </button>
                    {/each}
                  </div>
                </section>
              {/each}
            </div>
          {:else}
            <div class="empty-map">Referenced embeds do not expose date and time yet.</div>
          {/if}
        </div>
      {:else}
        <div
          class="map-view-map"
          data-testid="embeds-map-view-map"
          data-marker-count={mapMarkers.length}
          data-endpoint-marker-count={endpointMarkerCount}
          data-stop-marker-count={stopMarkerCount}
          data-route-count={routePaths.length}
          data-map-hydrated={shouldHydrateMap ? 'true' : 'false'}
          id="embeds-results-view-panel-map"
          role="tabpanel"
          aria-label="Mapped results"
          bind:this={mapShellElement}
        >
          {#if mapCenter}
            {#if shouldHydrateMap}
              <EmbedLeafletMap
                center={mapCenter}
                zoom={12}
                markers={mapMarkers}
                paths={routePaths}
                height="100%"
                minHeight="278px"
                fitBounds={true}
                scrollWheelZoom={false}
                zoomControlPosition="topleft"
                onMarkerSelect={selectMapEntry}
                onRouteSelect={selectMapEntry}
                onBoundsChange={handleMapBoundsChange}
              />
            {:else}
              <div class="map-hydration-placeholder">Map loading when visible...</div>
            {/if}
          {:else}
            <div class="empty-map">Referenced embeds do not expose coordinates yet.</div>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</section>

<style>
  .embeds-map-view {
    position: relative;
    container-type: inline-size;
    width: 100%;
    max-width: 652px;
    margin-top: 20px;
    padding-top: 23px;
    box-sizing: border-box;
    border: 1px solid var(--color-grey-25, rgba(0, 0, 0, 0.08));
    border-radius: 23px;
    background: var(--color-grey-20, #f3f3f3);
    color: var(--color-font-primary, #222222);
    overflow: visible;
    box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.05));
  }

  .map-view-toolbar {
    position: absolute;
    z-index: var(--z-index-dropdown-1, 10);
    top: 0;
    right: 0;
    left: 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 42px;
    padding: 0 10px;
    box-sizing: border-box;
  }

  .entry-count {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .results-view-tabs {
    position: absolute;
    left: 50%;
    display: inline-flex;
    width: 170px;
    height: 37px;
    padding: 0;
    box-sizing: border-box;
    border: 0;
    border-radius: 999px;
    background: var(--color-grey-0, #ffffff);
    box-shadow: var(--shadow-sm, 0 4px 10px rgba(0, 0, 0, 0.16));
    transform: translate(-50%, -20px);
  }

  .results-view-tabs button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 999px;
    background: transparent;
    color: var(--color-font-secondary, #666666);
    flex: 1 1 0;
    min-width: 0;
    height: 100%;
    margin-right: 0;
    padding: 0;
    filter: none;
    font: inherit;
    font-size: var(--font-size-xxs, 0.75rem);
    font-weight: 650;
    line-height: 1;
    cursor: pointer;
    transition: background var(--duration-fast, 0.15s) ease, color var(--duration-fast, 0.15s) ease;
  }

  .results-view-tab-icon {
    width: 20px;
    height: 20px;
    background: currentColor;
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .results-view-tab-icon-map {
    -webkit-mask-image: url('@openmates/ui/static/icons/maps.svg');
    mask-image: url('@openmates/ui/static/icons/maps.svg');
  }

  .results-view-tab-icon-calendar {
    -webkit-mask-image: url('@openmates/ui/static/icons/calendar.svg');
    mask-image: url('@openmates/ui/static/icons/calendar.svg');
  }

  .results-view-tabs button.active,
  .results-view-tabs button:hover {
    background: linear-gradient(135deg, var(--color-primary-start, #6c63ff), var(--color-primary-end, #8a63ff));
    color: var(--color-grey-0, #ffffff);
  }

  .results-view-tabs button:focus-visible {
    outline: 2px solid var(--color-primary, #6c63ff);
    outline-offset: 2px;
  }

  .filter-menu-wrapper {
    position: static;
    margin-left: auto;
  }

  .filter-button {
    display: inline-flex;
    align-items: center;
    width: 42px;
    min-width: 42px;
    max-width: 42px;
    height: 42px;
    flex: 0 0 42px;
    justify-content: center;
    border: 0;
    border-radius: 999px;
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 0;
    margin-right: 0;
    filter: none;
    font: inherit;
    font-size: var(--font-size-xxs);
    line-height: 1;
    text-transform: capitalize;
    cursor: pointer;
    box-shadow: var(--shadow-sm, 0 4px 10px rgba(0, 0, 0, 0.16));
    transform: translateY(-10px);
  }

  .filter-icon {
    width: 22px;
    height: 22px;
    background: var(--gradient-primary);
    -webkit-mask-image: url('@openmates/ui/static/icons/filter.svg');
    mask-image: url('@openmates/ui/static/icons/filter.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .close-icon {
    width: 22px;
    height: 22px;
    background: var(--gradient-primary);
    -webkit-mask-image: url('@openmates/ui/static/icons/close.svg');
    mask-image: url('@openmates/ui/static/icons/close.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .filter-button:hover,
  .filter-button:active {
    background: var(--color-grey-0, #ffffff);
    filter: none;
    scale: 1;
  }

  .filter-menu {
    position: absolute;
    top: 23px;
    right: 0;
    display: grid;
    grid-template-columns: minmax(180px, 0.9fr) minmax(0, 1.5fr);
    grid-template-rows: auto 1fr;
    gap: 16px 24px;
    width: 100%;
    height: 535px;
    overflow: hidden;
    box-sizing: border-box;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: 23px;
    background: var(--color-grey-10, #f9f9f9);
    box-shadow: none;
    padding: 32px 18px 18px;
  }

  .filter-menu-header {
    grid-column: 1;
    grid-row: 1;
    display: grid;
    align-content: start;
    justify-items: start;
    gap: 16px;
  }

  .filter-menu-header,
  .range-label-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
  }

  .filter-summary {
    grid-column: 1;
    grid-row: 2;
    margin: 0;
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-h3, 1.25rem);
    font-weight: 700;
    line-height: 1.4;
  }

  .filter-controls {
    grid-column: 2;
    grid-row: 1 / span 2;
    display: grid;
    gap: 10px;
    min-height: 0;
    overflow-y: scroll;
    overscroll-behavior: contain;
    scrollbar-gutter: stable;
    padding: 0 4px 18px 0;
  }

  .filter-menu-header strong,
  .filter-section-title {
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-xs, 0.8125rem);
    font-weight: 650;
  }

  .range-label-row span:last-child {
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-tiny, 0.6875rem);
    white-space: nowrap;
  }

  .filter-section {
    display: grid;
    gap: 8px;
  }

  .filter-category-options,
  .option-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .filter-menu button {
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: 999px;
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 7px 10px;
    font: inherit;
    font-size: var(--font-size-xxs, 0.75rem);
    text-align: center;
    cursor: pointer;
  }

  .filter-menu button:hover {
    background: var(--color-grey-blue, #e6eaff);
    color: var(--color-font-primary, #222222);
  }

  .filter-menu button.active,
  .filter-menu button[aria-pressed='true'] {
    border-color: transparent;
    background: var(--gradient-primary);
    color: var(--color-text-on-primary, #ffffff);
  }

  .filter-menu button[aria-pressed='true'] span {
    color: inherit;
  }

  .option-chips button span {
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-tiny, 0.6875rem);
  }

  .filter-histogram {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    align-items: end;
    gap: 3px;
    height: 34px;
    padding: 4px 0;
  }

  .filter-histogram span {
    display: block;
    min-height: 4px;
    border-radius: 999px 999px 2px 2px;
    background: var(--color-grey-blue, #e6eaff);
  }

  .range-inputs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .range-inputs input[type='range'] {
    min-width: 0;
    accent-color: var(--color-primary, #6c63ff);
  }

  .range-inputs input[type='date'] {
    min-width: 0;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: var(--radius-3, 8px);
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 6px;
    font: inherit;
    font-size: var(--font-size-xxs, 0.75rem);
  }

  .map-view-body {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    height: 535px;
    overflow: hidden;
    border-radius: 23px;
    background: var(--color-grey-20, #f3f3f3);
  }

  .map-view-body.calendar-active {
    display: block;
  }

  .results-view-pane {
    min-width: 0;
    height: 278px;
    min-height: 278px;
    background: var(--color-grey-20, #f3f3f3);
  }

  .map-view-list {
    position: relative;
    min-width: 0;
    height: 257px;
    border-bottom: 1px solid var(--color-grey-20, #f3f3f3);
    background: var(--color-grey-20, #f3f3f3);
  }

  .map-view-carousel {
    display: flex;
    gap: 12px;
    height: 257px;
    min-width: 0;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 8px 14px 26px;
    box-sizing: border-box;
    scroll-padding: 14px;
    scroll-snap-type: x mandatory;
    scrollbar-width: thin;
  }

  .map-view-card {
    display: block;
    flex: 0 0 300px;
    width: 300px;
    height: 200px;
    border: 0;
    border-radius: 30px;
    background: transparent;
    color: var(--color-font-primary, #222222);
    padding: 0;
    overflow: hidden;
    text-align: left;
    cursor: pointer;
    opacity: 1;
    scroll-snap-align: start;
    transition: opacity var(--duration-fast, 0.15s) ease, border-color var(--duration-fast, 0.15s) ease;
  }

  .map-view-card.dimmed {
    opacity: 0.5;
  }

  .map-view-card.highlighted,
  .map-view-card.hovered,
  .map-view-card.selected {
    box-shadow: inset 0 0 0 3px var(--color-primary);
  }

  .map-view-card:focus-visible {
    outline: 2px solid var(--color-primary, #6c63ff);
    outline-offset: 3px;
  }

  .fallback-card {
    display: grid;
    gap: 6px;
    width: 300px;
    min-width: 300px;
    height: 200px;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: 30px;
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 16px;
    text-align: left;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16), 0 2px 6px rgba(0, 0, 0, 0.1);
    cursor: pointer;
  }

  .fallback-card strong {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-small, 0.875rem);
    line-height: 1.28;
    overflow-wrap: anywhere;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .fallback-card .entry-subtitle,
  .fallback-card em {
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

  .show-all-results {
    position: absolute;
    z-index: 1;
    right: 16px;
    bottom: 10px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin: 0;
    width: fit-content;
    border: 1px solid var(--color-grey-30, #e3e3e3);
    border-radius: 999px;
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 8px 12px;
    font: inherit;
    font-size: var(--font-size-xxs, 0.75rem);
    font-weight: 650;
    cursor: pointer;
  }

  .map-view-map {
    min-width: 0;
    min-height: 278px;
    height: 278px;
    background: var(--color-grey-20, #f3f3f3);
  }

  .results-view-calendar {
    display: grid;
    align-content: start;
    gap: 8px;
    height: 535px;
    min-height: 535px;
    max-height: 535px;
    box-sizing: border-box;
    min-width: 0;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 14px 14px 18px;
    background:
      linear-gradient(180deg, color-mix(in srgb, var(--color-primary, #6c63ff) 8%, transparent), transparent 160px),
      var(--color-grey-20, #f3f3f3);
  }

  .calendar-week-toolbar {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr) 28px;
    align-items: center;
    gap: 8px;
    justify-self: start;
    inline-size: min(100%, calc(100cqw - 28px));
    min-height: 36px;
    position: sticky;
    left: 0;
    z-index: 1;
  }

  .calendar-week-toolbar strong {
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-xxs, 0.75rem);
    font-weight: 650;
    min-width: max-content;
    overflow: hidden;
    text-align: center;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .calendar-week-toolbar button {
    display: inline-grid;
    width: 28px;
    min-width: 28px;
    max-width: 28px;
    height: 28px;
    place-items: center;
    border: 0;
    border-radius: var(--radius-4, 10px);
    background: transparent;
    color: var(--color-font-primary, #222222);
    padding: 0;
    font: inherit;
    font-size: var(--font-size-large, 1.125rem);
    line-height: 1;
    cursor: pointer;
  }

  .calendar-week-toolbar button:first-child {
    justify-self: end;
  }

  .calendar-week-toolbar button:last-child {
    justify-self: start;
  }

  .calendar-week-toolbar button:hover {
    background: var(--color-grey-10, #f9f9f9);
  }

  .calendar-week {
    --calendar-hour-height: 46px;
    display: grid;
    grid-template-columns: 44px repeat(7, minmax(0, 1fr));
    gap: 0;
    justify-self: start;
    min-width: 620px;
    overflow: hidden;
    border-radius: var(--radius-6, 14px);
    background: var(--color-grey-0, #ffffff);
    box-shadow: var(--shadow-xs, 0 2px 4px rgba(0, 0, 0, 0.1));
  }

  .calendar-time-column,
  .calendar-day {
    display: grid;
    grid-template-rows: 42px calc(var(--calendar-hour-height) * 8);
    min-height: 0;
  }

  .calendar-time-column {
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-tiny, 0.6875rem);
    font-weight: 650;
  }

  .calendar-time-column-spacer {
    border-right: 1px solid var(--color-grey-20, #f3f3f3);
    border-bottom: 1px solid var(--color-grey-20, #f3f3f3);
  }

  .calendar-time-slots {
    display: grid;
    grid-template-rows: repeat(8, var(--calendar-hour-height));
    border-right: 1px solid var(--color-grey-20, #f3f3f3);
    background: var(--color-grey-0, #ffffff);
  }

  .calendar-time-slots span {
    align-self: start;
    justify-self: end;
    padding: 0 6px 0 0;
    transform: translateY(-0.55em);
  }

  .calendar-day {
    gap: 0;
    border-left: 1px solid var(--color-grey-20, #f3f3f3);
    background: var(--color-grey-0, #ffffff);
    padding: 0;
  }

  .calendar-day.today {
    background: var(--color-grey-10, #f9f9f9);
  }

  .calendar-day-header {
    display: grid;
    align-items: center;
    align-content: center;
    gap: 1px;
    min-height: 42px;
    border-bottom: 1px solid var(--color-grey-20, #f3f3f3);
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-xxs, 0.75rem);
    font-weight: 650;
    text-align: center;
  }

  .calendar-day-header strong {
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-xxs, 0.75rem);
  }

  .calendar-items {
    position: relative;
    min-height: calc(var(--calendar-hour-height) * 8);
    overflow: hidden;
    background:
      repeating-linear-gradient(
        to bottom,
        transparent 0,
        transparent calc(var(--calendar-hour-height) - 1px),
        var(--color-grey-20, #f3f3f3) calc(var(--calendar-hour-height) - 1px),
        var(--color-grey-20, #f3f3f3) var(--calendar-hour-height)
      );
  }

  .calendar-item {
    position: absolute;
    top: calc(var(--calendar-item-top-hours) * var(--calendar-hour-height));
    right: 6px;
    left: 6px;
    display: block;
    height: calc(var(--calendar-item-height-hours) * var(--calendar-hour-height));
    overflow: hidden;
    border: 0;
    border-left: 3px solid var(--color-error, #e74c3c);
    border-radius: var(--radius-3, 8px);
    background: color-mix(in srgb, var(--color-error, #e74c3c) 16%, var(--color-grey-0, #ffffff));
    color: var(--color-font-primary, #222222);
    padding: 5px 6px;
    text-align: left;
    box-shadow: none;
    cursor: pointer;
    transition: border-color var(--duration-fast, 0.15s) ease, transform var(--duration-fast, 0.15s) ease;
  }

  .calendar-item.highlighted,
  .calendar-item.hovered {
    border-color: var(--color-primary, #6c63ff);
  }

  .calendar-item:hover {
    transform: translateY(-1px);
  }

  .calendar-time {
    display: block;
    overflow: hidden;
    border-radius: 0;
    background: transparent;
    color: var(--color-font-primary, #222222);
    padding: 0;
    font-size: var(--font-size-tiny, 0.6875rem);
    font-weight: 700;
    line-height: 1;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .calendar-copy {
    display: block;
    min-width: 0;
  }

  .calendar-copy strong {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-tiny, 0.6875rem);
    line-height: 1.1;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .calendar-copy > span:last-child {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-secondary, #666666);
    font-size: 0.625rem;
    line-height: 1.1;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
  }

  .empty-state,
  .empty-map,
  .map-hydration-placeholder {
    display: grid;
    min-height: 180px;
    place-items: center;
    padding: 18px;
    color: var(--color-grey-60, #9aa4b5);
    text-align: center;
  }

  :global(.embeds-map-view-marker-active .marker-icon) {
    filter: drop-shadow(0 0 5px var(--color-primary));
  }

  :global(.embeds-map-view-marker-endpoint-start .marker-icon) {
    color: var(--color-app-travel-start, #059db3);
  }

  :global(.embeds-map-view-marker-endpoint-end .marker-icon) {
    color: var(--color-app-travel-end, #13daf5);
  }

  :global(.embeds-map-view-marker-stop .marker-icon),
  :global(.embeds-map-view-marker-selected .marker-icon) {
    color: var(--color-error, #e74c3c);
  }

  :global(.embeds-map-view-marker-location .marker-icon) {
    color: var(--color-grey-50, #a6a6a6);
  }

  :global(.embeds-map-view-marker-location.embeds-map-view-marker-selected .marker-icon) {
    color: var(--color-error, #e74c3c);
  }

  @container (max-width: 720px) {
    .results-view-tabs {
      position: absolute;
      width: min(170px, calc(100% - 70px));
      transform: translate(-50%, -20px);
    }

    .results-view-tabs button {
      flex: 1 1 0;
      justify-content: center;
    }

    .filter-menu-wrapper {
      position: static;
    }

    .filter-menu {
      position: absolute;
      top: 23px;
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto auto minmax(0, 1fr);
      width: 100%;
      height: 535px;
      max-height: none;
      margin: 0;
      border-radius: 23px;
      box-shadow: none;
      padding: 54px 14px 14px;
      overscroll-behavior: contain;
    }

    .filter-menu-header {
      grid-column: 1;
      grid-row: 2;
      display: flex;
    }

    .filter-summary {
      grid-column: 1;
      grid-row: 1;
      font-size: var(--font-size-small, 0.875rem);
    }

    .filter-controls {
      grid-column: 1;
      grid-row: 3;
    }

    .filter-menu-header,
    .range-label-row {
      align-items: flex-start;
    }

    .filter-category-options,
    .option-chips {
      flex-wrap: nowrap;
      overflow-x: auto;
      padding-bottom: 2px;
      scrollbar-width: none;
    }

    .filter-category-options::-webkit-scrollbar,
    .option-chips::-webkit-scrollbar {
      display: none;
    }

    .filter-menu button {
      flex: 0 0 auto;
      white-space: nowrap;
    }

    .filter-histogram {
      height: 22px;
    }

    .range-inputs {
      grid-template-columns: 1fr;
      gap: 4px;
    }

    .map-view-list {
      height: 257px;
      border-right: 0;
      border-bottom: 1px solid var(--color-grey-20, #f3f3f3);
    }

    .map-view-carousel {
      gap: 12px;
      height: 257px;
      padding: 8px 14px 26px;
      scroll-padding: 14px;
    }

    .map-view-card {
      box-sizing: border-box;
      flex: 0 0 auto;
      min-width: 0;
      scroll-snap-align: start;
      scroll-snap-stop: always;
    }

    .fallback-card strong {
      -webkit-line-clamp: 3;
      line-clamp: 3;
    }

    .map-view-map {
      min-height: 278px;
      height: 278px;
    }

    .results-view-pane,
    .results-view-calendar {
      min-height: 535px;
    }

    .results-view-calendar {
      height: 535px;
      max-height: 535px;
    }

    .calendar-week {
      grid-template-columns: 42px repeat(7, minmax(88px, 1fr));
      min-width: 658px;
    }

    .calendar-copy strong {
      white-space: normal;
    }
  }
</style>
