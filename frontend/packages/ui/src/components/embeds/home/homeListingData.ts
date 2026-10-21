/** Normalize rich home fields without turning missing evidence into false. */
export function homeNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) return undefined;
  const number = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(number) ? number : undefined;
}
export function homeObject(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') { try { return homeObject(JSON.parse(value)); } catch { return {}; } }
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
const HOME_AMENITIES = ['pets_allowed', 'balcony', 'terrace', 'garden', 'elevator', 'furnished', 'parking'];
const HOME_NEIGHBORHOOD_CATEGORIES = ['water', 'park', 'transit', 'groceries', 'school'];

/** Rebuild only schema-defined TOON paths; underscores inside field names are significant. */
export function homeListingContent(value: unknown): Record<string, unknown> {
  const raw = homeObject(value);
  const listing = { ...raw };
  for (const namespace of ['amenities', 'location', 'match_evidence', 'visual_assessment', 'neighborhood']) {
    const rebuilt = { ...homeObject(raw[namespace]) };
    for (const [key, field] of Object.entries(raw)) {
      if (!key.startsWith(`${namespace}_`)) continue;
      const suffix = key.slice(namespace.length + 1);
      const groups = namespace === 'match_evidence' ? { amenities: HOME_AMENITIES }
        : namespace === 'visual_assessment' ? { features: HOME_AMENITIES }
        : namespace === 'neighborhood' ? { features: HOME_NEIGHBORHOOD_CATEGORIES, coverage: HOME_NEIGHBORHOOD_CATEGORIES } : {};
      let assigned = false;
      for (const [group, children] of Object.entries(groups)) {
        for (const child of children) {
          const path = `${group}_${child}`;
          if (suffix !== path && !suffix.startsWith(`${path}_`)) continue;
          const collection = { ...homeObject(rebuilt[group]) };
          if (suffix === path) collection[child] = field;
          else collection[child] = { ...homeObject(collection[child]), [suffix.slice(path.length + 1)]: field };
          rebuilt[group] = collection;
          assigned = true;
          break;
        }
        if (assigned) break;
      }
      if (!assigned) rebuilt[suffix] = field;
    }
    // Normalize nested JSON and flattened JSON with the same semantics.
    for (const group of namespace === 'match_evidence' ? ['amenities'] : namespace === 'visual_assessment' ? ['features'] : namespace === 'neighborhood' ? ['features', 'coverage'] : []) {
      const collection = { ...homeObject(rebuilt[group]) };
      for (const [key, child] of Object.entries(collection)) {
        if (namespace === 'neighborhood' && group === 'features') {
          let places = child;
          if (typeof places === 'string') { try { places = JSON.parse(places); } catch { places = []; } }
          collection[key] = Array.isArray(places) ? places.map(homeObject) : [];
        } else collection[key] = homeObject(child);
      }
      rebuilt[group] = collection;
    }
    listing[namespace] = rebuilt;
  }
  return listing;
}
export function homeImages(value: unknown, primary?: unknown): string[] {
  if (typeof value === 'string') { const encoded = value; try { value = JSON.parse(encoded); } catch { value = encoded.split('|'); } }
  const images = Array.isArray(value) ? value : [];
  return [...new Set([primary, ...images].filter((url): url is string => typeof url === 'string' && !!url.trim()).map(url => url.trim()))];
}
export function homeBoolean(value: unknown): boolean | undefined {
  if (value === true || value === 'true') return true;
  if (value === false || value === 'false') return false;
  return undefined;
}
export function homeApproximate(content: Record<string, unknown>): boolean {
  return homeBoolean(content.location_approximate) !== false || content.location_precision !== 'building';
}
/** Render scalar provider facts only: no raw HTML and no implicit certainty. */
export function homeEvidence(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Unknown';
  if (Array.isArray(value)) return value.map(homeEvidence).join(', ');
  if (typeof value === 'object') return Object.entries(value).map(([key, item]) => `${key.replaceAll('_', ' ')}: ${homeEvidence(item)}`).join(' · ');
  if (value === true) return 'Yes';
  if (value === false) return 'No';
  return String(value).replaceAll('_', ' ');
}

export interface HomeListingFilters {
  maxPrice?: number;
  priceBasis: 'advertised' | 'warm' | 'cold';
  minRooms?: number;
  minSize?: number;
  requiredAmenity: string;
}
/** Explicit false/conflict takes precedence; possible and unknown never satisfy a requirement. */
export function homeHasAmenity(raw: Record<string, unknown>, amenity: string): boolean {
  const listing = homeListingContent(raw);
  const advertised = homeBoolean(listing[amenity]) ?? homeBoolean(homeObject(listing.amenities)[amenity]);
  const match = homeObject(homeObject(homeObject(listing.match_evidence).amenities)[amenity]);
  if (homeBoolean(match.source_conflict) === true || match.expectation === 'absent' || match.text_status === 'absent' || advertised === false || match.status === 'conflicting' || homeBoolean(match.advertised) === false) return false;
  return advertised === true || match.status === 'confirmed';
}
export function homeMatchesFilters(raw: Record<string, unknown>, filters: HomeListingFilters): boolean {
  const listing = homeListingContent(raw);
  if (filters.maxPrice !== undefined) {
    const price = filters.priceBasis === 'advertised'
      ? homeNumber(listing.price)
      : homeNumber(listing[`${filters.priceBasis}_rent_eur`]) ?? (listing.price_type === filters.priceBasis ? homeNumber(listing.price) : undefined);
    if (price === undefined || price > filters.maxPrice) return false;
  }
  if (filters.minRooms !== undefined) {
    const rooms = homeNumber(listing.rooms);
    if (rooms === undefined || rooms < filters.minRooms) return false;
  }
  if (filters.minSize !== undefined) {
    const size = homeNumber(listing.size_sqm);
    if (size === undefined || size < filters.minSize) return false;
  }
  return !filters.requiredAmenity || homeHasAmenity(listing, filters.requiredAmenity);
}
