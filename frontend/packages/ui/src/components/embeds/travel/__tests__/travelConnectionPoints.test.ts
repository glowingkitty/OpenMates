import { describe, expect, it } from 'vitest';
import { travelConnectionEndpoints, travelConnectionOverview, travelLegPresentation, travelPointLabel } from '../travelConnectionPoints';

describe('supplied travel connection points', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.maps.source-faithful-geometry
  it('keeps the complete supplied route independently of an incomplete leg and preserves source geometry', () => {
    const content = {
      origin: { name: 'Berlin Hbf (tief)', lat: 52.525, lon: 13.369 },
      destination: { name: 'Brussels Midi', lat: 50.836, lon: 4.336 },
      legs: [{ origin: 'Berlin Hbf', destination: 'Cologne Hbf', departure: '2027-01-29T07:00:00+01:00' }],
    };
    const before = structuredClone(content);
    expect(travelConnectionEndpoints(content)).toEqual({ origin: 'Berlin Hbf (tief)', destination: 'Brussels Midi' });
    expect(travelConnectionOverview(content)).toEqual({ origin: 'Berlin Hbf (tief)', destination: 'Brussels Midi', departure: undefined, arrival: undefined, duration: undefined });
    expect(travelLegPresentation(content.legs)).toEqual([{ ...content.legs[0], segments: [] }]);
    expect(content).toEqual(before);
    expect(travelLegPresentation(content.legs)?.[0]).not.toHaveProperty('arrival');
    expect(travelLegPresentation(content.legs)?.[0]).not.toHaveProperty('duration');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.content.typed-and-useful,authored-results.facts.provenance-and-drafts
  it('does not infer an authored final destination or any label from coordinates alone', () => {
    const content = { origin: { lat: 0, lon: 0 }, legs: [{ origin: 'Berlin Hbf', destination: 'Cologne Hbf' }] };
    expect(travelConnectionEndpoints(content)).toEqual({ origin: undefined, destination: undefined });
    expect(travelConnectionOverview(content)).toBeUndefined();
    for (const value of [undefined, null, 0, [], {}, { name: 42 }, { name: ' ' }]) {
      expect(travelPointLabel(value)).toBeUndefined();
    }
    expect(travelConnectionEndpoints(content, true)).toEqual({ origin: 'Berlin Hbf', destination: 'Cologne Hbf' });
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable
  it('preserves legacy string endpoints, supplied segment facts and unknown fields without changing stored content', () => {
    const segments = [{ carrier: 'Supplied railway', departure_station: 'Berlin Hbf' }];
    const content = { origin: 'Berlin Hbf', destination: 'Cologne Hbf', legs: [{ origin: { name: 'Berlin Hbf', lat: 0, lon: 0 }, segments, note: 'partial' }] };
    expect(travelConnectionEndpoints(content, true)).toEqual({ origin: 'Berlin Hbf', destination: 'Cologne Hbf' });
    expect(travelLegPresentation(content.legs)?.[0]).toEqual({ origin: 'Berlin Hbf', destination: undefined, segments, note: 'partial' });
    expect(content.legs[0].origin).toEqual({ name: 'Berlin Hbf', lat: 0, lon: 0 });
    expect(travelLegPresentation(undefined)).toBeUndefined();
    expect(travelLegPresentation([null, 'malformed'])).toEqual([]);
  });
});
