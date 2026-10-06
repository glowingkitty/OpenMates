/** Text presentation for the virtual embeds_results_view protocol block. */
import type { DecryptedEmbed } from './client.js';

export type TuiResultsViewMode = 'map' | 'calendar' | 'list';
export interface TuiResultsViewDescriptor {
  title: string;
  embeds: string[];
  sources: string[];
  highlight: string[];
}
export interface TuiResultsViewEntry {
  ref: string;
  title: string;
  address?: string;
  venueName?: string;
  provider?: string;
  date?: string;
  time?: string;
  latitude?: number;
  longitude?: number;
  route?: Array<{ latitude: number; longitude: number; label?: string }>;
  highlighted: boolean;
}
export interface TuiResultsViewData {
  title: string;
  entries: TuiResultsViewEntry[];
  missingRefs: string[];
  failedSources: number;
  availableModes: TuiResultsViewMode[];
}
export interface TuiResultsViewRenderOptions {
  mode?: TuiResultsViewMode;
  /** Number assigned by the parent to this view within the chat. */
  viewKey?: string | number;
  /** Converts canonical child IDs to chat-local /embed aliases. */
  aliasForEmbed?: (ref: string) => string;
  selectedRefs?: readonly string[];
}

const MAX_VISIBLE_ENTRIES = 40;
const fields = new Set(['title', 'embeds', 'sources', 'highlight']);

function uniqueRefs(refs: readonly string[]): string[] {
  const seen = new Set<string>();
  return refs.map(ref => ref.trim().replace(/^embed:/, '')).filter(ref => {
    if (!ref || seen.has(ref)) return false;
    seen.add(ref);
    return true;
  });
}

/** Mirrors the web parser: case-insensitive allowed keys, last nonempty value wins. */
export function parseTuiResultsViewBlock(code: string): TuiResultsViewDescriptor {
  const values = new Map<string, string>();
  for (const rawLine of code.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const colon = line.indexOf(':');
    if (colon < 0) continue;
    const key = line.slice(0, colon).trim().toLowerCase();
    const value = line.slice(colon + 1).trim();
    if (fields.has(key) && value) values.set(key, value);
  }
  const refs = (key: string) => [...new Set((values.get(key) ?? '').split(',').map(ref => ref.trim()).filter(Boolean))];
  return { title: values.get('title') || 'Results view', embeds: refs('embeds'), sources: refs('sources'), highlight: refs('highlight') };
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function firstString(...values: unknown[]): string {
  return values.find(value => typeof value === 'string' && value.trim())?.toString().trim() ?? '';
}
function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return undefined;
}
function point(lat: unknown, lon: unknown): { latitude: number; longitude: number } | null {
  const latitude = firstNumber(lat), longitude = firstNumber(lon);
  return latitude != null && longitude != null && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180
    ? { latitude, longitude } : null;
}
function firstPoint(...pairs: Array<[unknown, unknown]>): { latitude: number; longitude: number } | null {
  for (const pair of pairs) {
    const result = point(...pair);
    if (result) return result;
  }
  return null;
}
function embedPoint(content: Record<string, unknown>) {
  const location = record(content.location), venue = record(content.venue);
  const coordinates = record(content.coordinates), gps = record(content.gps_coordinates);
  if (firstString(content.event_type, content.eventType).toLowerCase() === 'online' ||
    firstString(content.venue_name, venue?.name).toLowerCase() === 'online event') return null;
  return firstPoint(
    [content.venue_lat, content.venue_lon], [content.venue_lat, content.venue_lng], [content.venue_latitude, content.venue_longitude],
    [venue?.lat, venue?.lon], [venue?.lat, venue?.lng], [venue?.latitude, venue?.longitude],
    [content.location_lat, content.location_lon], [content.location_lat, content.location_lng], [content.location_latitude, content.location_longitude],
    [location?.lat, location?.lon], [location?.lat, location?.lng], [location?.latitude, location?.longitude],
    [content.gps_coordinates_latitude, content.gps_coordinates_longitude], [content.gps_coordinates_latitude, content.gps_coordinates_lon],
    [gps?.latitude, gps?.longitude], [gps?.lat, gps?.lon], [gps?.lat, gps?.lng],
    [coordinates?.latitude, coordinates?.longitude], [coordinates?.lat, coordinates?.lon], [coordinates?.lat, coordinates?.lng],
    [content.latitude, content.longitude], [content.lat, content.lon], [content.lat, content.lng],
  );
}
function routePoint(value: unknown) {
  const item = record(value);
  if (!item) return null;
  const coords = firstPoint([item.lat, item.lon], [item.lat, item.lng], [item.latitude, item.longitude]);
  return coords && { ...coords, label: firstString(item.label, item.name, item.station, item.city) || undefined };
}
function embedRoute(content: Record<string, unknown>): TuiResultsViewEntry['route'] {
  const raw = content.route_points ?? content.route ?? content.path ?? content.polyline_points;
  if (Array.isArray(raw)) return raw.map(routePoint).filter((value): value is NonNullable<typeof value> => value != null);
  const legs = Array.isArray(content.legs) ? content.legs : [];
  const structuredSegments = legs.flatMap(leg => Array.isArray(record(leg)?.segments) ? record(leg)?.segments as unknown[] : []);
  const flatSegments: Record<string, unknown>[] = [];
  for (let leg = 0; leg < 8; leg++) {
    for (let segment = 0; segment < 32; segment++) {
      const prefix = `legs_${leg}_segments_${segment}`;
      const item = {
        departure_station: content[`${prefix}_departure_station`],
        departure_latitude: content[`${prefix}_departure_latitude`],
        departure_longitude: content[`${prefix}_departure_longitude`],
        arrival_station: content[`${prefix}_arrival_station`],
        arrival_latitude: content[`${prefix}_arrival_latitude`],
        arrival_longitude: content[`${prefix}_arrival_longitude`],
      };
      if (Object.values(item).some(value => value != null)) flatSegments.push(item);
      else if (segment === 0) break;
    }
  }
  const segments = structuredSegments.length ? structuredSegments : flatSegments;
  const points = segments.flatMap(segment => {
    const item = record(segment);
    if (!item) return [];
    const departure = firstPoint([item.departure_latitude, item.departure_longitude], [item.departure_lat, item.departure_lng], [item.departure_lat, item.departure_lon]);
    const arrival = firstPoint([item.arrival_latitude, item.arrival_longitude], [item.arrival_lat, item.arrival_lng], [item.arrival_lat, item.arrival_lon]);
    return [departure && { ...departure, label: firstString(item.departure_station) || undefined }, arrival && { ...arrival, label: firstString(item.arrival_station) || undefined }]
      .filter((value): value is NonNullable<typeof value> => value != null);
  });
  if (points.length > 1) return points.filter((item, index) => index === 0 || item.latitude !== points[index - 1].latitude || item.longitude !== points[index - 1].longitude);
  const flightTrack = record(content.flight_track);
  if (Array.isArray(flightTrack?.tracks)) {
    const trackPoints = flightTrack.tracks.map(routePoint).filter((value): value is NonNullable<typeof value> => value != null);
    if (trackPoints.length > 1) return trackPoints;
  }
  const origin = record(content.origin), destination = record(content.destination);
  const start = firstPoint([content.origin_lat, content.origin_lon], [content.origin_latitude, content.origin_longitude], [origin?.lat, origin?.lon], [origin?.latitude, origin?.longitude]);
  const end = firstPoint([content.destination_lat, content.destination_lon], [content.destination_latitude, content.destination_longitude], [destination?.lat, destination?.lon], [destination?.latitude, destination?.longitude]);
  return start && end ? [{ ...start, label: firstString(content.origin_name, content.origin) || undefined }, { ...end, label: firstString(content.destination_name, content.destination) || undefined }] : [];
}
function validDate(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?=$|[T\s])/.exec(value);
  if (!match) return undefined;
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? match[0] : undefined;
}
function entryDate(content: Record<string, unknown>): string | undefined {
  // The first populated web candidate governs date eligibility; never infer a date from creation time.
  return validDate(firstString(content.date, content.datetime, content.start_date, content.scheduled_departure,
    content.slot_datetime, content.date_start, content.departure, content.start_time, content.check_in_date, content.check_in));
}
function entryTime(content: Record<string, unknown>): string | undefined {
  const value = firstString(content.departure, content.scheduled_departure, content.slot_datetime, content.start_time, content.date_start);
  const match = /(?:T|\s|^)(\d{1,2}):(\d{2})/.exec(value) ?? /\b(\d{1,2}):(\d{2})\b/.exec(firstString(content.time_range));
  if (!match) return undefined;
  const hour = Number(match[1]), minute = Number(match[2]);
  return hour < 24 && minute < 60 ? `${match[1].padStart(2, '0')}:${match[2]}` : undefined;
}
function refsFromUnknown(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((ref): ref is string => typeof ref === 'string' && ref.length > 0);
  if (typeof value !== 'string') return [];
  if (value.trim().startsWith('[')) {
    try {
      const parsed: unknown = JSON.parse(value);
      if (Array.isArray(parsed)) return refsFromUnknown(parsed);
    } catch { /* Fall through to the delimited format. */ }
  }
  return value.split(/[|,\s]+/).map(ref => ref.trim()).filter(Boolean);
}
/** Existing source embed children, with the same visible bound as the view. */
export function tuiResultsSourceChildren(embed: DecryptedEmbed): string[] {
  const content = embed.content;
  if (!content || content.status === 'error' || content.status === 'cancelled') return [];
  return uniqueRefs([...refsFromUnknown(content.embed_ids), ...refsFromUnknown(content.child_embed_ids)]).slice(0, MAX_VISIBLE_ENTRIES);
}
function embedAt(embeds: ReadonlyMap<string, DecryptedEmbed> | Readonly<Record<string, DecryptedEmbed>>, ref: string): DecryptedEmbed | undefined {
  return embeds instanceof Map ? embeds.get(ref) : (embeds as Readonly<Record<string, DecryptedEmbed>>)[ref];
}

/** Uses already hydrated embeds; source roots are expanded one level in web order. */
export function buildTuiResultsViewData(
  descriptor: TuiResultsViewDescriptor,
  embeds: ReadonlyMap<string, DecryptedEmbed> | Readonly<Record<string, DecryptedEmbed>>,
): TuiResultsViewData {
  const missingRefs: string[] = [];
  let failedSources = 0;
  const children = descriptor.sources.flatMap(sourceRef => {
    const normalized = sourceRef.trim().replace(/^embed:/, '');
    const source = embedAt(embeds, normalized);
    if (!source) missingRefs.push(normalized);
    if (source?.content?.status === 'error' || source?.content?.status === 'cancelled') failedSources++;
    return source ? tuiResultsSourceChildren(source) : [];
  });
  const refs = uniqueRefs([...descriptor.embeds, ...children]).slice(0, MAX_VISIBLE_ENTRIES);
  const highlighted = new Set(uniqueRefs(descriptor.highlight));
  const entries = refs.flatMap(ref => {
    const embed = embedAt(embeds, ref);
    if (!embed) { missingRefs.push(ref); return []; }
    const content = embed.content ?? {};
    const coords = embedPoint(content), route = embedRoute(content), date = entryDate(content);
    if (!coords && !route?.length && !date) return [];
    const venue = record(content.venue), location = record(content.location);
    const origin = firstString(content.origin, content.origin_name, content.from);
    const destination = firstString(content.destination, content.destination_name, content.to);
    return [{
      ref,
      title: origin && destination ? `${origin} → ${destination}` : firstString(content.title, content.name, content.displayName, content.display_name, venue?.name, content.summary, embed.type, ref),
      venueName: firstString(content.venue_name, venue?.name) || undefined,
      address: firstString(content.venue_address, content.formattedAddress, content.formatted_address, content.address, venue?.address, location?.address) || undefined,
      provider: firstString(content.provider, content.booking_provider, content.source_provider) || undefined,
      date, time: entryTime(content),
      latitude: coords?.latitude, longitude: coords?.longitude,
      route: route?.length ? route : undefined,
      highlighted: highlighted.has(ref) || highlighted.has(embed.embedId),
    } satisfies TuiResultsViewEntry];
  });
  const hasMap = entries.some(entry => entry.latitude != null || Boolean(entry.route?.length));
  const hasCalendar = entries.some(entry => entry.date);
  return { title: descriptor.title || 'Results view', entries, missingRefs: uniqueRefs(missingRefs), failedSources,
    availableModes: [...(hasMap ? ['map' as const] : []), ...(hasCalendar ? ['calendar' as const] : []), ...(entries.length ? ['list' as const] : [])] };
}

function compass(entry: TuiResultsViewEntry, entries: TuiResultsViewEntry[]): string {
  const points = entries.flatMap(item => item.latitude != null && item.longitude != null
    ? [{ latitude: item.latitude, longitude: item.longitude }] : item.route ?? []);
  const own = entry.latitude != null && entry.longitude != null
    ? { latitude: entry.latitude, longitude: entry.longitude } : entry.route?.[0];
  if (!own || !points.length) return '';
  const centerLat = (Math.min(...points.map(item => item.latitude)) + Math.max(...points.map(item => item.latitude))) / 2;
  const centerLon = (Math.min(...points.map(item => item.longitude)) + Math.max(...points.map(item => item.longitude))) / 2;
  const ns = own.latitude > centerLat ? 'N' : own.latitude < centerLat ? 'S' : '';
  const ew = own.longitude > centerLon ? 'E' : own.longitude < centerLon ? 'W' : '';
  return ns + ew || 'center';
}
function entryLines(entry: TuiResultsViewEntry, index: number, entries: TuiResultsViewEntry[], mode: TuiResultsViewMode, alias: (ref: string) => string, selected: Set<string>): string[] {
  const marker = selected.has(entry.ref) ? '▶' : entry.highlighted ? '★' : ' ';
  const where = mode === 'map' ? compass(entry, entries) : '';
  const dateTime = [entry.date, entry.time].filter(Boolean).join(' ');
  const summary = [where, dateTime, entry.provider].filter(Boolean).join(' · ');
  const coords = entry.latitude != null && entry.longitude != null ? `${entry.latitude.toFixed(5)}, ${entry.longitude.toFixed(5)}` : '';
  const route = entry.route?.length ? entry.route.map(point => point.label || `${point.latitude.toFixed(3)},${point.longitude.toFixed(3)}`).join(' → ') : '';
  return [`${marker} ${index + 1}. ${entry.title}${summary ? ` · ${summary}` : ''}`,
    ...([entry.venueName,entry.address].filter(Boolean).length ? [`   ${[entry.venueName,entry.address].filter(Boolean).join(" · ")}`] : []),
    ...(mode === 'map' && (route || coords) ? [`   ${route || coords}`] : []),
    `   /embed ${alias(entry.ref)}`];
}

/** Returns plain lines; the parent owns width wrapping, colors, and mode state. */
export function renderTuiResultsViewLines(data: TuiResultsViewData, options: TuiResultsViewRenderOptions = {}): string[] {
  const mode = options.mode && data.availableModes.includes(options.mode) ? options.mode : data.availableModes[0] ?? 'list';
  const viewKey = options.viewKey == null ? '' : String(options.viewKey);
  const alias = options.aliasForEmbed ?? ((ref: string) => ref);
  if (!data.entries.length) return [data.title, data.failedSources ? 'Referenced source failed. No verified results.'
    : data.missingRefs.length ? 'Referenced results are not available yet.' : 'No results with a valid location or date.'];
  const selected = new Set(options.selectedRefs ?? []);
  const lines = [`${data.title} · ${mode[0].toUpperCase()}${mode.slice(1)} · ${data.entries.length} results`];
  if (viewKey) lines.push(` /view ${viewKey} ${data.availableModes.join('|')} · Switch view`);
  if (mode === 'calendar') {
    const dated = data.entries.map((entry, index) => ({ entry, index })).filter(item => item.entry.date);
    dated.sort((a, b) => a.entry.date!.localeCompare(b.entry.date!) || (a.entry.time ?? '').localeCompare(b.entry.time ?? '') || a.index - b.index);
    let lastDate = '';
    for (const {entry, index} of dated) {
      if (entry.date !== lastDate) { lastDate = entry.date!; lines.push(lastDate); }
      lines.push(...entryLines(entry, index, data.entries, mode, alias, selected));
    }
  } else {
    data.entries.forEach((entry, index) => lines.push(...entryLines(entry, index, data.entries, mode, alias, selected)));
  }
  if (data.missingRefs.length) lines.push(`${data.missingRefs.length} referenced result${data.missingRefs.length === 1 ? '' : 's'} unavailable.`);
  return lines;
}
