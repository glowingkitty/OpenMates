import { describe, expect, it } from 'vitest';
import { formatStationDate, formatStationDateTime, formatStationTime } from '../travelTime';

describe('station-local travel times (TASK-3927)', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful
  it('shows the wall-clock time of the station, not the viewer zone', () => {
    // A UTC test runner would have shown 05:43 with Date#toLocaleTimeString.
    expect(formatStationTime('2026-11-16T06:43:00+01:00', 'de-DE')).toBe('06:43');
    expect(formatStationTime('2026-07-01T23:59:00+02:00', 'de-DE')).toBe('23:59');
    expect(formatStationTime('2026-11-17T09:05:00Z', 'de-DE')).toBe('09:05');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful
  it('formats readable dates and date-times instead of raw ISO strings', () => {
    expect(formatStationDate('2026-11-16T20:52:00+01:00', 'en-US')).toBe('Mon, Nov 16');
    expect(formatStationDateTime('2026-11-16T20:52:00+01:00', 'en-GB')).toBe('Mon 16 Nov, 20:52');
    expect(formatStationDateTime('2026-11-16T20:52:00+01:00', 'en-GB')).not.toContain('T20');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful
  it('returns an empty string for missing or unreadable values', () => {
    expect(formatStationTime(undefined)).toBe('');
    expect(formatStationTime('tomorrow morning')).toBe('');
    expect(formatStationDateTime('')).toBe('');
  });
});
