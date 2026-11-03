import { describe, expect, it } from 'vitest';
import { healthAppointmentName, healthAppointmentSlot } from './healthAppointmentData';

describe('supplied appointment presentation', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('preserves supplied clinician aliases without inventing a name', () => {
    expect(healthAppointmentName({doctor_name: 'Dr Example'})).toBe('Dr Example');
    expect(healthAppointmentName({name: 'Practice', doctor_name: 'Dr Example'})).toBe('Practice');
    expect(healthAppointmentName({practice_name: 'Supplied practice'})).toBe('Supplied practice');
    expect(healthAppointmentName({})).toBeUndefined();
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('uses the supplied IANA timezone across a UTC day boundary in both date and time', () => {
    const slot = healthAppointmentSlot('2027-01-31T23:30:00Z', 'Asia/Tokyo', 'en-US');
    expect(slot).toMatchObject({date: '2027-01-31T23:30:00Z', timezone: 'Asia/Tokyo', timeLabel: '8:30 AM'});
    expect(slot.label).toContain('Feb 1, 2027');
    expect(slot.label).toContain('Asia/Tokyo');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('keeps a supplied offset wall date and time when no IANA timezone is supplied', () => {
    const slot = healthAppointmentSlot('2027-01-31T23:30:00-05:00', undefined, 'en-US');
    expect(slot).toMatchObject({date: '2027-01-31', timezone: 'UTC', timeLabel: '11:30 PM UTC-05:00'});
    expect(slot.label).toContain('Jan 31, 2027');
    expect(healthAppointmentSlot('2027-01-31T23:30:00-05:00', 'Invalid/Zone', 'en-US').timeLabel).toBe('11:30 PM UTC-05:00');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('keeps absent or invalid dates unavailable and never creates an end time', () => {
    expect(healthAppointmentSlot(undefined)).toEqual({timeLabel: '', label: ''});
    expect(healthAppointmentSlot('invalid')).toEqual({timeLabel: '', label: 'invalid'});
    expect(healthAppointmentSlot('2027-01-31T23:30:00Z')).not.toHaveProperty('end');
  });
});
