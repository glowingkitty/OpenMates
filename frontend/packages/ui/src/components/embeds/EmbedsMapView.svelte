<!--
  frontend/packages/ui/src/components/embeds/EmbedsMapView.svelte

  Virtual in-chat results view over existing location/schedule-capable embeds.
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
  const MAP_HYDRATION_ROOT_MARGIN = '320px';
  const HISTOGRAM_BUCKETS = 12;

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
    facets: EntryFacets;
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

  interface CalendarDayGroup {
    dateOrdinal: number;
    entries: CalendarEntry[];
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
  let activeVisualTab = $state<VisualTabId>('map');
  let rangeFilters = $state<Record<string, { min: number; max: number }>>({});
  let optionFilters = $state<Record<string, string[]>>({});
  let filtersOpen = $state(false);
  let shouldHydrateMap = $state(false);
  let mapShellElement = $state<HTMLDivElement | null>(null);
  let unsubscribeRefIndex: (() => void) | null = null;
  let mapHydrationObserver: IntersectionObserver | null = null;
  let mapHydrationTimer: ReturnType<typeof setTimeout> | null = null;
  let lastRefIndexVersion = -1;
  let loadGeneration = 0;

  const entryCache = new Map<string, { signature: string; entry: MapViewEntry }>();
  const sourceChildrenCache = new Map<string, { signature: string; refs: string[] }>();

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
  const calendarEntries = $derived<CalendarEntry[]>(visibleEntries
    .map(calendarEntryFromMapEntry)
    .filter((entry): entry is CalendarEntry => entry != null)
    .sort((a, b) => a.dateOrdinal - b.dateOrdinal || a.startMinutes - b.startMinutes || a.entry.title.localeCompare(b.entry.title)));
  const calendarDayGroups = $derived<CalendarDayGroup[]>(groupCalendarEntries(calendarEntries));
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
  const visualTabs = $derived<VisualTab[]>(deriveVisualTabs(Boolean(mapCenter), calendarEntries.length > 0));
  const selectedVisualTab = $derived.by(() => {
    if (visualTabs.some((tab) => tab.id === activeVisualTab)) return activeVisualTab;
    return visualTabs[0]?.id ?? 'map';
  });
  const showVisualTabs = $derived(visualTabs.length > 1);

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
    const content = typeof embedData.content === 'string' ? embedData.content : '';
    return [
      embedId,
      embedData.type ?? '',
      embedData.updatedAt ?? '',
      content.length,
      content.slice(0, 48),
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
    const match = value.match(/(?:T|^)(\d{1,2}):(\d{2})/);
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
    hoveredRef = null;
  }

  function toggleOptionFilter(key: string, value: string): void {
    const current = optionFilters[key] ?? [];
    const next = current.includes(value)
      ? current.filter((item) => item !== value)
      : [...current, value];
    optionFilters = { ...optionFilters, [key]: next };
    hoveredRef = null;
  }

  function clearFilters(): void {
    activeCategory = 'all';
    rangeFilters = {};
    optionFilters = {};
    hoveredRef = null;
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

  function groupCalendarEntries(items: CalendarEntry[]): CalendarDayGroup[] {
    const groups = new Map<number, CalendarEntry[]>();
    for (const item of items) {
      groups.set(item.dateOrdinal, [...(groups.get(item.dateOrdinal) ?? []), item]);
    }
    return Array.from(groups.entries())
      .sort(([a], [b]) => a - b)
      .map(([dateOrdinal, entriesForDay]) => ({ dateOrdinal, entries: entriesForDay }));
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

  function formatCalendarDate(value: number): string {
    return new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    }).format(new Date(value * 86400000));
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
    return {
      lat: firstNumber(
        content?.lat,
        content?.latitude,
        content?.gps_coordinates_latitude,
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
        gpsCoordinates?.lat,
        gpsCoordinates?.latitude,
      ),
      lon: firstNumber(
        content?.lon,
        content?.lng,
        content?.longitude,
        content?.gps_coordinates_lon,
        content?.gps_coordinates_lng,
        content?.gps_coordinates_longitude,
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
        gpsCoordinates?.lon,
        gpsCoordinates?.lng,
        gpsCoordinates?.longitude,
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
      facets: extractFacets(category, decodedContent),
    } satisfies MapViewEntry;
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
    dispatchEmbedFullscreen({
      embedId: entry.embedId,
      embedType: entry.embedType,
      embedData: entry.embedData,
      decodedContent: entry.decodedContent,
    });
  }

  function scheduleMapHydration(): void {
    if (shouldHydrateMap || mapHydrationTimer) return;
    const hydrate = () => {
      mapHydrationTimer = null;
      shouldHydrateMap = true;
      mapHydrationObserver?.disconnect();
      mapHydrationObserver = null;
    };
    const requestIdle = (globalThis as typeof globalThis & { requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number }).requestIdleCallback;
    if (requestIdle) {
      requestIdle(hydrate, { timeout: 600 });
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
    void loadEntries();
    unsubscribeRefIndex = embedRefIndexVersion.subscribe((version) => {
      if (lastRefIndexVersion === -1) {
        lastRefIndexVersion = version;
        return;
      }
      if (version !== lastRefIndexVersion) {
        lastRefIndexVersion = version;
        if (entries.some((entry) => entry.status !== 'ready')) void loadEntries();
      }
    });
  });

  onDestroy(() => {
    unsubscribeRefIndex?.();
    unsubscribeRefIndex = null;
    mapHydrationObserver?.disconnect();
    mapHydrationObserver = null;
    if (mapHydrationTimer) clearTimeout(mapHydrationTimer);
    mapHydrationTimer = null;
  });

  $effect(() => {
    if (mapShellElement && mapCenter && !shouldHydrateMap) setupMapHydrationObserver();
  });

  $effect(() => {
    if (visualTabs.length > 0 && !visualTabs.some((tab) => tab.id === activeVisualTab)) {
      activeVisualTab = visualTabs[0].id;
    }
  });
</script>

<section class="embeds-results-view embeds-map-view" data-testid="embeds-map-view" data-results-view-id={id} data-map-view-id={id} aria-label={title}>
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
            aria-selected={selectedVisualTab === tab.id}
            aria-controls={`embeds-results-view-panel-${tab.id}`}
            onclick={() => (activeVisualTab = tab.id)}
          >
            {tab.label}
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
          aria-haspopup="menu"
          aria-expanded={filtersOpen}
          onclick={() => (filtersOpen = !filtersOpen)}
        >
          <span class="filter-icon" aria-hidden="true"></span>
          <span>{activeFilterCount === 0 ? 'Filter' : `Filter (${activeFilterCount})`}</span>
        </button>
        {#if filtersOpen}
          <div class="filter-menu" data-testid="embeds-map-view-filter-menu" role="menu">
            <div class="filter-menu-header">
              <strong>Filters</strong>
              {#if activeFilterCount > 0}
                <button type="button" data-testid="embeds-map-view-clear-filters" onclick={clearFilters}>Clear all</button>
              {/if}
            </div>

            {#if categories.length > 1}
              <div class="filter-section">
                <span class="filter-section-title">Type</span>
                <div class="filter-category-options">
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
                      type="date"
                      min={dateFromOrdinal(control.min)}
                      max={dateFromOrdinal(control.max)}
                      value={dateFromOrdinal(rangeValue.min)}
                      oninput={(event) => updateRangeFilter(control.key, 'min', dateOrdinalFromValue((event.currentTarget as HTMLInputElement).value) ?? control.min)}
                    />
                    <input
                      data-testid={`embeds-map-view-filter-${control.key}-max`}
                      type="date"
                      min={dateFromOrdinal(control.min)}
                      max={dateFromOrdinal(control.max)}
                      value={dateFromOrdinal(rangeValue.max)}
                      oninput={(event) => updateRangeFilter(control.key, 'max', dateOrdinalFromValue((event.currentTarget as HTMLInputElement).value) ?? control.max)}
                    />
                  {:else}
                    <input
                      data-testid={`embeds-map-view-filter-${control.key}-min`}
                      type="range"
                      min={control.min}
                      max={control.max}
                      step={control.type === 'time' ? 5 : 1}
                      value={rangeValue.min}
                      oninput={(event) => updateRangeFilter(control.key, 'min', Number((event.currentTarget as HTMLInputElement).value))}
                    />
                    <input
                      data-testid={`embeds-map-view-filter-${control.key}-max`}
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

    <div class="results-view-pane" data-testid="embeds-results-view-pane" data-active-tab={selectedVisualTab}>
      {#if selectedVisualTab === 'calendar'}
        <div class="results-view-calendar" data-testid="embeds-results-view-calendar" id="embeds-results-view-panel-calendar" role="tabpanel" aria-label="Calendar results">
          {#if calendarDayGroups.length > 0}
            {#each calendarDayGroups as dayGroup}
              <section class="calendar-day" data-testid="embeds-results-view-calendar-day">
                <header class="calendar-day-header">
                  <strong>{formatCalendarDate(dayGroup.dateOrdinal)}</strong>
                  <span>{dayGroup.entries.length} {dayGroup.entries.length === 1 ? 'result' : 'results'}</span>
                </header>
                <div class="calendar-items">
                  {#each dayGroup.entries as item}
                    <button
                      type="button"
                      class="calendar-item"
                      class:highlighted={item.entry.highlighted}
                      class:hovered={item.entry.ref === hoveredRef}
                      data-testid="embeds-results-view-calendar-item"
                      data-entry-category={item.entry.category}
                      onclick={() => openEntry(item.entry)}
                      onpointerenter={() => (hoveredRef = item.entry.ref)}
                      onpointerleave={() => {
                        if (hoveredRef === item.entry.ref) hoveredRef = null;
                      }}
                      onfocus={() => (hoveredRef = item.entry.ref)}
                      onblur={() => {
                        if (hoveredRef === item.entry.ref) hoveredRef = null;
                      }}
                    >
                      <span class="calendar-time">{formatCalendarTime(item)}</span>
                      <span class="calendar-copy">
                        <span class="category-pill">{item.entry.category}</span>
                        <strong>{item.entry.title}</strong>
                        <span>{item.entry.subtitle}</span>
                      </span>
                    </button>
                  {/each}
                </div>
              </section>
            {/each}
          {:else}
            <div class="empty-map">Referenced embeds do not expose date and time yet.</div>
          {/if}
        </div>
      {:else}
        <div
          class="map-view-map"
          data-testid="embeds-map-view-map"
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
                minHeight="260px"
                fitBounds={true}
                scrollWheelZoom={false}
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

  .results-view-tabs {
    position: absolute;
    left: 50%;
    display: inline-flex;
    gap: 2px;
    padding: 3px;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: 999px;
    background: var(--color-grey-10, #f9f9f9);
    box-shadow: var(--shadow-xs, 0 2px 4px rgba(0, 0, 0, 0.1));
    transform: translateX(-50%);
  }

  .results-view-tabs button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 999px;
    background: transparent;
    color: var(--color-font-secondary, #666666);
    padding: 6px 12px;
    font: inherit;
    font-size: var(--font-size-xxs, 0.75rem);
    font-weight: 650;
    line-height: 1;
    cursor: pointer;
    transition: background var(--duration-fast, 0.15s) ease, color var(--duration-fast, 0.15s) ease;
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
    gap: 10px;
    width: min(360px, calc(100vw - 32px));
    max-height: min(70vh, 560px);
    overflow: auto;
    box-sizing: border-box;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: var(--radius-5, 12px);
    background: var(--color-grey-0, #ffffff);
    box-shadow: var(--shadow-lg, 0 4px 16px rgba(0, 0, 0, 0.15));
    padding: 12px;
  }

  .filter-menu-header,
  .range-label-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
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

  .filter-menu button.active,
  .filter-menu button[aria-pressed='true'],
  .filter-menu button:hover {
    background: var(--color-grey-blue, #e6eaff);
    color: var(--color-font-primary, #222222);
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

  .results-view-pane {
    min-width: 0;
    min-height: 360px;
    background: var(--color-grey-20, #f3f3f3);
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
    height: 100%;
    background: var(--color-grey-20, #f3f3f3);
  }

  .results-view-calendar {
    display: grid;
    align-content: start;
    gap: 12px;
    min-height: 360px;
    max-height: 420px;
    overflow: auto;
    padding: 14px;
    background:
      linear-gradient(180deg, color-mix(in srgb, var(--color-primary, #6c63ff) 8%, transparent), transparent 160px),
      var(--color-grey-20, #f3f3f3);
  }

  .calendar-day {
    display: grid;
    gap: 8px;
  }

  .calendar-day-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-xxs, 0.75rem);
  }

  .calendar-day-header strong {
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-small, 0.875rem);
  }

  .calendar-items {
    display: grid;
    gap: 8px;
  }

  .calendar-item {
    display: grid;
    grid-template-columns: minmax(54px, auto) minmax(0, 1fr);
    gap: 10px;
    width: 100%;
    border: 1px solid var(--color-grey-25, #e8e8e8);
    border-radius: var(--radius-6, 14px);
    background: var(--color-grey-0, #ffffff);
    color: var(--color-font-primary, #222222);
    padding: 10px;
    text-align: left;
    box-shadow: var(--shadow-xs, 0 2px 4px rgba(0, 0, 0, 0.1));
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
    align-self: start;
    border-radius: 999px;
    background: var(--color-grey-blue, #e6eaff);
    color: var(--color-font-primary, #222222);
    padding: 5px 7px;
    font-size: var(--font-size-tiny, 0.6875rem);
    font-weight: 700;
    line-height: 1.1;
    white-space: nowrap;
  }

  .calendar-copy {
    display: grid;
    gap: 5px;
    min-width: 0;
  }

  .calendar-copy strong {
    overflow: hidden;
    color: var(--color-font-primary, #222222);
    font-size: var(--font-size-small, 0.875rem);
    line-height: 1.25;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .calendar-copy > span:last-child {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-font-secondary, #666666);
    font-size: var(--font-size-xxs, 0.75rem);
    line-height: 1.3;
    -webkit-line-clamp: 2;
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
    .map-view-toolbar {
      align-items: stretch;
      flex-wrap: wrap;
    }

    .entry-count {
      order: 1;
    }

    .results-view-tabs {
      position: static;
      order: 3;
      width: 100%;
      transform: none;
    }

    .results-view-tabs button {
      flex: 1 1 0;
      justify-content: center;
    }

    .filter-menu-wrapper {
      display: grid;
      justify-items: end;
      width: 100%;
      order: 2;
      position: static;
      z-index: auto;
    }

    .filter-menu {
      position: static;
      justify-self: stretch;
      width: 100%;
      max-height: min(42vh, 320px);
      margin-top: 8px;
      border-radius: var(--radius-5, 12px);
      box-shadow: none;
      overscroll-behavior: contain;
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

    .results-view-pane,
    .results-view-calendar {
      min-height: 280px;
    }

    .results-view-calendar {
      max-height: 360px;
    }

    .calendar-item {
      grid-template-columns: 1fr;
    }

    .calendar-copy strong {
      white-space: normal;
    }
  }
</style>
