/** Event children arrive as nested legacy JSON or flattened persisted TOON. */
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
  const venue = record(content.venue);
  const organizer = record(content.organizer);
  const fee = record(content.fee);
  const value = (nested: Record<string, unknown> | undefined, prefix: string, key: string) => nested?.[key] ?? content[`${prefix}_${key}`];
  const has = (nested: Record<string, unknown> | undefined, prefix: string) => !!nested || Object.keys(content).some(key => key.startsWith(`${prefix}_`) && content[key] != null);
  return {
    ...content,
    embed_id: embedId,
    id: string(content.id), provider: string(content.provider), title: string(content.title),
    description: string(content.description), url: string(content.url),
    date_start: string(content.date_start), date_end: string(content.date_end),
    timezone: string(content.timezone), event_type: string(content.event_type),
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
    image_url: event.image_url,
    cover_url: event.cover_url,
  };
}
