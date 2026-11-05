import { describe, expect, it } from 'vitest';
import { buildCalendarFile } from '../../../utils/calendarDownload';
import { fitnessClassCalendarTiming } from './fitnessClassCalendar';

const file = (date: string, range: string | undefined, authored: boolean) => buildCalendarFile({title:'Supplied class',...fitnessClassCalendarTiming(date,range,authored)})!;

// contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit,authored-results.facts.provenance-and-drafts
describe('authored class and appointment calendar end precision', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit
  it('omits unsupplied timed class end and duration', () => {
    const value = file('2027-01-30','08:00',true);
    expect(value).toContain('DTSTART:');
    expect(value).not.toContain('DTEND');
    expect(value).not.toContain('DURATION');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit
  it('exports a date-only class as one calendar day without invented hours', () => {
    const value = file('2027-01-30',undefined,true);
    expect(value).toContain('DTSTART;VALUE=DATE:20270130\r\n');
    expect(value).toContain('DTEND;VALUE=DATE:20270131\r\n');
    expect(value).not.toContain('DTSTART:');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit
  it('preserves an explicitly supplied class time range', () => {
    const timing = fitnessClassCalendarTiming('2027-01-30','08:00–09:30',true);
    expect(timing).toMatchObject({start:'2027-01-30T08:00:00',end:'2027-01-30T09:30:00'});
    const value = buildCalendarFile({title:'Supplied class',...timing})!;
    const start = /DTSTART:(.+)\r\n/.exec(value)![1];
    const end = /DTEND:(.+)\r\n/.exec(value)![1];
    const instant = (stamp:string) => new Date(stamp.replace(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/, '$1-$2-$3T$4:$5:$6Z')).getTime();
    expect(instant(end)-instant(start)).toBe(90*60000);
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit
  it('retains the legacy duration fallback', () => {
    expect(file('2027-01-30','08:00',false)).toContain('DTEND:');
    expect(fitnessClassCalendarTiming('2027-01-30','08:00')).not.toHaveProperty('preserveUnknownEnd');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.actions.truthful-and-explicit
  it('does not assign a duration to an authored appointment slot', () => {
    const value = buildCalendarFile({title:'Supplied appointment',start:'2027-01-30T08:00:00+01:00',preserveUnknownEnd:true})!;
    expect(value).toContain('DTSTART:20270130T070000Z\r\n');
    expect(value).not.toContain('DTEND');
    expect(value).not.toContain('DURATION');
  });
});
