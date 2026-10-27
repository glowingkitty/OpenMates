/** Calendar artifact data shared by current UI/CLI adapters; Rust integration is deferred. */
import type { CalendarWeekEntry } from '@repo/public-site/components/results/calendarWeek';

export interface CalendarEvent {
  title: string;
  start: string;
  end?: string;
  timezone?: string;
  description?: string;
  location?: string;
  source_url?: string;
}
export interface CalendarEventDocument {
  openmatesType: 'calendar_event';
  schemaVersion: 1;
  primary_event: CalendarEvent;
  context_events: CalendarEvent[];
}
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$/;
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

export function isAllDayDate(value: string): boolean { return DATE.test(value); }

export function parseCalendarEventDate(value: unknown): Date | null {
  if (typeof value !== 'string' || (!DATE.test(value) && !TIMESTAMP.test(value)) || value.startsWith('0000-')) return null;
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== value.slice(0, 10)) return null;
  const date = new Date(DATE.test(value) ? `${value}T00:00:00Z` : value);
  if (!Number.isFinite(date.getTime()) || date.toISOString().length !== 24) return null;
  if (!DATE.test(value) && (Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19) || '0') > 59)) return null;
  return date;
}

function text(value: unknown, limit: number): string | undefined {
  if (value == null) return undefined;
  // eslint-disable-next-line no-control-regex -- Reject raw controls before rendering or export.
  if (typeof value !== 'string' || value.length > limit || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) throw new Error('Invalid calendar text');
  return value.trim() || undefined;
}

export function normalizeCalendarEvent(value: unknown): CalendarEvent | null {
  if (!record(value)) return null;
  try {
    const title = text(value.title, 240);
    const start = parseCalendarEventDate(value.start);
    if (!title || !start) return null;
    const event: CalendarEvent = { title, start: value.start as string };
    if (value.end != null) {
      const end = parseCalendarEventDate(value.end);
      if (!end || isAllDayDate(value.end as string) !== isAllDayDate(event.start) || end.getTime() <= start.getTime()) return null;
      event.end = value.end as string;
    }
    const timezone = text(value.timezone, 100);
    if (timezone) {
      const formatter = new Intl.DateTimeFormat('en', { timeZone: timezone, timeZoneName: 'longOffset' });
      for (const value of [event.start, event.end]) {
        if (!value || isAllDayDate(value)) continue;
        const offset = value.endsWith('Z') ? '+00:00' : value.slice(-6);
        const expected = formatter.formatToParts(new Date(value)).find(part => part.type === 'timeZoneName')?.value.replace('GMT', '') || '+00:00';
        if (expected !== offset && !(expected === '+00:00' && offset === '-00:00')) return null;
      }
      event.timezone = timezone;
    }
    for (const [field, limit] of [['description', 20_000], ['location', 2_000], ['source_url', 2_048]] as const) {
      const item = text(value[field], limit);
      if (item) event[field] = item;
    }
    if (event.source_url) {
      const url = new URL(event.source_url);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || /\s/.test(event.source_url)) return null;
    }
    return event;
  } catch { return null; }
}

export function normalizeCalendarEventContent(value: unknown): CalendarEventDocument | null {
  if (!record(value)) return null;
  let model: unknown = record(value.model) ? value.model : value;
  if (!record(model) || !model.primary_event) {
    if (typeof value.source_json !== 'string' || value.source_json.length > 262_144) return null;
    try { model = JSON.parse(value.source_json); } catch { return null; }
  }
  if (!record(model) || (model.openmatesType !== 'calendar_event' && model.type !== 'calendar_event')) return null;
  if (model.schemaVersion != null && model.schemaVersion !== 1) return null;
  const primary = normalizeCalendarEvent(model.primary_event);
  if (!primary) return null;
  const context: CalendarEvent[] = [];
  const identity = (item: CalendarEvent) => JSON.stringify([item.title, item.start, item.end]);
  const seen = new Set([identity(primary)]);
  for (const raw of (Array.isArray(model.context_events) ? model.context_events : []).slice(0, 50)) {
    const item = normalizeCalendarEvent(raw);
    if (item && !seen.has(identity(item))) { context.push(item); seen.add(identity(item)); }
  }
  return { openmatesType: 'calendar_event', schemaVersion: 1, primary_event: primary, context_events: context };
}

export function formatCalendarEventDate(event: CalendarEvent, locale?: string, compact = false): string {
  const allDay = isAllDayDate(event.start);
  if (compact && event.end) {
    const startOffset = event.start.endsWith('Z') ? 'Z' : event.start.slice(-6);
    const endOffset = event.end.endsWith('Z') ? 'Z' : event.end.slice(-6);
    if (allDay || startOffset === endOffset) {
      let start = new Date(event.start), end = new Date(event.end);
      if (allDay) end.setUTCDate(end.getUTCDate() - 1);
      else if (!event.timezone) {
        start = new Date(start.getTime() + offsetMinutes(startOffset) * 60_000);
        end = new Date(end.getTime() + offsetMinutes(endOffset) * 60_000);
      }
      const formatter = new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric',
        timeZone: allDay ? 'UTC' : event.timezone ?? 'UTC',
        ...(!allDay ? { hour: 'numeric', minute: '2-digit', ...(event.timezone ? { timeZoneName: 'shortOffset' as const } : {}) } : {}),
      });
      const label = formatter.formatRange(start, end);
      return !allDay && !event.timezone ? `${label} UTC${startOffset === 'Z' ? '' : startOffset}` : label;
    }
  }
  const format = (value: string, last = false) => {
    let date = new Date(value);
    if (allDay && last) date.setUTCDate(date.getUTCDate() - 1);
    const offset = value.endsWith('Z') ? 'Z' : value.slice(-6);
    if (!allDay && !event.timezone) date = new Date(date.getTime() + offsetMinutes(offset) * 60_000);
    const label = new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'short', day: 'numeric',
      ...(allDay ? { timeZone: 'UTC' } : { hour: 'numeric', minute: '2-digit', timeZone: event.timezone ?? 'UTC', ...(event.timezone ? { timeZoneName: 'shortOffset' as const } : {}) }),
    }).format(date);
    return !allDay && !event.timezone ? `${label} UTC${offset === 'Z' ? '' : offset}` : label;
  };
  const start = format(event.start);
  const end = event.end ? format(event.end, true) : '';
  return `${start}${end && end !== start ? ` – ${end}` : ''}`;
}

function offsetMinutes(offset: string): number {
  return offset === 'Z' ? 0 : (offset.startsWith('-') ? -1 : 1) * (Number(offset.slice(1, 3)) * 60 + Number(offset.slice(4)));
}

/** Project all entries into one timezone so overlaps remain meaningful. */
export function calendarEventWeekEntries(document: CalendarEventDocument, embedId: string): CalendarWeekEntry[] {
  const primary = document.primary_event;
  const offset = !primary.timezone && !isAllDayDate(primary.start) ? (primary.start.endsWith('Z') ? 'Z' : primary.start.slice(-6)) : undefined;
  const zone = primary.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  function position(value: string) {
    if (isAllDayDate(value)) return { ordinal: new Date(`${value}T00:00:00Z`).getTime() / 86_400_000, minutes: 0 };
    const date = new Date(value);
    if (offset) {
      const minutes = offsetMinutes(offset);
      const shifted = new Date(date.getTime() + minutes * 60_000);
      return { ordinal: new Date(`${shifted.toISOString().slice(0, 10)}T00:00:00Z`).getTime() / 86_400_000,
        minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes() };
    }
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(date).map(part => [part.type, part.value]));
    return { ordinal: new Date(`${parts.year}-${parts.month}-${parts.day}T00:00:00Z`).getTime() / 86_400_000, minutes: Number(parts.hour) * 60 + Number(parts.minute) };
  }
  return [primary, ...document.context_events].map((event, index) => {
    const start = position(event.start), end = event.end ? position(event.end) : undefined;
    const projectedEnd = end ? (end.ordinal - start.ordinal) * 1440 + end.minutes : undefined;
    const timedEnd = event.end && projectedEnd != null ? (projectedEnd > start.minutes ? projectedEnd : start.minutes + (new Date(event.end).getTime() - new Date(event.start).getTime()) / 60_000) : undefined;
    return { ref: index ? `${embedId}:context:${index}` : embedId, title: event.title,
      dateOrdinal: start.ordinal, startMinutes: start.minutes,
      endMinutes: !isAllDayDate(event.start) ? timedEnd : undefined,
      endKnown: event.end != null,
      endDateOrdinal: isAllDayDate(event.start) ? end?.ordinal : undefined,
      dateOnly: isAllDayDate(event.start), highlighted: index === 0, contextual: index !== 0,
      minimumDisplayMinutes: 15, location: event.location };
  });
}
