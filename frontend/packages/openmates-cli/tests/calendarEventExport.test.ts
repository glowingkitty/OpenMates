import { it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildCalendarEventFile } from '../../ui/src/utils/calendarDownload.ts';
import { calendarEventWeekEntries, formatCalendarEventDate, normalizeCalendarEventContent } from '../../ui/src/utils/calendarEvent.ts';
import { buildCalendarWeekDays, calendarWeeksWithEntries, layoutCalendarDay, weekStartOrdinal } from '../../public-site/src/components/results/calendarWeek.ts';

const vectors = JSON.parse(readFileSync(new URL('../../../../shared/test-fixtures/calendar-event-export.json', import.meta.url), 'utf8'));
for (const sample of vectors.valid) {
  // contract-test: supporting surface=sdks.npm assertions=calendar-event.export.primary-only,calendar-event.content.validated
  it(`exports primary-only calendar bytes: ${sample.id}`, () => {
    const file = buildCalendarEventFile(vectors.embed_id, sample.content);
    assert.ok(file);
    const unfolded = file.replace(/\r\n /g, '');
    assert.ok(unfolded.includes(sample.start_line + '\r\n'));
    assert.equal(sample.end_line ? unfolded.includes(sample.end_line + '\r\n') : !unfolded.includes('DTEND'), true);
    assert.equal((unfolded.match(/^BEGIN:VEVENT\r$/gm) ?? []).length, 1);
    assert.equal((unfolded.match(/^END:VEVENT\r$/gm) ?? []).length, 1);
    assert.ok(unfolded.includes(`UID:${vectors.embed_id}@openmates\r\n`));
    assert.ok(!unfolded.includes('Context only'));
    assert.ok(!/^ATTENDEE:|^BEGIN:VALARM|^METHOD:/m.test(unfolded));
    for (const line of file.split('\r\n')) assert.ok(Buffer.byteLength(line, 'utf8') <= 75);
    if (sample.id === 'unicode-and-injection') {
      assert.ok(unfolded.includes('Réunion\\; café\\, 東京 🚀'));
      assert.ok(unfolded.includes('\\nBEGIN:VEVENT\\nATTENDEE:'));
      assert.ok(unfolded.includes('URL:https://example.org/event?tags=a,b'));
    }
  });
}
for (const sample of vectors.invalid) {
  // contract-test: supporting surface=sdks.npm assertions=calendar-event.export.primary-only,calendar-event.content.validated
  it(`rejects unavailable export: ${sample.id}`, () => {
    assert.equal(buildCalendarEventFile(vectors.embed_id, sample.content), null);
  });
}

// contract-test: supporting surface=cli assertions=calendar-event.export.primary-only,calendar-event.streaming.saved-lifecycle
it('does not export processing, failed, or cancelled primary events', () => {
  for (const status of ['processing', 'error', 'cancelled']) {
    assert.equal(buildCalendarEventFile(vectors.embed_id, { ...vectors.valid[0].content, status }), null);
  }
});

// contract-test: supporting surface=gui.web assertions=calendar-event.preview.context-highlight,calendar-event.preview.shared-week-layout
it('shares real overlap positions and preserves all-day continuation into another week', () => {
  const document = normalizeCalendarEventContent({ openmatesType: 'calendar_event', schemaVersion: 1,
    primary_event: { title: 'Workshop', start: '2027-03-15T10:00:00+01:00', end: '2027-03-15T12:00:00+01:00' },
    context_events: [{ title: 'Meeting', start: '2027-03-15T10:30:00Z', end: '2027-03-15T11:00:00Z' }] });
  assert.ok(document);
  const entries = calendarEventWeekEntries(document, vectors.embed_id);
  assert.equal(entries[0].startMinutes, 600);
  assert.equal(entries[1].startMinutes, 690);
  const day = layoutCalendarDay(entries);
  assert.equal(day[0].columnCount, 2);
  assert.equal(day[1].columnCount, 2);
  assert.equal(day[0].highlighted, true);
  assert.equal(day[1].contextual, true);
  const first = new Date('2027-01-31T00:00:00Z').getTime() / 86_400_000;
  const span = [{ ref: 'conference', title: 'Conference', dateOrdinal: first, startMinutes: 0, endDateOrdinal: first + 2, dateOnly: true }];
  assert.equal(calendarWeeksWithEntries(span).length, 2);
  assert.equal(buildCalendarWeekDays(weekStartOrdinal(first), span)[6].entries.length, 1);
  assert.equal(buildCalendarWeekDays(weekStartOrdinal(first) + 7, span)[0].entries.length, 1);
  assert.equal(buildCalendarWeekDays(weekStartOrdinal(first) + 7, span)[1].entries.length, 0);
});

// contract-test: supporting surface=gui.web assertions=calendar-event.content.validated
it('formats all-day dates without viewer timezone shifts and disambiguates DST offsets', () => {
  const before = process.env.TZ;
  try {
    process.env.TZ = 'America/Los_Angeles';
    const text = formatCalendarEventDate(vectors.valid[0].content.primary_event, 'en-US');
    assert.match(text, /Jan 30, 2027.*Jan 31, 2027/);
    const compact = formatCalendarEventDate(vectors.valid[0].content.primary_event, 'en-US', true);
    assert.match(compact, /Jan 30.*31, 2027/);
    assert.equal(compact.match(/2027/g)?.length, 1);
    const dst = formatCalendarEventDate(vectors.valid[4].content.primary_event, 'en-US');
    assert.match(dst, /GMT\+2.*GMT\+1/);
    assert.match(formatCalendarEventDate(vectors.valid[4].content.primary_event, 'en-US', true), /GMT\+2.*GMT\+1/);
  } finally { if (before == null) delete process.env.TZ; else process.env.TZ = before; }
});
