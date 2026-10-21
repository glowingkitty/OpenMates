import type { MapMarker } from './EmbedLeafletMap.svelte';

/** Use real coordinates carried by typed location, event and travel previews. */
export function searchResultMapMarkers<T extends { embed_id: string }>(results: T[]): MapMarker[] {
  const markers: MapMarker[] = []; const seen = new Set<string>();
  for (const result of results) {
    const record = result as Record<string, unknown>;
    const label = typeof record.title === 'string' ? record.title : typeof record.name === 'string' ? record.name : undefined;
    const visit = (value: unknown, depth = 0): void => {
      if (!value || typeof value !== 'object' || depth > 6 || markers.length >= 60) return;
      if (Array.isArray(value)) { value.forEach(item => visit(item, depth + 1)); return; }
      const fields = value as Record<string, unknown>;
      for (const [lat, lon] of [[fields.latitude ?? fields.lat, fields.longitude ?? fields.lon ?? fields.lng], [fields.departure_latitude, fields.departure_longitude], [fields.arrival_latitude, fields.arrival_longitude], [fields.venue_lat, fields.venue_lon]]) {
        if (typeof lat !== 'number' || typeof lon !== 'number' || !Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
        const key = `${result.embed_id}:${lat}:${lon}`;
        if (!seen.has(key)) { seen.add(key); markers.push({ lat, lon, ref: result.embed_id, label }); }
      }
      Object.values(fields).forEach(item => { if (item && typeof item === 'object') visit(item, depth + 1); });
    };
    visit(record);
  }
  return markers;
}
