import type { ComponentProps } from 'svelte';
import type MapLocationEmbedFullscreen from './MapLocationEmbedFullscreen.svelte';

const defaultProps = {
  data: { decodedContent: {
    name: 'Man vs. Machine Coffee Roasters',
    formatted_address: 'Müllerstraße 23, 80469 Munich, Germany',
    location: { latitude: 48.1321, longitude: 11.5718 },
    rating: 4.7, user_rating_count: 1832, place_type: 'Coffee Shop',
    website_uri: 'https://www.mvsm.coffee', place_id: 'ChIJabc123',
  } },
  onClose: () => {},
} satisfies ComponentProps<typeof MapLocationEmbedFullscreen>;

export default defaultProps;
export const variants = {
  discovery: {
    data: { decodedContent: {
      name: 'Historic ruins', place_id: 'geoapify:example-ruins', provider: 'Geoapify',
      location: { latitude: 52.52, longitude: 13.405 }, place_type: 'Ruins',
      data_source: 'OpenStreetMap via Geoapify', distance_meters: 1240,
    } }, onClose: () => {},
  },
  withNavigation: { ...defaultProps, hasPreviousEmbed: true, hasNextEmbed: true, onNavigatePrevious: () => {}, onNavigateNext: () => {} },
  noCoords: { data: { decodedContent: { name: 'Lost Weekend', formatted_address: 'Schellingstraße 3, Munich' } }, onClose: () => {} },
  minimal: { data: { decodedContent: { name: 'Café Frischhut' } }, onClose: () => {} },
} satisfies Record<string, ComponentProps<typeof MapLocationEmbedFullscreen>>;
