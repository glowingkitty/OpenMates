<!--
  frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte

  Virtual in-chat results view over existing location/schedule-capable embeds.
  It resolves refs from local embed data and never calls provider/app-skill
  enrichment endpoints. Unresolved or ineligible refs remain invisible.
  Spec: docs/specs/embeds-map-view/spec.yml
-->

<script lang="ts">
  import ResultCalendarWeek from "@repo/public-site/components/results/ResultCalendarWeek.svelte";
  import type { CalendarWeekEntry } from "@repo/public-site/components/results/calendarWeek";
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  const sourceChatContext = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  const sourceChatId = sourceChatContext?.exampleChatId ?? sourceChatContext?.lookupChatId ?? sourceChatContext?.chatId ?? null;
  import { onDestroy, onMount, getContext} from 'svelte';
  import Toggle from '../Toggle.svelte';
  import ProviderIcon from '../settings/ProviderIcon.svelte';
  import ResultsRangeFilter from './ResultsRangeFilter.svelte';
  import ResultsDateRangeFilter from './ResultsDateRangeFilter.svelte';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import { text } from '../../i18n/translations';
  import { homeMapGeometry, homeMapLabel, type HomeMapGeometry } from './home/homeListingData';
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  import { EMBED_METADATA, normalizeEmbedType } from '../../data/embedRegistry.generated';
  import { userProfile } from '../../stores/userProfile';
  import type { Component } from 'svelte';
  import { extractResultRoute, buildResultRoutePaths, buildResultMapMarkers } from './resultMapRoutes';
  import { deduplicateResultViewEntries } from './resultViewEntries';
  import EmbedLeafletMap, { type MapMarker, type MapPathPoint, type MapRoutePath } from './EmbedLeafletMap.svelte';
  import { decodeToonContent, resolveEmbed, type EmbedData } from '../../services/embedResolver';
  import { resolveResultsViewRefToId } from '../../services/resultsViewRefResolver';
  import { embedAvailabilityVersion, embedRefIndexVersion, embedStore } from '../../services/embedStore';
  import { chatSyncService } from '../../services/chatSyncService';
  import { dispatchEmbedFullscreen } from '../../services/embedFullscreenController';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
  import { incrementStreamingRenderMetric } from '../../message_parsing/streamingRenderMetrics';
  import type { EmbedNodeAttributes } from '../../message_parsing/types';

  let resolutionMarker: HTMLSpanElement;
  let diagnosticHidden = $state(false);
  // Collapse the node view and legacy code-fence shell, not just its contents.
  onMount(() => {
    const target = resolutionMarker?.parentElement;
    const pre = target?.closest('pre');
    target?.classList.add('results-view-mount');
    pre?.classList.add('results-view-protocol-host');
    return () => {
      target?.classList.remove('results-view-mount');
      pre?.classList.remove('results-view-protocol-host');
    };
  });

  const DeleteFilterIcon = getLucideIcon('trash-2');
  const ProviderFilterIcon = getLucideIcon('messages-square');
  const DateFilterIcon = getLucideIcon('calendar-days');
  const TypeFilterIcon = getLucideIcon('layers');
  function rangeFilterIcon(key: string) {
    return getLucideIcon(key === 'price' ? 'euro' : key === 'rating' ? 'star' : 'clock-3');
  }

  const MAX_VISIBLE_ENTRIES = 40;
  const MAX_TRAVEL_LEGS = 8;
  const MAX_TRAVEL_SEGMENTS_PER_LEG = 32;
  const MAP_HYDRATION_ROOT_MARGIN = '320px';

  interface Props {
    id: string;
    title: string;
    embedRefs?: string[];
    sourceRefs?: string[];
    highlightRefs?: string[];
    interactionMode?: 'open' | 'select';
    /** Parent fullscreen owns the scroll; render previews as a vertical grid. */
    fullscreen?: boolean;
    initialVisualTab?: 'map' | 'calendar';
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
    homeGeometry?: HomeMapGeometry;
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

  let {
    id,
    title,
    embedRefs = [],
    sourceRefs = [],
    highlightRefs = [],
    interactionMode = 'open',
    fullscreen = false,
    initialVisualTab = 'map',
  }: Props = $props();

  let entries = $state<MapViewEntry[]>([]);
  let isLoading = $state(true);
  let hoveredRef = $state<string | null>(null);
  let activeCategory = $state<string>('all');
  let activeVisualTab = $state<VisualTabId>('map');
  let initialVisualTabApplied = $state(false);
  let rangeFilters = $state<Record<string, { min: number; max: number }>>({});
  let optionFilters = $state<Record<string, string[]>>({});
  let filtersOpen = $state(false);
  let shouldHydrateMap = $state(false);
  let mapShellElement = $state<HTMLDivElement | null>(null);
  let mapViewportEntryRefs = $state<string[] | null>(null);
  let mapSelectionRefs = $state<string[]>([]);
  let mapSelectionKey = $state<string | null>(null);
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
  const resolvedSourceIds = new Set<string>();
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;
  const sourceChildrenCache = new Map<string, { signature: string; refs: string[] }>();

  export function updateDescriptor(attrs: EmbedNodeAttributes): void {
    resolvedSourceIds.clear();
    id = attrs.id;
    title = attrs.title || 'Results view';
    embedRefs = [...(attrs.mapEmbedRefs || [])];
    sourceRefs = [...(attrs.mapSourceRefs || [])];
    highlightRefs = [...(attrs.mapHighlightRefs || [])];
    void loadEntries();
  }

  const highlightSet = $derived(new Set(highlightRefs));
  // Unresolved references remain internal so sync can recover them. Hosting
  // domains have a registered preview but no map/calendar coordinates.
  const eligibleEntries = $derived(entries.filter((entry) => entry.status === 'ready' && (
    (entry.lat != null && entry.lon != null) || (entry.route?.length ?? 0) > 0 ||
    calendarEntryFromMapEntry(entry) != null || (normalizeEmbedType(entry.embedType ?? '') === 'hosting-domain' && entry.preview != null)
  )));
  const categories = $derived.by(() => {
    const values = Array.from(new Set(eligibleEntries.map((entry) => entry.category)));
    return ['all', ...values];
  });
  const categoryFilteredEntries = $derived.by(() => {
    if (activeCategory === 'all') return eligibleEntries;
    return eligibleEntries.filter((entry) => entry.category === activeCategory);
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
    const mappable = visualTabs.length === 0
      ? visibleEntries.filter((entry) => normalizeEmbedType(entry.embedType ?? '') === 'hosting-domain' && entry.preview != null)
      : visibleEntries.filter((entry) => (entry.lat != null && entry.lon != null) || (entry.route?.length ?? 0) > 0);
    if (mapSelectionRefs.length > 0) {
      const selectionSet = new Set(mapSelectionRefs);
      return mappable.filter((entry) => selectionSet.has(entry.ref));
    }
    if (mapViewportEntryRefs && mapViewportEntryRefs.length > 0) {
      const viewportSet = new Set(mapViewportEntryRefs);
      const viewportEntries = mappable.filter((entry) => viewportSet.has(entry.ref));
      if (viewportEntries.length > 0 && viewportEntries.length < visibleEntries.length) return viewportEntries;
    }
    return mappable;
  });
  const isCarouselScoped = $derived(carouselEntries.length < visibleEntries.length || mapSelectionRefs.length > 0);
  const activeGeometryRefs = $derived(mapSelectionRefs.length > 0
    ? new Set(mapSelectionRefs)
    : new Set([hoveredRef ?? selectedRef].filter((ref): ref is string => ref != null)));
  const mapMarkers = $derived<MapMarker[]>(buildResultMapMarkers(visibleEntries.map(entry => ({
    ref: entry.ref, title: entry.title, color: mapEntryColor(entry), lat: entry.lat, lon: entry.lon,
    route: entry.route, homeGeometry: entry.homeGeometry,
    homeLabel: entry.homeGeometry ? `${entry.title} · ${homeMapLabel(entry.homeGeometry, $text)}` : undefined,
  })), activeGeometryRefs, mapSelectionKey));
  const endpointMarkerCount = $derived(mapMarkers.filter((marker) => marker.iconClass?.includes('marker-endpoint')).length);
  const stopMarkerCount = $derived(mapMarkers.filter((marker) => marker.iconClass?.includes('marker-stop')).length);
  const routePaths = $derived<MapRoutePath[]>(buildResultRoutePaths(visibleEntries, activeGeometryRefs, 'embeds-map-view-route-path'));
  const calendarEntries = $derived<CalendarWeekEntry[]>(visibleEntries
    .map(calendarEntryFromMapEntry)
    .filter((entry): entry is CalendarWeekEntry => entry != null)
    .sort((a, b) => a.dateOrdinal - b.dateOrdinal || a.startMinutes - b.startMinutes || a.title.localeCompare(b.title)));
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

  function mapEntryColor(entry: MapViewEntry): string {
    const appId = firstString(
      entry.preview?.props.appId,
      EMBED_METADATA[normalizeEmbedType(entry.embedType ?? '')]?.appId,
      entry.decodedContent?.app_id,
      entry.embedData?.app_id,
      'maps',
    );
    const safeAppId = /^[a-z][a-z0-9-]*$/.test(appId) ? appId : 'maps';
    return `var(--color-app-${safeAppId}-start, var(--color-app-maps-start))`;
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
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?=$|[T\s])/);
    if (!match) return undefined;
    const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
    const timestamp = Date.UTC(year, month - 1, day);
    const date = new Date(timestamp);
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return undefined;
    return timestamp / 86400000;
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
      content?.datetime,
      content?.start_date,
      content?.scheduled_departure,
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
      + optionControls.reduce((count, control) => count + (optionFilters[control.key] !== undefined && optionFilters[control.key].length !== control.options.length ? 1 : 0), 0);
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
      const selectedValues = optionFilters[control.key];
      if (selectedValues === undefined) continue;
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
    const current = optionFilters[key] ?? optionFilterControls.find((control) => control.key === key)?.options.map((option) => option.value) ?? [];
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

  function calendarEntryFromMapEntry(entry: MapViewEntry): CalendarWeekEntry | null {
    if (entry.status !== 'ready') return null;
    const dateOrdinal = numberFacet(entry, 'dateOrdinal');
    const departureMinutes = numberFacet(entry, 'departureMinutes');
    if (dateOrdinal == null) return null;
    const startMinutes = departureMinutes ?? 0;
    const rawEndMinutes = numberFacet(entry, 'arrivalMinutes');
    const endDateOrdinal = dateOrdinalFromValue(firstString(entry.decodedContent?.arrival,
      entry.decodedContent?.scheduled_arrival, entry.decodedContent?.end_time, entry.decodedContent?.date_end));
    const endDayOffset = endDateOrdinal != null ? Math.max(0, endDateOrdinal - dateOrdinal) * 1440 : 0;
    const durationMinutes = numberFacet(entry, 'durationMinutes');
    const endMinutes = rawEndMinutes != null && (rawEndMinutes !== startMinutes || endDayOffset > 0)
      ? rawEndMinutes + (endDayOffset || (rawEndMinutes < startMinutes ? 1440 : 0))
      : durationMinutes != null && durationMinutes > 0 ? startMinutes + durationMinutes : undefined;
    return {
      ref: entry.ref, title: entry.title, category: entry.category, highlighted: entry.highlighted,
      location: calendarLocation(entry), dateOrdinal, startMinutes, endMinutes,
      dateOnly: departureMinutes == null,
      endDateOrdinal: departureMinutes == null && typeof entry.decodedContent?.date_end === 'string'
        && /^\d{4}-\d{2}-\d{2}$/.test(entry.decodedContent.date_end) ? endDateOrdinal ?? undefined : undefined,
    };
  }


  // Include every week occupied by an event, including its overnight continuation.
  // Event end times are exclusive, so an event ending at Monday 00:00 stays in Sunday.



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




  // Overlaps share the day's width; they never move away from their real time.


  function calendarLocation(entry: MapViewEntry): string {
    const content = entry.decodedContent;
    const venue = getNestedRecord(content, 'venue');
    const location = getNestedRecord(content, 'location');
    return firstString(content?.venue_name, venue?.name, location?.name, content?.location_name,
      content?.formattedAddress, content?.formatted_address, content?.address, venue?.address, location?.address);
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
    return resolveResultsViewRefToId(normalizeMapViewRef(ref), embedStore);
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
    return preview;
  }

  async function resolveEntry(ref: string): Promise<MapViewEntry> {
    const embedId = await resolveRefToId(ref);
    if (!embedId) {
      return { ref, embedId: null, embedType: null, title: ref, subtitle: 'Waiting for embed data', category: 'loading', status: 'loading', highlighted: highlightSet.has(ref), facets: emptyFacets() };
    }

    const embedData = await resolveEmbed(embedId, { chatId: sourceChatId });
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
    const isHome = normalizeEmbedType(embedData.type) === 'home-listing' || decodedContent?.app_id === 'home';
    const homeGeometry = isHome && decodedContent ? homeMapGeometry(decodedContent) : undefined;
    const point: Partial<CoordinatePair> = isHome ? homeGeometry ?? {} : extractPoint(decodedContent);
    const route = isHome ? [] : extractResultRoute(decodedContent);
    const entry: MapViewEntry = {
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
      homeGeometry,
      embedData,
      decodedContent,
      preview: null,
      facets: extractFacets(category, decodedContent),
    } satisfies MapViewEntry;
    if ((entry.lat != null && entry.lon != null) || (entry.route?.length ?? 0) > 0 || calendarEntryFromMapEntry(entry) != null || normalizeEmbedType(embedData.type) === 'hosting-domain') {
      entry.preview = await resolveEntryPreview(entry);
    }
    entryCache.set(ref, { signature, entry });
    return entry;
  }

  async function resolveSourceChildren(sourceRef: string): Promise<string[]> {
    const sourceId = await resolveRefToId(sourceRef);
    if (!sourceId) return [];
    resolvedSourceIds.add(sourceId);
    const sourceEmbed = await resolveEmbed(sourceId, { chatId: sourceChatId });
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

    let resolvedEntries: MapViewEntry[] = [];
    // Cap unique results, not raw refs: aliases and overlapping searches must
    // neither repeat cards nor consume slots belonging to later unique events.
    for (let offset = 0; offset < refs.length; offset += MAX_VISIBLE_ENTRIES) {
      const batch = await Promise.all(refs.slice(offset, offset + MAX_VISIBLE_ENTRIES).map(resolveEntry));
      if (generation !== loadGeneration) return;
      resolvedEntries = deduplicateResultViewEntries([...resolvedEntries, ...batch]);
      if (resolvedEntries.length >= MAX_VISIBLE_ENTRIES) break;
    }
    entries = resolvedEntries.slice(0, MAX_VISIBLE_ENTRIES);
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
    if (entry.homeGeometry?.radiusM) {
      const {lat, lon, radiusM} = entry.homeGeometry;
      const closestLat = Math.max(bounds.south, Math.min(bounds.north, lat));
      // Normalize longitudes around the area center, including dateline viewports.
      const delta = (value: number) => ((value - lon + 540) % 360) - 180;
      const west = delta(bounds.west), east = delta(bounds.east);
      const insideLon = bounds.west <= bounds.east ? lon >= bounds.west && lon <= bounds.east : lon >= bounds.west || lon <= bounds.east;
      const lonDelta = insideLon ? 0 : Math.min(Math.abs(west), Math.abs(east));
      const radians = Math.PI / 180;
      const a = Math.sin((closestLat - lat) * radians / 2) ** 2
        + Math.cos(lat * radians) * Math.cos(closestLat * radians) * Math.sin(lonDelta * radians / 2) ** 2;
      return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a))) <= radiusM;
    }
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

  function handleReferencedEmbedUpdate(event: Event): void {
    const embedId = (event as CustomEvent<{ embed_id?: string }>).detail?.embed_id?.replace(/^embed:/, '');
    if (!embedId || !(resolvedSourceIds.has(embedId) || entries.some((entry) => entry.embedId === embedId || entry.ref === embedId))) return;
    if (refreshTimer !== null) return;
    refreshTimer = setTimeout(() => { refreshTimer = null; void loadEntries(); }, 0);
  }

  onMount(() => {
    chatSyncService.addEventListener('embedUpdated', handleReferencedEmbedUpdate);
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
    loadGeneration += 1;
    chatSyncService.removeEventListener('embedUpdated', handleReferencedEmbedUpdate);
    if (refreshTimer !== null) clearTimeout(refreshTimer);
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
    if (!initialVisualTabApplied && !isLoading && eligibleEntries.length > 0) {
      if (visualTabs.some(tab => tab.id === initialVisualTab)) activeVisualTab = initialVisualTab;
      initialVisualTabApplied = true;
    }
    if (visualTabs.length > 0 && !visualTabs.some((tab) => tab.id === activeVisualTab)) {
      activeVisualTab = visualTabs[0].id;
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

<span bind:this={resolutionMarker} hidden data-result-view-visible={eligibleEntries.length > 0 || (!isLoading && $userProfile.is_admin === true && !diagnosticHidden) ? "true" : "false"} data-testid="embeds-map-view-resolution" data-loading={isLoading ? 'true' : 'false'}></span>
{#if eligibleEntries.length > 0}
<section class="embeds-results-view embeds-map-view" class:fullscreen class:list-only={visualTabs.length === 0} data-testid="embeds-map-view" data-results-view-id={id} data-map-view-id={id} data-loading={isLoading ? 'true' : 'false'} aria-label={title}>
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
            onclick={() => { initialVisualTabApplied = true; activeVisualTab = tab.id; }}
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
            <div class="filter-menu-summary">
              <p class="filter-summary" data-testid="embeds-map-view-filter-summary">
                {visibleEntries.length} of {eligibleEntries.length}<br class="filter-summary-break" /> results remain
              </p>
              <button type="button" class="clear-results-filters" data-testid="embeds-map-view-clear-filters" onclick={clearFilters}>
                <DeleteFilterIcon size={17} /><span>Clear all filters</span>
              </button>
            </div>

            <div class="filter-controls" data-testid="embeds-map-view-filter-controls">
              {#if categories.length > 2}
                <div class="filter-section">
                  <span class="filter-section-title"><TypeFilterIcon size={23} />Type</span>
                  <div class="filter-category-options">
                    {#each categories as category}
                      <button
                        type="button"
                        role="switch"
                        aria-checked={category === activeCategory}
                        onclick={() => {
                          activeCategory = category;
                          clearMapViewportScope();
                        }}
                      >
                        <span>{category === 'all' ? 'All results' : formatOptionLabel(category)}</span>
                        <Toggle checked={category === activeCategory} presentationOnly={true} />
                      </button>
                    {/each}
                  </div>
                </div>
              {/if}

              {#each rangeFilterControls.filter((control) => control.type !== 'date') as control}
                {@const Icon = rangeFilterIcon(control.key)}
                {@const rangeValue = getRangeValue(control)}
                <div class="filter-section" data-testid={`embeds-map-view-filter-${control.key}`}>
                  <span class="filter-section-title"><Icon size={23} />{control.label}</span>
                  <ResultsRangeFilter
                    min={control.min} max={control.max}
                    lower={rangeValue.min} upper={rangeValue.max}
                    values={control.values} step={control.type === 'time' ? 5 : 1}
                    label={control.label} testId={`embeds-map-view-filter-${control.key}`}
                    formatValue={(value) => formatRangeValue(control, value)}
                    onChange={(side, value) => updateRangeFilter(control.key, side, value)}
                  />
                </div>
              {/each}

              {#each optionFilterControls as control}
                <div class="filter-section" data-testid={`embeds-map-view-filter-${control.key}`}>
                  <span class="filter-section-title"><ProviderFilterIcon size={23} />{control.label}</span>
                  <div class="option-chips">
                    {#each control.options as option}
                      <button
                        type="button"
                        data-testid={`embeds-map-view-option-${testIdPart(control.label)}-${testIdPart(option.value)}`}
                        role="switch"
                        aria-checked={optionFilters[control.key] === undefined || optionFilters[control.key].includes(option.value)}
                        onclick={() => toggleOptionFilter(control.key, option.value)}
                      >
                        {#if control.key === 'providers' || control.key === 'carriers'}
                          <ProviderIcon name={option.label} size="36px" />
                        {/if}
                        <span class="filter-option-label">{option.label}</span>
                        <Toggle checked={optionFilters[control.key] === undefined || optionFilters[control.key].includes(option.value)} presentationOnly={true} />
                      </button>
                    {/each}
                  </div>
                </div>
              {/each}
              {#each rangeFilterControls.filter((control) => control.type === 'date') as control}
                {@const rangeValue = getRangeValue(control)}
                <div class="filter-section" data-testid={`embeds-map-view-filter-${control.key}`}>
                  <span class="filter-section-title"><DateFilterIcon size={23} />{control.label}</span>
                  <ResultsDateRangeFilter
                    min={control.min} max={control.max}
                    lower={rangeValue.min} upper={rangeValue.max}
                    label={control.label} testId={`embeds-map-view-filter-${control.key}`}
                    onChange={(side, value) => updateRangeFilter(control.key, side, value)}
                  />
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    {/if}
  </header>

  {#if visualTabs.length === 0}
    <div class="map-view-list" data-testid="embeds-map-view-list">
      <div class="map-view-carousel" data-testid="embeds-map-view-carousel" data-embed-result-context="results" aria-label="Result previews">
        {#each carouselEntries as entry}
          <div class="map-view-card" data-testid="embeds-map-view-card" data-entry-status={entry.status} data-entry-category={entry.category} role="group" aria-label={entry.title}>
            {#if entry.preview}
              {@const Component = getRenderableComponent(entry.preview.component)}
              <Component {...entry.preview.props} />
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {:else}
  <div class="map-view-body" class:calendar-active={selectedVisualTab === 'calendar'} aria-hidden={filtersOpen}>
    {#if selectedVisualTab === 'map'}
      <div class="map-view-list" data-testid="embeds-map-view-list">
      <div class="map-view-carousel" data-testid="embeds-map-view-carousel" data-embed-result-context="results" aria-label="Result previews">
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
                {@const metadata = EMBED_METADATA[normalizeEmbedType(entry.embedType ?? '')]}
                <UnifiedEmbedPreview
                  id={entry.embedId ?? entry.ref}
                  presentationOnly={true}
                  appId={metadata?.appId ?? String(entry.decodedContent?.app_id ?? '')}
                  skillId={metadata?.skillId ?? ''}
                  skillIconName={metadata?.icon ?? 'search'}
                  skillName={entry.title}
                  status="finished"
                  onFullscreen={() => openEntry(entry)}
                >
                  {#snippet details()}
                    <strong>{entry.title}</strong>
                    <p>{entry.subtitle}</p>
                  {/snippet}
                </UnifiedEmbedPreview>
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
        <div id="embeds-results-view-panel-calendar" role="tabpanel" aria-label="Calendar results">
          <ResultCalendarWeek entries={calendarEntries} {selectedRef} {hoveredRef}
            onOpen={(ref) => { const entry = visibleEntries.find(item => item.ref === ref); if (entry) void openEntry(entry); }}
            onHover={(ref) => { if (ref) hoveredRef = ref; else if (hoveredRef) handleEntryPointerLeave(hoveredRef); }} />
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
  {/if}
</section>
{:else if !isLoading && $userProfile.is_admin === true && !diagnosticHidden}
  <div class="results-view-admin-error" role="alert" data-testid="results-view-admin-error">
    <strong>Map/calendar view could not be rendered.</strong>
    {#if embedRefs.length === 0 && sourceRefs.length === 0}
      The assistant provided no usable embed references.
    {:else}
      None of the referenced embeds could be loaded with valid coordinates or a valid date.
    {/if}
    <span>This diagnostic is visible only to server admins.</span>
    <button type="button" data-testid="results-view-admin-hide" onclick={() => { diagnosticHidden = true; }}>Hide</button>
  </div>
{/if}

<style>
  .embeds-map-view.fullscreen { max-width: 1100px; margin: 0 auto; padding-top: 0; border: 0; box-shadow: none; }
  .fullscreen .map-view-body:not(.calendar-active) { display: flex; flex-direction: column; height: auto; overflow: visible; }
  .fullscreen .results-view-pane { order: -1; }
  .fullscreen .map-view-list { height: auto; }
  .fullscreen .map-view-carousel { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); height: auto; overflow: clip; gap: 20px; padding: 20px 14px; scroll-snap-type: none; }
  .fullscreen .map-view-card { width: 100%; min-width: 0; }
  .fullscreen .show-all-results { position: relative; margin: 12px 16px; }
  .fullscreen .map-view-toolbar { position: sticky; top: 0; z-index: 20; background: var(--color-grey-20); padding-right: 64px; }
  .fullscreen .results-view-tabs { transform: translate(-50%, 0); }

  :global(.results-view-mount:not(:has([data-result-view-visible="true"]))) { display: none !important; }
  :global(pre.results-view-protocol-host:not(:has([data-result-view-visible="true"]))) { display: none !important; }
  :global(pre.results-view-protocol-host) { background: transparent !important; border: 0 !important; padding: 0 !important; font-size: 0 !important; white-space: normal !important; }
  :global(pre.results-view-protocol-host > code) { font-size: 0 !important; background: transparent !important; }
  :global(pre.results-view-protocol-host .embeds-results-view) { font-size: var(--font-size-small, .875rem); }
  .results-view-admin-error { padding: 12px 16px; border: 1px solid var(--color-error, #d45454); border-radius: 8px; color: var(--color-font-primary); background: var(--color-grey-20); font: 400 .875rem/1.5 sans-serif; }
  .results-view-admin-error button { margin-top: 8px; padding: 5px 12px; border: 1px solid var(--color-grey-50); border-radius: 6px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
  .results-view-admin-error strong, .results-view-admin-error span { display: block; }


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
    color: var(--color-font-button, #ffffff);
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
    grid-template-columns: minmax(150px, 1fr) minmax(0, 1.2fr);
    gap: 24px;
    width: 100%;
    height: 535px;
    overflow: hidden;
    box-sizing: border-box;
    border: 0;
    border-radius: 23px;
    background: var(--color-grey-10);
    padding: 30px 18px 18px;
  }
  .filter-menu-summary {
    align-self: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    min-width: 0;
    text-align: center;
  }
  .filter-summary {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-h3-mobile);
    font-weight: 650;
    line-height: 1.35;
  }
  .filter-menu .clear-results-filters {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    border: 0;
    padding: 0;
    background: transparent;
    box-shadow: none;
    color: var(--color-primary-start);
    font: inherit;
    font-size: var(--font-size-xs);
    cursor: pointer;
  }
  .filter-controls {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 25px;
    overflow-y: auto;
    overscroll-behavior-y: contain;
    scrollbar-width: thin;
    padding: 0 4px 20px 0;
  }
  .filter-section {
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    min-width: 0;
    gap: 12px;
  }
  .filter-section-title {
    display: flex;
    align-items: center;
    gap: 20px;
    border-bottom: 3px solid var(--color-primary-start);
    padding: 0 8px 7px;
    color: var(--color-font-primary);
    font-size: var(--font-size-p);
    font-weight: 650;
  }
  .filter-section-title :global(svg) { color: var(--color-primary-start); flex-shrink: 0; }
  .filter-category-options, .option-chips {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .filter-menu .option-chips button,
  .filter-menu .filter-category-options button {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    min-height: 42px;
    border: 0;
    border-radius: 0;
    padding: 0;
    background: transparent;
    color: var(--color-font-primary);
    box-shadow: none;
    font: inherit;
    font-size: var(--font-size-small);
    font-weight: 550;
    text-align: left;
    cursor: pointer;
  }
  .filter-option-label, .filter-category-options button > span:first-child { flex: 1; min-width: 0; }
  .filter-menu button:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 3px; }
  @container (max-width: 520px) {
    .filter-menu {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto minmax(0, 1fr);
      gap: 20px;
      padding: 25px 16px 16px;
    }
    .filter-menu-summary { gap: 7px; }
    .filter-summary { font-size: var(--font-size-small); }
    .filter-summary-break { display: none; }
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

  .embeds-map-view.list-only .map-view-list,
  .embeds-map-view.list-only .map-view-carousel {
    height: auto;
  }

  .embeds-map-view.list-only .map-view-list {
    border-bottom: 0;
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

  :global(.embeds-map-view-marker-active .embed-map-pin),
  :global(.embeds-map-view-marker-selected .embed-map-pin) {
    filter: drop-shadow(0 0 3px var(--color-primary-start));
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


    .map-view-map {
      min-height: 278px;
      height: 278px;
    }

    .results-view-pane {
      min-height: 535px;
    }



  }
</style>
