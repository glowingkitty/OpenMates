// Station-local formatting of travel timestamps.
//
// Departures and arrivals arrive as ISO timestamps with the station's UTC offset
// ("2026-11-16T06:43:00+01:00"). A traveller reads the time printed on the
// station board, so the wall-clock part of the timestamp is shown as is,
// whatever the viewer's own time zone. Converting through `new Date()` in the
// browser's zone showed Berlin 06:43 as 05:43 to a viewer on UTC (TASK-3927).

const ISO_WALL_CLOCK = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

function wallClock(iso: string): Date | null {
  const match = ISO_WALL_CLOCK.exec(iso.trim());
  if (!match) return null;
  const [year, month, day, hour, minute] = match.slice(1).map(Number);
  const date = new Date(Date.UTC(year, month - 1, day, hour, minute));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "06:43" (or "6:43 AM" in 12-hour locales) for the station-local time; '' when unreadable. */
export function formatStationTime(iso: string | null | undefined, locale?: string): string {
  if (!iso) return '';
  const date = wallClock(iso);
  if (!date) return '';
  return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(date);
}

/** "Mon, Nov 16" for the station-local date; '' when unreadable. */
export function formatStationDate(iso: string | null | undefined, locale?: string): string {
  if (!iso) return '';
  const date = wallClock(iso);
  if (!date) return '';
  return new Intl.DateTimeFormat(locale, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
}

/** "Mon, Nov 16, 06:43": a readable timestamp for one fact line; '' when unreadable. */
export function formatStationDateTime(iso: string | null | undefined, locale?: string): string {
  const date = formatStationDate(iso, locale);
  const time = formatStationTime(iso, locale);
  return date && time ? `${date}, ${time}` : date || time;
}
