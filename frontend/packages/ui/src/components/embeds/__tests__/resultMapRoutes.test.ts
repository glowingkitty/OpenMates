import { describe, expect, it } from 'vitest';
import { buildResultMapMarkers, buildResultRoutePaths, extractResultRoute } from '../resultMapRoutes';

describe('shared result route geometry', () => {
  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  it('prefers explicit routes and rejects incomplete coordinates', () => {
    expect(extractResultRoute({ route_points: [
      { latitude: '48.1', longitude: '11.5', name: 'Munich' },
      { lat: 50.1, lng: 8.6, station: 'Frankfurt' }, { lat: 42 },
    ], origin_lat: 1, origin_lon: 2, destination_lat: 3, destination_lon: 4 })).toEqual([
      { lat: 48.1, lon: 11.5, label: 'Munich' }, { lat: 50.1, lon: 8.6, label: 'Frankfurt' },
    ]);
    expect(extractResultRoute({ origin_lat: 1, origin_lon: 2, destination_lat: 3 })).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  it('joins structured and flattened segments without repeating interchange points', () => {
    const segments = [
      { departure_station: 'MUC', departure_latitude: 48, departure_longitude: 11, arrival_station: 'FRA', arrival_latitude: 50, arrival_longitude: 8 },
      { departure_station: 'FRA', departure_latitude: 50, departure_longitude: 8, arrival_station: 'BER', arrival_latitude: 52, arrival_longitude: 13 },
    ];
    const structured = extractResultRoute({ legs: [{ segments, layovers: [{ station_code: 'FRA', station: 'Frankfurt' }] }] });
    expect(structured).toEqual([{ lat: 48, lon: 11, label: 'MUC' }, { lat: 50, lon: 8, label: 'Frankfurt (FRA)' }, { lat: 52, lon: 13, label: 'BER' }]);
    const flattened = Object.fromEntries(segments.flatMap((segment, index) => Object.entries(segment).map(([key, value]) => [`legs_0_segments_${index}_${key}`, value])));
    expect(extractResultRoute(flattened).map(({lat, lon}) => ({lat, lon}))).toEqual(structured.map(({lat, lon}) => ({lat, lon})));
  });

  // contract-test: supporting surface=gui.web assertions=travel-search.surface-parity
  it('highlights shared stops and routes without changing route geometry', () => {
    const entries = [
      { ref: 'a', title: 'Direct', color: 'red', route: [{lat: 48, lon: 11}, {lat: 50, lon: 8}, {lat: 52, lon: 13}] },
      { ref: 'b', title: 'Via Cologne', color: 'red', route: [{lat: 48, lon: 11}, {lat: 51, lon: 7}, {lat: 52, lon: 13}] },
    ];
    const idle = buildResultRoutePaths(entries);
    const active = buildResultRoutePaths(entries, new Set(['b']));
    expect(active.map(path => path.points)).toEqual(idle.map(path => path.points));
    expect(active[0].points).toBe(entries[0].route);
    expect(active[0].opacity).toBeLessThan(active[1].opacity!);
    const markers = buildResultMapMarkers(entries, new Set(['b']));
    const shared = markers.find(marker => marker.lat === 48)!;
    expect(shared.relatedRefs).toEqual(['a', 'b']);
    expect(shared.ref).toBe('b');
    expect(markers.filter(marker => marker.testId?.endsWith('stop-marker'))).toHaveLength(2);
  });

  // contract-test: supporting surface=gui.web assertions=home-search.location.precision
  it('retains approximate home areas and omits missing geometry', () => {
    const markers = buildResultMapMarkers([
      { ref: 'home', title: 'Approximate location', color: 'red', homeGeometry: {lat: 48, lon: 11, radiusM: 600} },
      { ref: 'missing', title: 'Location unavailable', color: 'red' },
    ]);
    expect(markers).toHaveLength(1);
    expect(markers[0]).toMatchObject({radiusM: 600, testId: 'home-location-area', homeLocation: true});
  });
});
