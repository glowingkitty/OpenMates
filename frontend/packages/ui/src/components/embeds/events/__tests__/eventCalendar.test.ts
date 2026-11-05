import { describe, expect, it } from 'vitest';
import { buildEventResultCalendarFile, eventCalendarInput } from '../eventCalendar';
import { normalizeEventResult } from '../eventResult';
import { buildCalendarEventFile, buildCalendarFile } from '../../../../utils/calendarDownload';

const event = (details: Record<string, unknown>) => normalizeEventResult({ title: 'Supplied event', ...details }, 'event-actual-id');
const unfold = (value: string) => value.replace(/\r\n[ \t]/g, '');

describe('event result explicit local calendar export', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.actions.truthful-and-explicit
  it.each([
    ['2027-01-30', undefined, '20270131'],
    ['2027-01-30', '2027-01-30', '20270131'],
    ['2027-01-30', '2027-01-31', '20270201'],
    ['2028-02-29', '2028-02-29', '20280301'],
    ['2027-12-31', undefined, '20280101'],
  ])('exports supplied all-day %s–%s with an exclusive DTEND', (start, end, exclusive) => {
    const source = event({ date_start: start, date_end: end, timezone: 'Pacific/Honolulu' });
    const file = buildEventResultCalendarFile(source)!;
    expect(file).toContain(`DTSTART;VALUE=DATE:${start.replaceAll('-', '')}\r\n`);
    expect(file).toContain(`DTEND;VALUE=DATE:${exclusive}\r\n`);
    expect(file).not.toContain('DTSTART:');
    expect(file).not.toContain('TZID');
    expect(source.date_end).toBe(end);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.actions.truthful-and-explicit
  it('omits a timed unknown end and duration instead of manufacturing an hour', () => {
    const source = event({ date_start: '2027-03-15T23:30:00+09:00' });
    const file = buildEventResultCalendarFile(source)!;
    expect(file).toContain('DTSTART:20270315T143000Z\r\n');
    expect(file).not.toContain('DTEND');
    expect(file).not.toContain('DURATION');
    expect(eventCalendarInput(source)?.timezone).toBeUndefined();
    expect(source.date_end).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.actions.truthful-and-explicit
  it('uses the exact supplied timed end and supports a 500-character event title', () => {
    const source = event({ title: 'A'.repeat(500), date_start: '2027-03-15T23:30:00+09:00', date_end: '2027-03-16T01:00:00+09:00' });
    const file = unfold(buildEventResultCalendarFile(source)!);
    expect(file).toContain('DTEND:20270315T160000Z\r\n');
    expect(file).toContain('SUMMARY:' + source.title);
    expect(file).toContain('UID:event-actual-id@openmates');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.actions.truthful-and-explicit
  it.each([
    { date_start: '2027-02-30' },
    { date_start: '2027-03-15T10:00:00' },
    { date_start: '2027-03-15', date_end: '2027-03-14' },
    { date_start: '2027-03-15', date_end: '2027-03-15T10:00:00Z' },
    { date_start: '2027-03-15T10:00:00Z', date_end: '2027-03-15T10:00:00Z' },
    { date_start: '2027-03-15T10:00:00Z', date_end: '2027-03-15T09:00:00Z' },
    { date_start: '9999-12-31' },
    { date_start: '2027-03-15', status: 'processing' },
    { date_start: '2027-03-15', status: 'cancelled' },
    { date_start: '2027-03-15', status: 'error' },
    { date_start: '2027-03-15', title: '' },
    {},
  ])('does not offer an export for invalid or incomplete facts: %o', details => {
    expect(eventCalendarInput(event(details))).toBeNull();
    expect(buildEventResultCalendarFile(event(details))).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.actions.truthful-and-explicit
  it('escapes text, folds Unicode by UTF-8 bytes and emits only CRLF lines', () => {
    const source = event({ title: 'Conference, workshop; 東京\\\nSecond line', date_start: '2027-01-30',
      description: '新しい会議 '.repeat(40) + '\r\nEND:VEVENT', venue: { name: 'Hall; A, B\\C' },
      url: 'https://example.org/event?edition=1,2;type=public' });
    const file = buildEventResultCalendarFile(source)!;
    const full = unfold(file);
    expect(full).toContain('SUMMARY:Conference\\, workshop\\; 東京\\\\\\nSecond line\r\n');
    expect(full).toContain('LOCATION:Hall\\; A\\, B\\\\C\r\n');
    expect(full).toContain('\\nEND:VEVENT\r\n');
    expect(full).toContain('URL:https://example.org/event?edition=1,2;type=public\r\n');
    expect(file).not.toMatch(/(?<!\r)\n/);
    expect(full.match(/\r\nEND:VEVENT\r\n/g)).toHaveLength(1);
    for (const line of file.split('\r\n')) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit,calendar-event.privacy.explicit-local-export
  it('leaves calendar-artifact exclusive ends and other legacy caller defaults unchanged', () => {
    const artifact = buildCalendarEventFile('calendar-id', { openmatesType: 'calendar_event', schemaVersion: 1,
      primary_event: { title: 'Existing calendar artifact', start: '2027-01-30', end: '2027-01-31' } })!;
    expect(artifact).toContain('DTEND;VALUE=DATE:20270131\r\n');
    expect(artifact).not.toContain('DTEND;VALUE=DATE:20270201');
    const timed = buildCalendarEventFile('calendar-id', { openmatesType: 'calendar_event', schemaVersion: 1,
      primary_event: { title: 'Existing calendar artifact', start: '2027-01-30T10:00:00Z' } })!;
    expect(timed).not.toContain('DTEND');
    expect(timed).not.toContain('DURATION');
    expect(buildCalendarFile({ title: 'Other legacy caller', start: '2027-01-30T10:00:00Z' })).toContain('DTEND:20270130T110000Z');
  });
});
