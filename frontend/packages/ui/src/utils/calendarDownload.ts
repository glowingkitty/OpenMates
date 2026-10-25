/*
 * frontend/packages/ui/src/utils/calendarDownload.ts
 *
 * Small browser-side helper for generating iCalendar (.ics) files.
 * Used by fullscreen embeds that represent scheduled real-world items.
 * Keeps download mechanics and ICS escaping consistent across embeds.
 *
 * See docs/architecture/embeds.md
 */

import { normalizeCalendarEvent, normalizeCalendarEventContent } from './calendarEvent';

export interface CalendarDownloadInput {
  title: string;
  start: string;
  end?: string;
  location?: string;
  description?: string;
  url?: string;
  filename?: string;
  timezone?: string;
  /** Stable artifact identity, rather than title/date coincidence. */
  uid?: string;
  /** Calendar content artifacts preserve unknown ends and reject invalid dates. */
  strict?: boolean;
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
    .replace(/\r\n?|\n/g, '\\n')
    // eslint-disable-next-line no-control-regex -- RFC text cannot contain raw controls.
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '');
}

function foldIcsLine(line: string): string {
  const chunks: string[] = [];
  let current = '';
  let length = 0;
  const encoder = new TextEncoder();
  for (const character of line) {
    const bytes = encoder.encode(character).length;
    if (length + bytes > 75) { chunks.push(current); current = ' '; length = 1; }
    current += character;
    length += bytes;
  }
  chunks.push(current);
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
  if (input.strict && !normalizeCalendarEvent({ ...input, source_url: input.url })) return null;
  const start = parseCalendarDate(input.start);
  if (!start) return null;

  const parsedEnd = parseCalendarDate(input.end);
  // A date without a time represents an all-day entry, not midnight UTC.
  // iCalendar DTEND is exclusive, so a single day ends on the following date.
  const allDay = DATE_ONLY_PATTERN.test(input.start);
  const end = parsedEnd && parsedEnd.getTime() > start.getTime()
    ? parsedEnd
    : !allDay && input.strict ? null
    : new Date(start.getTime() + (allDay ? ALL_DAY_DURATION_MS : DEFAULT_EVENT_DURATION_MS));
  const now = new Date();
  const uid = input.uid || `${start.getTime()}-${sanitizeCalendarFilename(input.title)}@openmates`;

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//OpenMates//Embeds//EN',
    'CALSCALE:GREGORIAN',
    ...(!input.strict ? ['METHOD:PUBLISH'] : []),
    'BEGIN:VEVENT',
    `UID:${escapeIcsText(uid)}`,
    `DTSTAMP:${formatUtcDate(now)}`,
    allDay ? `DTSTART;VALUE=DATE:${formatUtcDate(start).slice(0, 8)}` : `DTSTART:${formatUtcDate(start)}`,
    ...(end ? [allDay ? `DTEND;VALUE=DATE:${formatUtcDate(end).slice(0, 8)}` : `DTEND:${formatUtcDate(end)}`] : []),
    `SUMMARY:${escapeIcsText(input.title || 'Calendar event')}`,
  ];

  if (input.location) lines.push(`LOCATION:${escapeIcsText(input.location)}`);
  if (input.description) lines.push(`DESCRIPTION:${escapeIcsText(input.description)}`);
  if (input.url) lines.push(`URL:${input.strict ? input.url : escapeIcsText(input.url)}`);

  lines.push('END:VEVENT', 'END:VCALENDAR');
  return `${lines.map(foldIcsLine).join('\r\n')}\r\n`;
}

export function downloadCalendarFile(input: CalendarDownloadInput): boolean {
  const calendarFile = buildCalendarFile(input);
  if (!calendarFile) return false;

  try {
    const blob = new Blob([calendarFile], { type: 'text/calendar;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${sanitizeCalendarFilename(input.filename || input.title)}.ics`;
    document.body.appendChild(link);
    try { link.click(); }
    finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 0); }
    return true;
  } catch { return false; }
}

function calendarEventInput(embedId: string, content: unknown): CalendarDownloadInput | null {
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(embedId)) return null;
  if (content && typeof content === 'object' && 'status' in content && content.status !== 'finished') return null;
  const document = normalizeCalendarEventContent(content);
  if (!document) return null;
  const event = document.primary_event;
  return { ...event, url: event.source_url, uid: `${embedId}@openmates`, strict: true };
}

/** Same primary-only bytes for browser controls, CLI downloads and the npm SDK. */
export function buildCalendarEventFile(embedId: string, content: unknown): string | null {
  const input = calendarEventInput(embedId, content);
  return input ? buildCalendarFile(input) : null;
}

export function downloadCalendarEventFile(embedId: string, content: unknown): boolean {
  const input = calendarEventInput(embedId, content);
  return input ? downloadCalendarFile(input) : false;
}
