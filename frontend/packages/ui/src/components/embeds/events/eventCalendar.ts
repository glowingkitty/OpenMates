/** Explicit local .ics export for event results; calendar artifacts keep their own exclusive-end contract. */
import { buildCalendarFile, downloadCalendarFile, sanitizeCalendarFilename, type CalendarDownloadInput } from '../../../utils/calendarDownload';
import { parseCalendarEventDate, isAllDayDate } from '../../../utils/calendarEvent';
import { eventResultSourceUrl, type EventResult } from './eventResult';

const DAY_MS = 86_400_000;

/** Convert only the result card's inclusive all-day end, never its stored facts. */
export function eventCalendarInput(event: EventResult): CalendarDownloadInput | null {
  if (typeof event.title !== 'string' || !event.title.trim() || event.title.length > 500
    || !event.date_start || (event.status && event.status !== 'finished')) return null;
  const start = parseCalendarEventDate(event.date_start);
  if (!start) return null;
  const allDay = isAllDayDate(event.date_start);
  let end: string | undefined;
  if (event.date_end) {
    const parsedEnd = parseCalendarEventDate(event.date_end);
    if (!parsedEnd || isAllDayDate(event.date_end) !== allDay
      || parsedEnd.getTime() < start.getTime() || (!allDay && parsedEnd.getTime() === start.getTime())) return null;
    if (allDay) {
      const exclusiveEnd = new Date(parsedEnd.getTime() + DAY_MS);
      if (exclusiveEnd.toISOString().length !== 24) return null;
      end = exclusiveEnd.toISOString().slice(0, 10);
    } else end = event.date_end;
  } else if (allDay) {
    const nextDay = new Date(start.getTime() + DAY_MS);
    if (nextDay.toISOString().length !== 24) return null;
    end = nextDay.toISOString().slice(0, 10);
  }
  const url = eventResultSourceUrl(event.url);
  const location = [event.venue?.name, event.venue?.address,
    [event.venue?.city, event.venue?.state, event.venue?.country].filter(Boolean).join(', ')].filter(Boolean).join('\n');
  const description = [event.description, event.organizer?.name ? `Organizer: ${event.organizer.name}` : undefined,
    event.provider ? `Source: ${event.provider}` : undefined,
    event.authoring ? `Origin: ${event.authoring.origin}` : undefined].filter(Boolean).join('\n\n');
  return {
    title: event.title, start: event.date_start, end,
    location: location || undefined, description: description || undefined, url,
    filename: sanitizeCalendarFilename(`${event.title}-${event.date_start.slice(0, 10)}`),
    uid: event.embed_id ? `${event.embed_id}@openmates` : undefined,
    preserveUnknownEnd: true,
  };
}

export function buildEventResultCalendarFile(event: EventResult): string | null {
  const input = eventCalendarInput(event);
  return input ? buildCalendarFile(input) : null;
}
export function downloadEventResultCalendarFile(event: EventResult): boolean {
  const input = eventCalendarInput(event);
  return input ? downloadCalendarFile(input) : false;
}
