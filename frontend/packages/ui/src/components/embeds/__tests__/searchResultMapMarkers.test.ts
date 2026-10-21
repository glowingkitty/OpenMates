import { describe, expect, it } from 'vitest';
import { searchResultMapMarkers } from '../searchResultMapMarkers';
describe('real result header map coordinates', () => {
  // contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen
  it('uses venue and travel segment coordinates already carried by typed children', () => {
    const results = [{ embed_id: 'event', venue: { lat: 52, lon: 13 } }, { embed_id: 'flight', legs: [{ segments: [{ departure_latitude: 52, departure_longitude: 13, arrival_latitude: 14, arrival_longitude: 100 }] }] }];
    expect(searchResultMapMarkers(results)).toEqual([
      { ref: 'event', lat: 52, lon: 13, label: undefined }, { ref: 'flight', lat: 52, lon: 13, label: undefined }, { ref: 'flight', lat: 14, lon: 100, label: undefined },
    ]);
  });
  // contract-test: direct surface=gui.web assertions=apps.results.shared-fullscreen
  it('ignores missing or invalid coordinates and deduplicates repeated real points', () => {
    expect(searchResultMapMarkers([{ embed_id: 'x', location: { lat: 100, lon: 200 } }])).toEqual([]);
    expect(searchResultMapMarkers([{ embed_id: 'x', lat: 52, lon: 13, location: { lat: 52, lon: 13 } }])).toHaveLength(1);
  });
});
