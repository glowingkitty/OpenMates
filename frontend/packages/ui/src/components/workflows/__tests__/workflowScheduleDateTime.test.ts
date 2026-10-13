import { describe, expect, it } from 'vitest';
import { scheduleDateTimeInput, scheduleDateTimeInstant, scheduleDateTimeWithOffset } from '../workflowScheduleDateTime';

describe('workflow schedule date and time', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.schedule.preview
  it('shows UTC and offset-authored instants in the selected timezone', () => {
    expect(scheduleDateTimeInput('2026-11-02T08:30:00-05:00', 'Europe/Berlin')).toBe('2026-11-02T14:30');
    expect(scheduleDateTimeInput('2026-11-02T13:30:00Z', 'America/New_York')).toBe('2026-11-02T08:30');
    expect(scheduleDateTimeInput('2026-11-02T14:30:00', 'Europe/Berlin')).toBe('2026-11-02T14:30');
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.schedule.preview
  it('converts the selected wall time to an instant across daylight saving changes', () => {
    expect(scheduleDateTimeInstant('2026-11-02T14:30', 'Europe/Berlin')).toBe('2026-11-02T13:30:00.000Z');
    expect(scheduleDateTimeInstant('2026-10-18T00:00', 'Europe/Berlin')).toBe('2026-10-17T22:00:00.000Z');
    expect(scheduleDateTimeInstant('2026-07-02T14:30', 'Europe/Berlin')).toBe('2026-07-02T12:30:00.000Z');
    expect(scheduleDateTimeInstant('2026-03-29T02:30', 'Europe/Berlin')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.schedule.preview
  it('preserves seconds and microseconds when attaching the old timezone offset', () => {
    expect(scheduleDateTimeWithOffset('2026-10-18T09:00:00.000001', 'Europe/Berlin')).toBe('2026-10-18T09:00:00.000001+02:00');
    expect(scheduleDateTimeWithOffset('2026-11-02T09:00:59.123456', 'Europe/Berlin')).toBe('2026-11-02T09:00:59.123456+01:00');
    expect(Date.parse(scheduleDateTimeWithOffset('2026-10-18T09:00:00.000001', 'Europe/Berlin')!)).toBe(Date.parse('2026-10-18T07:00:00.000Z'));
  });
});
