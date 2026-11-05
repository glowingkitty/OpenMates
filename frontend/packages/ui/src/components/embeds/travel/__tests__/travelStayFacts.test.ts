import { describe, expect, it } from 'vitest';
import { travelStayCoordinates, travelStayFacts, travelStayRate } from '../travelStayFacts';

describe('supplied stay facts', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('retains admitted object rates and date-only stays without inferring check-in times', () => {
    const content = { rate_per_night: { amount: 90 }, total_rate: { amount: 270 }, currency: 'EUR',
      check_in: '2027-01-29', check_out: '2027-02-01', booking_url: 'https://example.org/stay',
      coordinates: { lat: 50.85, lon: 4.35 } };
    const before = structuredClone(content);
    expect(travelStayFacts(content)).toEqual({ nightlyRate: { amount: 90, currency: 'EUR' },
      totalRate: { amount: 270, currency: 'EUR' }, checkIn: '2027-01-29', checkOut: '2027-02-01',
      sourceUrl: 'https://example.org/stay', coordinates: { latitude: 50.85, longitude: 4.35 } });
    expect(content).toEqual(before);
    expect(travelStayFacts(content)).not.toHaveProperty('check_in_time');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('keeps each supplied rate currency and explicit zero with no currency default', () => {
    const facts = travelStayFacts({ rate_per_night: { amount: 0, currency: 'USD' }, total_rate: { amount: 45, currency: 'EUR' } });
    expect(facts.nightlyRate).toEqual({ amount: 0, currency: 'USD' });
    expect(facts.totalRate).toEqual({ amount: 45, currency: 'EUR' });
    expect(travelStayRate({ amount: 12 })).toEqual({ amount: 12, currency: undefined });
    expect(travelStayFacts({ url: 'https://example.org/source' }).sourceUrl).toBe('https://example.org/source');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.maps.source-faithful-geometry
  it('does not convert blank, malformed or missing rates and coordinates into facts', () => {
    for (const value of [undefined, null, '', ' ', true, NaN, Infinity, -1, {}, { amount: '' }]) {
      expect(travelStayRate(value).amount).toBeUndefined();
    }
    expect(travelStayFacts({}).nightlyRate.currency).toBeUndefined();
    expect(travelStayCoordinates({ coordinates: { lat: 91, lon: 0 } })).toBeUndefined();
    expect(travelStayCoordinates({ coordinates: { lat: 10 }, gps_coordinates: { lon: 20 } })).toBeUndefined();
    expect(travelStayCoordinates({ coordinates: { lat: 0, lon: 0 } })).toEqual({ latitude: 0, longitude: 0 });
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable
  it('retains existing scalar rate and provider coordinate aliases', () => {
    expect(travelStayFacts({ extracted_rate_per_night: 50, extracted_total_rate: 100, currency: 'GBP',
      link: 'https://example.org/provider', gps_coordinates: { latitude: '52.5', longitude: '13.4' } })).toMatchObject({
      nightlyRate: { amount: 50, currency: 'GBP' }, totalRate: { amount: 100, currency: 'GBP' },
      coordinates: { latitude: 52.5, longitude: 13.4 }, sourceUrl: 'https://example.org/provider',
    });
    expect(travelStayRate('25.50', 'EUR')).toEqual({ amount: 25.5, currency: 'EUR' });
  });
});
