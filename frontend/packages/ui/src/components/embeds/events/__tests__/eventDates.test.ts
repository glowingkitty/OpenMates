import { describe, expect, it } from 'vitest';
import { eventCalendarBadge, formatEventResultDate, formatEventResultTime, eventResultSourceUrl } from '../eventResult';

// contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
describe('source-faithful event date presentation', () => {
  it('keeps an all-day date on its supplied day without a midnight time in any zone', () => {
    expect(formatEventResultDate('2027-01-30', 'Pacific/Honolulu', 'en-US')).toContain('Jan 30, 2027');
    expect(formatEventResultTime('2027-01-30', 'Pacific/Honolulu', 'en-US')).toBe('');
    expect(eventCalendarBadge('2027-01-30', 'Pacific/Honolulu')).toEqual({ date: '2027-01-30', timezone: 'UTC' });
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.actions.truthful-and-explicit
  it('uses a supplied numeric offset when no IANA timezone was provided', () => {
    expect(formatEventResultTime('2027-01-30T00:30:00+09:00', undefined, 'en-US')).toMatch(/12:30.*AM UTC\+09:00/);
    expect(formatEventResultDate('2027-01-30T00:30:00+09:00', undefined, 'en-US')).toContain('Jan 30, 2027');
    expect(eventCalendarBadge('2027-01-30T00:30:00+09:00')).toEqual({ date: '2027-01-30', timezone: 'UTC' });
    expect(formatEventResultTime('2027-01-30T00:30:00+09:00', 'Invalid/Zone', 'en-US')).toContain('UTC+09:00');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.actions.truthful-and-explicit
  it('retains an explicit IANA zone and does not fabricate unknown dates or times', () => {
    expect(formatEventResultTime('2027-01-30T09:00:00Z', 'Europe/Berlin', 'en-US')).toMatch(/10:00.*AM/);
    expect(eventCalendarBadge('2027-01-30T09:00:00Z', 'Europe/Berlin')).toEqual({ date: '2027-01-30T09:00:00Z', timezone: 'Europe/Berlin' });
    for (const value of [undefined, '', '2027-02-30', '2027-01-30T09:00:00']) {
      expect(formatEventResultDate(value, undefined, 'en-US')).toBe('');
      expect(formatEventResultTime(value, undefined, 'en-US')).toBe('');
      expect(eventCalendarBadge(value)).toEqual({});
    }
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.actions.truthful-and-explicit
  it('shows only supplied source links without manufacturing provider authority', () => {
    expect(eventResultSourceUrl('https://example.org/event')).toBe('https://example.org/event');
    for (const value of ['javascript:alert(1)', 'https://user:private@example.org/event', 'https://example.org/event\n', undefined])
      expect(eventResultSourceUrl(value)).toBeUndefined();
  });
});
