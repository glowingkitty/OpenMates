import { describe, expect, it } from 'vitest';
import { buildResultMapMarkers, buildResultRoutePaths, extractResultRoute, isResultRouteSchematic, compatibleResultPriceCurrency } from '../resultMapRoutes';

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

// contract-test: supporting surface=gui.web assertions=authored-results.maps.source-faithful-geometry
describe('authored map geometry', () => {
  it('uses supplied GeoJSON rather than a schematic endpoint connector', () => {
    const content = {geometry: {type: 'LineString', coordinates: [[11, 48], [12, 49], [13, 52]]}, origin_lat: 1, origin_lon: 2, destination_lat: 3, destination_lon: 4};
    expect(extractResultRoute(content)).toEqual([{lat:48,lon:11},{lat:49,lon:12},{lat:52,lon:13}]);
    expect(isResultRouteSchematic(content)).toBe(false);
    expect(buildResultRoutePaths([{ref:'track',route:extractResultRoute(content),routeSchematic:false}])[0].dashArray).toBeUndefined();
    expect(buildResultMapMarkers([{ref:'track',title:'Actual track',color:'red',route:extractResultRoute(content),routeSchematic:false}])).toHaveLength(2);
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.maps.source-faithful-geometry,authored-results.facts.provenance-and-drafts
  it('prefers an actual authored flight track to segment endpoint joins', () => {
    const content = {authoring:{kind:'travel.connection'}, flight_track:{tracks:[{lat:48,lon:11},{lat:49,lon:12},{lat:52,lon:13}]}, legs:[{segments:[{departure_lat:1,departure_lon:2,arrival_lat:3,arrival_lon:4}]}]};
    expect(extractResultRoute(content)).toEqual([{lat:48,lon:11},{lat:49,lon:12},{lat:52,lon:13}]);
    expect(isResultRouteSchematic(content)).toBe(false);
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.maps.source-faithful-geometry,authored-results.facts.provenance-and-drafts
  it('keeps two supplied endpoints schematic and rejects invalid GeoJSON', () => {
    const content = {origin:{lat:48,lon:11},destination:{lat:52,lon:13}};
    expect(extractResultRoute(content)).toHaveLength(2);
    expect(isResultRouteSchematic(content)).toBe(true);
    expect(buildResultRoutePaths([{ref:'connector',route:extractResultRoute(content),routeSchematic:true}])[0].dashArray).toBe('10 10');
    expect(extractResultRoute({geometry:{type:'LineString',coordinates:[[181,48],[13,52]]}})).toEqual([]);
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.maps.source-faithful-geometry,authored-results.facts.provenance-and-drafts
  it('does not turn an approximate area or unmapped cards into exact pins', () => {
    const entries = [
      {ref:'connector',title:'Route',color:'red',route:[{lat:48,lon:11},{lat:52,lon:13}]},
      {ref:'home',title:'Area',color:'red',homeGeometry:{lat:50,lon:12,radiusM:500}},
      {ref:'online',title:'Online appointment',color:'red'},
      {ref:'tv',title:'Series',color:'red'},
    ];
    const markers = buildResultMapMarkers(entries,new Set(['connector']));
    expect(markers).toHaveLength(3);
    expect(markers.find(marker=>marker.ref==='home')).toMatchObject({radiusM:500,testId:'home-location-area'});
    expect(markers.flatMap(marker=>marker.relatedRefs)).not.toContain('online');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.maps.source-faithful-geometry,authored-results.facts.provenance-and-drafts
  it('requires compatible known currencies for price comparisons and preserves zero', () => {
    expect(compatibleResultPriceCurrency([{price:0,currency:'USD'},{price:5,currency:'usd'}])).toBe('USD');
    expect(compatibleResultPriceCurrency([{price:0},{price:5,currency:'USD'}])).toBeUndefined();
    expect(compatibleResultPriceCurrency([{price:1,currency:'EUR'},{price:5,currency:'USD'}])).toBeUndefined();
  });
});
