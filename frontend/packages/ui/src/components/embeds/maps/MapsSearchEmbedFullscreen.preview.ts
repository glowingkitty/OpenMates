import type { ComponentProps } from 'svelte';
import type MapsSearchEmbedFullscreen from './MapsSearchEmbedFullscreen.svelte';
import { embedStore } from '../../../services/embedStore';

// Static public fixtures; no skill/provider calls or private chat state.
const regularChildren = [
  { name: 'Man vs. Machine Coffee Roasters', location: { latitude: 48.1321, longitude: 11.5718 }, rating: 4.7, place_type: 'Coffee Shop' },
  { name: 'Lost Weekend', location: { latitude: 48.1523, longitude: 11.5784 }, rating: 4.5, place_type: 'Coffee Shop' },
];
const discoveryChildren = [
  { name: 'Historic ruins', location: { latitude: 52.52, longitude: 13.405 }, place_type: 'Ruins', place_id: 'geoapify:fixture-ruins', distance_meters: 1240 },
  { name: 'Unnamed ruins', name_is_derived: true, location: { latitude: 52.53, longitude: 13.42 }, place_type: 'Ruins', place_id: 'geoapify:fixture-unnamed', distance_meters: 2380 },
].map(child => ({ ...child, provider: 'Geoapify', data_source: 'OpenStreetMap via Geoapify' }));

function seed(id: string, query: string, provider: string, children: object[]) {
  const ids = children.map((_, index) => id + '-place-' + index);
  children.forEach((content, index) => embedStore.registerStaticEmbed({
    embedId: ids[index], type: 'place', appId: 'maps', skillId: 'place', content: JSON.stringify(content),
  }));
  const content = { app_id: 'maps', skill_id: 'search', query, provider, result_count: ids.length, embed_ids: ids, status: 'finished' };
  embedStore.registerStaticEmbed({ embedId: id, type: 'app_skill_use', appId: 'maps', skillId: 'search', embedIds: ids, content: JSON.stringify(content) });
  return { embedId: id, data: { decodedContent: content }, onClose: () => {} } satisfies ComponentProps<typeof MapsSearchEmbedFullscreen>;
}
const defaultProps = seed('preview-maps-google', 'Coffee shops in Munich', 'Google Maps', regularChildren);
export default defaultProps;
const discovery = seed('preview-maps-geoapify', 'Ruins near Berlin', 'Geoapify', discoveryChildren);
export const variants = {
  discovery,
  withNavigation: { ...defaultProps, hasPreviousEmbed: true, hasNextEmbed: true, onNavigatePrevious: () => {}, onNavigateNext: () => {} },
  noResults: { data: { decodedContent: { query: 'Ruins nearby', provider: 'Geoapify', result_count: 0, embed_ids: [] } }, onClose: () => {} },
  quotaExhausted: { data: { decodedContent: { query: 'Ruins nearby', provider: 'Geoapify', search_status: 'quota_exhausted', embed_ids: [], error: 'Geoapify daily search allowance is exhausted. Try again tomorrow.' } }, onClose: () => {} },
  noVerifiedAmenityMatches: { data: { decodedContent: {
    query: 'Restaurants in Berlin with air conditioning and free wifi', provider: 'Google Maps + Geoapify', embed_ids: [],
    warnings: 'No Geoapify/OSM-verified matches were found within the enrichment budget; try relaxing the amenity filter.',
    filter_summary_required: 'air_conditioning|internet_access', filter_summary_candidate_count: 10,
    filter_summary_verified_count: 0, filter_summary_status: 'no_verified_results',
  } }, onClose: () => {} },
} satisfies Record<string, ComponentProps<typeof MapsSearchEmbedFullscreen>>;
