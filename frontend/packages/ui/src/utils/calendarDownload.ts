/*
 * frontend/packages/ui/src/utils/calendarDownload.ts
 *
 * Small browser-side helper for generating iCalendar (.ics) files.
 * Used by fullscreen embeds that represent scheduled real-world items.
 * Keeps download mechanics and ICS escaping consistent across embeds.
 *
 * See docs/architecture/embeds.md
 */

export interface CalendarDownloadInput {
  title: string;
  start: string;
  end?: string;
  location?: string;
  description?: string;
  url?: string;
  filename?: string;
}

const DEFAULT_EVENT_DURATION_MS = 60 * 60 * 1000;
const ALL_DAY_DURATION_MS = 24 * DEFAULT_EVENT_DURATION_MS;
const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function parseCalendarDate(value: string | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatUtcDate(date: Date): string {
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
}

function escapeIcsText(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n');
}

function foldIcsLine(line: string): string {
  const maxLength = 75;
  if (line.length <= maxLength) return line;

  const chunks: string[] = [];
  let remaining = line;
  while (remaining.length > maxLength) {
    chunks.push(remaining.slice(0, maxLength));
    remaining = ` ${remaining.slice(maxLength)}`;
  }
  chunks.push(remaining);
  return chunks.join('\r\n');
}

export function sanitizeCalendarFilename(value: string): string {
  const filename = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);

  return filename || 'calendar-event';
}

export function buildCalendarFile(input: CalendarDownloadInput): string | null {
  const start = parseCalendarDate(input.start);
  if (!start) return null;

  const parsedEnd = parseCalendarDate(input.end);
  // A date without a time represents an all-day entry, not midnight UTC.
  // iCalendar DTEND is exclusive, so a single day ends on the following date.
  const allDay = DATE_ONLY_PATTERN.test(input.start);
  const end = parsedEnd && parsedEnd.getTime() > start.getTime()
    ? parsedEnd
    : new Date(start.getTime() + (allDay ? ALL_DAY_DURATION_MS : DEFAULT_EVENT_DURATION_MS));
  const now = new Date();
  const uid = `${start.getTime()}-${sanitizeCalendarFilename(input.title)}@openmates`;

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//OpenMates//Embeds//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${formatUtcDate(now)}`,
    allDay ? `DTSTART;VALUE=DATE:${formatUtcDate(start).slice(0, 8)}` : `DTSTART:${formatUtcDate(start)}`,
    allDay ? `DTEND;VALUE=DATE:${formatUtcDate(end).slice(0, 8)}` : `DTEND:${formatUtcDate(end)}`,
    `SUMMARY:${escapeIcsText(input.title || 'Calendar event')}`,
  ];

  if (input.location) lines.push(`LOCATION:${escapeIcsText(input.location)}`);
  if (input.description) lines.push(`DESCRIPTION:${escapeIcsText(input.description)}`);
  if (input.url) lines.push(`URL:${escapeIcsText(input.url)}`);

  lines.push('END:VEVENT', 'END:VCALENDAR');
  return `${lines.map(foldIcsLine).join('\r\n')}\r\n`;
}

export function downloadCalendarFile(input: CalendarDownloadInput): boolean {
  const calendarFile = buildCalendarFile(input);
  if (!calendarFile) return false;

  const blob = new Blob([calendarFile], { type: 'text/calendar;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${sanitizeCalendarFilename(input.filename || input.title)}.ics`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  return true;
}
