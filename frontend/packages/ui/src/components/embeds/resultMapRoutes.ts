import type { MapPathPoint, MapRoutePath, MapMarker } from './embedMapTypes';

const MAX_TRAVEL_LEGS = 8;
const MAX_TRAVEL_SEGMENTS_PER_LEG = 32;
const firstString = (...values: unknown[]): string => values.find((value): value is string => typeof value === 'string' && !!value.trim())?.trim() ?? '';
function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
}
function getNestedRecord(record: Record<string, unknown> | null | undefined, key: string): Record<string, unknown> | null {
  const value = record?.[key];
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function extractArrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item)) : [];
}

/** Shared route parsing used by the map view, search overview and connection previews. */
  function addRoutePoint(points: MapPathPoint[], lat: number | undefined, lon: number | undefined, label = ''): void {
    if (lat == null || lon == null) return;
    const lastPoint = points[points.length - 1];
    if (lastPoint && lastPoint.lat === lat && lastPoint.lon === lon) {
      if (!lastPoint.label && label) lastPoint.label = label;
      return;
    }
    points.push({ lat, lon, ...(label ? { label } : {}) });
  }

  function travelLocationLabels(content: Record<string, unknown> | null): Map<string, string> {
    const labels = new Map<string, string>();
    const addLabel = (codeValue: unknown, nameValue: unknown) => {
      const code = firstString(codeValue);
      const name = firstString(nameValue);
      if (!code || !name) return;
      labels.set(code, name.includes(code) ? name : `${name} (${code})`);
    };
    for (const leg of extractArrayRecords(content?.legs)) {
      for (const layover of extractArrayRecords(leg.layovers)) {
        addLabel(layover.airport_code ?? layover.station_code ?? layover.code, layover.airport ?? layover.station ?? layover.name);
      }
    }
    if (!content) return labels;
    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let layoverIndex = 0; layoverIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; layoverIndex += 1) {
        const prefix = `legs_${legIndex}_layovers_${layoverIndex}`;
        const code = content[`${prefix}_airport_code`] ?? content[`${prefix}_station_code`] ?? content[`${prefix}_code`];
        const name = content[`${prefix}_airport`] ?? content[`${prefix}_station`] ?? content[`${prefix}_name`];
        if (code == null && name == null) {
          if (layoverIndex === 0) break;
          continue;
        }
        addLabel(code, name);
      }
    }
    return labels;
  }

  function extractRouteFromSegmentRecords(segments: unknown[], locationLabels: Map<string, string>): MapPathPoint[] {
    const points: MapPathPoint[] = [];
    for (const segment of segments) {
      if (!segment || typeof segment !== 'object' || Array.isArray(segment)) continue;
      const record = segment as Record<string, unknown>;
      addRoutePoint(
        points,
        firstNumber(record.departure_latitude, record.departure_lat),
        firstNumber(record.departure_longitude, record.departure_lng, record.departure_lon),
        locationLabels.get(firstString(record.departure_station)) ?? firstString(record.departure_station),
      );
      addRoutePoint(
        points,
        firstNumber(record.arrival_latitude, record.arrival_lat),
        firstNumber(record.arrival_longitude, record.arrival_lng, record.arrival_lon),
        locationLabels.get(firstString(record.arrival_station)) ?? firstString(record.arrival_station),
      );
    }
    return points;
  }

  function extractRouteFromStructuredTravelLegs(content: Record<string, unknown> | null): MapPathPoint[] {
    if (!Array.isArray(content?.legs)) return [];
    const segments = content.legs.flatMap((leg) => {
      if (!leg || typeof leg !== 'object' || Array.isArray(leg)) return [];
      const legRecord = leg as Record<string, unknown>;
      return Array.isArray(legRecord.segments) ? legRecord.segments : [];
    });
    return extractRouteFromSegmentRecords(segments, travelLocationLabels(content));
  }

  function extractRouteFromFlatTravelSegments(content: Record<string, unknown> | null): MapPathPoint[] {
    if (!content) return [];
    const segments: Record<string, unknown>[] = [];

    for (let legIndex = 0; legIndex < MAX_TRAVEL_LEGS; legIndex += 1) {
      for (let segmentIndex = 0; segmentIndex < MAX_TRAVEL_SEGMENTS_PER_LEG; segmentIndex += 1) {
        const prefix = `legs_${legIndex}_segments_${segmentIndex}`;
        const record = {
          departure_station: content[`${prefix}_departure_station`],
          departure_latitude: content[`${prefix}_departure_latitude`],
          departure_longitude: content[`${prefix}_departure_longitude`],
          arrival_station: content[`${prefix}_arrival_station`],
          arrival_latitude: content[`${prefix}_arrival_latitude`],
          arrival_longitude: content[`${prefix}_arrival_longitude`],
        };
        const hasSegmentData = Object.values(record).some((value) => value != null);
        if (!hasSegmentData) {
          if (segmentIndex === 0) break;
          continue;
        }
        segments.push(record);
      }
    }

    return extractRouteFromSegmentRecords(segments, travelLocationLabels(content));
  }

  function extractRouteFromFlightTrack(content: Record<string, unknown> | null): MapPathPoint[] {
    const flightTrack = getNestedRecord(content, 'flight_track');
    const tracks = flightTrack?.tracks;
    if (!Array.isArray(tracks)) return [];
    return tracks
      .map((point) => {
        if (!point || typeof point !== 'object' || Array.isArray(point)) return null;
        const record = point as Record<string, unknown>;
        const lat = firstNumber(record.lat, record.latitude);
        const lon = firstNumber(record.lon, record.lng, record.longitude);
        return lat != null && lon != null ? { lat, lon } : null;
      })
      .filter((point): point is MapPathPoint => point != null);
  }

  export function extractResultRoute(content: Record<string, unknown> | null): MapPathPoint[] {
    const routeValue = content?.route_points || content?.route || content?.path || content?.polyline_points;
    if (Array.isArray(routeValue)) {
      return routeValue
        .map((point) => {
          if (!point || typeof point !== 'object') return null;
          const record = point as Record<string, unknown>;
          const lat = firstNumber(record.lat, record.latitude);
          const lon = firstNumber(record.lon, record.lng, record.longitude);
          const label = firstString(record.label, record.name, record.station, record.city);
          return lat != null && lon != null ? { lat, lon, ...(label ? { label } : {}) } : null;
        })
        .filter((point): point is MapPathPoint => point != null);
    }

    const structuredTravelRoute = extractRouteFromStructuredTravelLegs(content);
    if (structuredTravelRoute.length > 1) return structuredTravelRoute;

    const flatTravelRoute = extractRouteFromFlatTravelSegments(content);
    if (flatTravelRoute.length > 1) return flatTravelRoute;

    const flightTrackRoute = extractRouteFromFlightTrack(content);
    if (flightTrackRoute.length > 1) return flightTrackRoute;

    const origin = getNestedRecord(content, 'origin');
    const destination = getNestedRecord(content, 'destination');
    const originLat = firstNumber(content?.origin_lat, content?.origin_latitude, origin?.lat, origin?.latitude);
    const originLon = firstNumber(content?.origin_lon, content?.origin_lng, content?.origin_longitude, origin?.lon, origin?.lng, origin?.longitude);
    const destinationLat = firstNumber(content?.destination_lat, content?.destination_latitude, destination?.lat, destination?.latitude);
    const destinationLon = firstNumber(content?.destination_lon, content?.destination_lng, content?.destination_longitude, destination?.lon, destination?.lng, destination?.longitude);
    if (originLat != null && originLon != null && destinationLat != null && destinationLon != null) {
      return [
        { lat: originLat, lon: originLon, ...(firstString(content?.origin_name, content?.origin) ? { label: firstString(content?.origin_name, content?.origin) } : {}) },
        { lat: destinationLat, lon: destinationLon, ...(firstString(content?.destination_name, content?.destination) ? { label: firstString(content?.destination_name, content?.destination) } : {}) },
      ];
    }
    return [];
  }


/** Shared map-view route styling. Changing active refs never refits route geometry. */
export function buildResultRoutePaths(
  entries: Array<{ref: string; route?: MapPathPoint[] | null}>,
  activeRefs: ReadonlySet<string> = new Set(),
  testId = 'search-result-route-path',
): MapRoutePath[] {
  return entries.filter(entry => entry.route && entry.route.length > 1).map(entry => ({
    points: entry.route!, ref: entry.ref, testId,
    color: activeRefs.size === 0 ? 'var(--color-app-travel-start)' : activeRefs.has(entry.ref) ? 'var(--color-app-travel-end)' : 'var(--color-grey-50)',
    weight: 5, opacity: activeRefs.size > 0 && !activeRefs.has(entry.ref) ? 0.5 : 0.8, dashArray: '10 10',
  }));
}

export interface ResultMapEntry {
  ref: string;
  title: string;
  color: string;
  lat?: number | null;
  lon?: number | null;
  route?: MapPathPoint[] | null;
  homeGeometry?: MapMarker | null;
  homeLabel?: string;
}

  function markerCoordinateKey(point: MapPathPoint): string {
    return `${point.lat.toFixed(6)}:${point.lon.toFixed(6)}`;
  }

  export function buildResultMapMarkers(sourceEntries: ResultMapEntry[], activeRefs: ReadonlySet<string> = new Set(), selectedMarkerKey: string | null = null, testIdPrefix = 'embeds-map-view'): MapMarker[] {
    const homeMarkers: MapMarker[] = [];
    const markers = new Map<string, {
      point: MapPathPoint;
      role: 'endpoint-start' | 'endpoint-end' | 'stop' | 'location';
      ref: string;
      refs: Set<string>;
      label: string;
      color: string;
    }>();

    const addMarker = (
      entry: ResultMapEntry,
      point: MapPathPoint,
      role: 'endpoint-start' | 'endpoint-end' | 'stop' | 'location',
      label: string,
    ) => {
      const key = markerCoordinateKey(point);
      const existing = markers.get(key);
      if (!existing) {
        markers.set(key, { point, role, ref: entry.ref, refs: new Set([entry.ref]), label, color: entry.color });
        return;
      }
      existing.refs.add(entry.ref);
      if (role.startsWith('endpoint-') && existing.role === 'stop') {
        existing.role = role;
        existing.ref = entry.ref;
        existing.label = label;
      }
    };

    for (const entry of sourceEntries) {
      if (entry.homeGeometry) {
        const geometry = entry.homeGeometry;
        const key = `home:${entry.ref}:${geometry.lat}:${geometry.lon}:${geometry.radiusM ?? 0}`;
        const isActive = activeRefs.has(entry.ref);
        homeMarkers.push({...geometry, homeLocation: true, ref: entry.ref, relatedRefs: [entry.ref], selectionKey: key,
          selected: selectedMarkerKey === key, color: entry.color, opacity: activeRefs.size > 0 && !isActive ? 0.5 : 1,
          testId: geometry.radiusM ? 'home-location-area' : 'home-location-pin', label: entry.homeLabel ?? entry.title});
        continue;
      }
      if (entry.route && entry.route.length > 1) {
        entry.route.forEach((point, index) => {
          const isEndpoint = index === 0 || index === entry.route!.length - 1;
          addMarker(
            entry,
            point,
            isEndpoint ? (index === 0 ? 'endpoint-start' : 'endpoint-end') : 'stop',
            point.label || `${entry.title} ${isEndpoint ? (index === 0 ? 'start' : 'end') : 'stop'}`,
          );
        });
      } else if (entry.lat != null && entry.lon != null) {
        addMarker(entry, { lat: entry.lat, lon: entry.lon }, 'location', entry.title);
      }
    }

    return [...homeMarkers, ...Array.from(markers.values()).map((marker) => {
      const key = markerCoordinateKey(marker.point);
      const relatedRefs = Array.from(marker.refs);
      const isActive = relatedRefs.some((ref) => activeRefs.has(ref));
      return {
        lat: marker.point.lat,
        lon: marker.point.lon,
        label: marker.label,
        color: marker.color,
        ref: isActive ? relatedRefs.find((ref) => activeRefs.has(ref)) ?? marker.ref : marker.ref,
        relatedRefs,
        selectionKey: key,
        selected: selectedMarkerKey === key,
        testId: marker.role === 'stop' ? `${testIdPrefix}-stop-marker` : `${testIdPrefix}-endpoint-marker`,
        iconClass: `embeds-map-view-marker embeds-map-view-marker-${marker.role}${isActive ? ' embeds-map-view-marker-active' : ''}${selectedMarkerKey === key ? ' embeds-map-view-marker-selected' : ''}`,
        opacity: activeRefs.size > 0 && !isActive ? 0.5 : 1,
      };
    })];
  }

