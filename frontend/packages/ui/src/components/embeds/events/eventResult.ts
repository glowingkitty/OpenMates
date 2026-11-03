/** Event children arrive as nested legacy JSON or flattened persisted TOON. */
import type { AuthoredResultMetadata } from '../../../types/authoredResult';
import { isAllDayDate, parseCalendarEventDate } from '../../../utils/calendarEvent';
export interface EventResult extends Record<string, unknown> {
  embed_id: string;
  id?: string;
  provider?: string;
  title?: string;
  description?: string;
  url?: string;
  date_start?: string;
  date_end?: string;
  timezone?: string;
  online?: boolean;
  online_url?: string;
  authoring?: AuthoredResultMetadata;
  event_type?: string;
  venue?: { name?: string; address?: string; city?: string; state?: string; country?: string; lat?: number; lon?: number; [key: string]: unknown };
  organizer?: { id?: string; name?: string; slug?: string; [key: string]: unknown };
  rsvp_count?: number;
  is_paid?: boolean;
  fee?: { amount?: number; currency?: string; [key: string]: unknown };
  image_url?: string | null;
  cover_url?: string | null;
}

const record = (value: unknown): Record<string, unknown> | undefined =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
const string = (value: unknown): string | undefined => typeof value === 'string' ? value : undefined;
const number = (value: unknown): number | undefined => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return undefined;
};

/** Preserve raw/additive fields while restoring only the known nested event data. */
export function normalizeEventResult(content: Record<string, unknown>, embedId = string(content.embed_id) || ''): EventResult {
  const venue = record(content.venue) ?? record(content.location)
    ?? (typeof content.location === 'string' && content.location.trim() ? { name: content.location } : undefined);
  const organizer = record(content.organizer)
    ?? (typeof content.organizer === 'string' && content.organizer.trim() ? { name: content.organizer } : undefined);
  const authoring = record(content.authoring);
  const fee = record(content.fee);
  const value = (nested: Record<string, unknown> | undefined, prefix: string, key: string) => nested?.[key] ?? content[`${prefix}_${key}`];
  const has = (nested: Record<string, unknown> | undefined, prefix: string) => !!nested || Object.keys(content).some(key => key.startsWith(`${prefix}_`) && content[key] != null);
  return {
    ...content,
    embed_id: embedId,
    id: string(content.id), provider: string(content.provider), title: string(content.title),
    description: string(content.description), url: string(content.url) || string(content.source_url),
    date_start: string(content.date_start), date_end: string(content.date_end),
    timezone: string(content.timezone), event_type: string(content.event_type),
    online: typeof content.online === 'boolean' ? content.online : undefined,
    online_url: string(content.online_url),
    authoring: authoring?.schema_version === 1 && authoring.kind === 'events.event'
      && ['researched', 'user_provided', 'draft'].includes(String(authoring.origin))
      && Array.isArray(authoring.sources) ? authoring as unknown as AuthoredResultMetadata : undefined,
    venue: has(venue, 'venue') ? {
      ...venue,
      name: string(value(venue, 'venue', 'name')), address: string(value(venue, 'venue', 'address')),
      city: string(value(venue, 'venue', 'city')), state: string(value(venue, 'venue', 'state')),
      country: string(value(venue, 'venue', 'country')),
      lat: number(value(venue, 'venue', 'lat')), lon: number(value(venue, 'venue', 'lon')),
    } : undefined,
    organizer: has(organizer, 'organizer') ? {
      ...organizer,
      id: string(value(organizer, 'organizer', 'id')), name: string(value(organizer, 'organizer', 'name')),
      slug: string(value(organizer, 'organizer', 'slug')),
    } : undefined,
    fee: has(fee, 'fee') ? {
      ...fee, amount: number(value(fee, 'fee', 'amount')), currency: string(value(fee, 'fee', 'currency')),
    } : undefined,
    rsvp_count: number(content.rsvp_count),
    is_paid: typeof content.is_paid === 'boolean' ? content.is_paid : undefined,
    image_url: content.image_url === null ? null : string(content.image_url),
    cover_url: content.cover_url === null ? null : string(content.cover_url),
  };
}

/**
 * The request boundary accepts only the renderer's known event fields. Keep this
 * separate from normalization, which must retain transport/provider metadata.
 */
export function projectVisibleEventResult(event: EventResult): EventResult {
  return {
    embed_id: event.embed_id,
    id: event.id,
    provider: event.provider,
    title: event.title,
    description: event.description,
    url: event.url,
    date_start: event.date_start,
    date_end: event.date_end,
    timezone: event.timezone,
    event_type: event.event_type,
    venue: event.venue ? {
      name: event.venue.name,
      address: event.venue.address,
      city: event.venue.city,
      state: event.venue.state,
      country: event.venue.country,
      lat: event.venue.lat,
      lon: event.venue.lon,
    } : undefined,
    organizer: event.organizer ? {
      id: event.organizer.id,
      name: event.organizer.name,
      slug: event.organizer.slug,
    } : undefined,
    fee: event.fee ? { amount: event.fee.amount, currency: event.fee.currency } : undefined,
    rsvp_count: event.rsvp_count,
    is_paid: event.is_paid,
    image_url: typeof event.image_url === 'string' && /^(?:blob:|data:)/.test(event.image_url) ? undefined : event.image_url,
    cover_url: typeof event.cover_url === 'string' && /^(?:blob:|data:)/.test(event.cover_url) ? undefined : event.cover_url,
    ...(event.online === undefined ? {} : { online: event.online }),
    ...(event.online_url === undefined ? {} : { online_url: event.online_url }),
    ...(event.authoring ? { authoring: {
      schema_version: event.authoring.schema_version,
      kind: event.authoring.kind,
      origin: event.authoring.origin,
      sources: event.authoring.sources.map(source => ({
        ...(typeof source.url === 'string' ? { url: source.url } : {}),
        ...(typeof source.label === 'string' ? { label: source.label } : {}),
        ...(typeof source.embed_ref === 'string' ? { embed_ref: source.embed_ref } : {}),
      })),
      ...(event.authoring.observed_at ? { observed_at: event.authoring.observed_at } : {}),
    } } : {}),
  };
}


/** All-day dates are calendar days, never midnight in the viewer's timezone. */
export function isEventDateOnly(value: string | undefined): boolean {
  return !!value && isAllDayDate(value) && !!parseCalendarEventDate(value);
}
function displayDate(value: string | undefined, timezone?: string): { date: Date; timezone: string; offset?: string } | undefined {
  const parsed = parseCalendarEventDate(value);
  if (!parsed || !value) return;
  if (isAllDayDate(value)) return { date: parsed, timezone: 'UTC' };
  if (timezone) {
    try { new Intl.DateTimeFormat(undefined, { timeZone: timezone }); return { date: parsed, timezone }; }
    catch { /* Keep the supplied numeric offset instead of substituting a machine timezone. */ }
  }
  const wallDate = new Date(value.replace(/(?:Z|[+-]\d{2}:\d{2})$/, 'Z'));
  return { date: wallDate, timezone: 'UTC', offset: value.endsWith('Z') ? 'UTC' : `UTC${value.slice(-6)}` };
}
export function formatEventResultDate(value: string | undefined, timezone?: string, locale?: string): string {
  const display = displayDate(value, timezone);
  return display ? new Intl.DateTimeFormat(locale, { timeZone: display.timezone,
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }).format(display.date) : '';
}
export function formatEventResultTime(value: string | undefined, timezone?: string, locale?: string): string {
  if (isEventDateOnly(value)) return '';
  const display = displayDate(value, timezone);
  if (!display) return '';
  const label = new Intl.DateTimeFormat(locale, { timeZone: display.timezone,
    hour: 'numeric', minute: '2-digit' }).format(display.date);
  return display.offset ? `${label} ${display.offset}` : label;
}
/** Feed the existing badge without moving a supplied day across an absent zone. */
export function eventCalendarBadge(value: string | undefined, timezone?: string): { date?: string; timezone?: string } {
  const display = displayDate(value, timezone);
  if (!display || !value) return {};
  if (isAllDayDate(value) || display.offset) return { date: value.slice(0, 10), timezone: 'UTC' };
  return { date: value, timezone: display.timezone };
}


/** Source-page actions are explicit and accept only ordinary safe external links. */
export function eventResultSourceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value || [...value].some(character => character.charCodeAt(0) <= 32
    || character.charCodeAt(0) === 127 || character === "\\")) return;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? value : undefined;
  } catch { return; }
}
