import { getApiUrl } from '../../../config/api';
import { homeNumber, homeObject, type HomeMapGeometry } from './homeListingData';

/** Only send the advertised municipality, never the listing's street, to geocoding. */
export function homePreviewCity(city?: string, address?: string): string | undefined {
  if (city?.trim()) return city.trim().slice(0, 200);
  const last = address?.split(',').at(-1)?.trim().replace(/^\d{4,6}\s+/, '');
  if (!last || /\d|\b(street|road|avenue|lane)\b|str\.|(?:strasse|straße|allee|gasse|weg)$/i.test(last)) return undefined;
  return last.length <= 200 ? last : undefined;
}
const normalize = (value: unknown) => typeof value === 'string' ? value.normalize('NFKC').trim().toLocaleLowerCase() : '';
const distance = (a: {lat: number; lon: number}, b: {lat: number; lon: number}) => {
  const radians = Math.PI / 180;
  const h = Math.sin((b.lat - a.lat) * radians / 2) ** 2 + Math.cos(a.lat * radians) * Math.cos(b.lat * radians) * Math.sin((b.lon - a.lon) * radians / 2) ** 2;
  return 6371000 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
};
/** Bound a matching administrative municipality; a point alone never establishes an area. */
export function homeCityGeometry(results: unknown, city: string): HomeMapGeometry | undefined {
  if (!Array.isArray(results)) return undefined;
  const matches: HomeMapGeometry[] = [];
  for (const value of results) {
    const row = homeObject(value), address = homeObject(row.address);
    if (!['city', 'town', 'village', 'municipality'].includes(String(row.addresstype || row.type))) continue;
    if (![row.name, address.city, address.town, address.village, address.municipality].some(name => normalize(name) === normalize(city))) continue;
    if (!Array.isArray(row.boundingbox) || row.boundingbox.length !== 4) continue;
    const bounds = row.boundingbox.map(homeNumber);
    if (bounds.some(value => value === undefined)) continue;
    const [south, north, west, east] = bounds as number[];
    if (south < -90 || north > 90 || west < -180 || east > 180 || north <= south || east <= west || north - south > 30 || east - west > 60) continue;
    const center = {lat: (south + north) / 2, lon: (west + east) / 2};
    const radiusM = Math.ceil(Math.max(...[south, north].flatMap(lat => [west, east].map(lon => distance(center, {lat, lon})))));
    matches.push({...center, radiusM, areaBasis: 'city'});
  }
  const first = matches[0];
  // Ambiguous municipalities require more locality evidence, not an arbitrary match.
  return first && !matches.some(match => distance(first, match) > Math.max(first.radiusM!, match.radiusM!)) ? first : undefined;
}

// Cache only public city geometry, never listing addresses or listing data. Shared
// promises deduplicate a grid's requests; failed lookups are retriable on remount.
const cityLookups = new Map<string, Promise<HomeMapGeometry | undefined>>();
export function resolveHomePreviewCity(city: string): Promise<HomeMapGeometry | undefined> {
  const key = normalize(city);
  const existing = cityLookups.get(key);
  if (existing) return existing;
  const lookup = (async () => {
    try {
      const response = await fetch(`${getApiUrl()}/v1/geocode/search?q=${encodeURIComponent(city)}&limit=3&addressdetails=1`, {signal: AbortSignal.timeout(10000)});
      return response.ok ? homeCityGeometry(await response.json(), city) : undefined;
    } catch { return undefined; }
  })();
  cityLookups.set(key, lookup);
  void lookup.then(geometry => { if (!geometry) cityLookups.delete(key); });
  if (cityLookups.size > 64) cityLookups.delete(cityLookups.keys().next().value!);
  return lookup;
}
