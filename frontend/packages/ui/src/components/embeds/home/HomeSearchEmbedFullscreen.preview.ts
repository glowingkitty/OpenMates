import { listing, variants as listingVariants } from './HomeListingEmbedFullscreen.preview';
const results = [
  {...listing, title: 'Canal apartment with balcony', price: 1250, price_type: 'warm', garden: false, address: 'Example Street 12, Berlin', location: {exact_address: true}, location_precision: 'building', location_approximate: false},
  {...listing, title: 'District loft', price_label: '1,500 EUR cold / month', price: 1500, price_type: 'cold', cold_rent_eur: 1500, warm_rent_eur: null, rooms: 3, size_sqm: 85, balcony: null, garden: null, match_evidence: {amenities: {balcony: {status: 'unknown', advertised: null}, terrace: {status: 'confirmed', advertised: true}}}, location_precision: 'district', location_approximate: true},
  {...listing, title: 'Garden apartment without coordinates', price: 900, cold_rent_eur: 750, warm_rent_eur: 900, rooms: 1, size_sqm: 40, balcony: false, garden: true, match_evidence: {amenities: {balcony: {status: 'conflicting', advertised: false}, garden: {status: 'confirmed', advertised: true}}}, address: 'Berlin', location: {}, latitude: null, longitude: null, image_url: '/store-examples/home-3.webp'}
];
const defaultProps = {data: {decodedContent: {query: 'Berlin apartments', provider: 'Multi', results, status: 'finished'}}, onClose: () => {}};
export default defaultProps;
export const variants = {
  sameCityArea: {data: {decodedContent: {query: 'Berlin same-area homes', status: 'finished', results: ['A', 'B'].map(name => ({...listing, title: `Same city home ${name}`, location_precision: 'city', location: {area: {latitude: 52.52, longitude: 13.405, radius_m: 18000, basis: 'city', method: 'city_extent', source: 'Provider city', checked_at: '2026-10-21'}}}))}}},
  persistedFlattened: {data: {decodedContent: {query: 'Berlin', status: 'finished', results: [listingVariants.persistedFlattened.data.decodedContent]}}},
  noConfirmedMatches: {data: {decodedContent: {query: 'Berlin apartments', status: 'finished', results: [], warnings: JSON.stringify(['No confirmed matches: balcony and warm rent below 1500 EUR could not both be established.', 'Some listing photos could not be assessed.'])}}},
  processing: {data: {decodedContent: {query: 'Berlin', status: 'processing', results: []}}},
  error: {data: {decodedContent: {query: 'Berlin', status: 'error', error: 'Providers unavailable', results: []}}}
};
