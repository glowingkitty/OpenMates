/**
 * Preview mock data for HomeListingEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/home
 */

/** Default props — shows a listing card with full metadata */
const defaultProps = {
	embed_id: 'preview-listing-1',
	title: 'Schöne 2-Zimmer-Wohnung in Kreuzberg',
	price_label: '850 EUR/month',
	size_sqm: 55,
	rooms: 2,
	address: 'Bergmannstr. 12, 10961 Berlin',
  city: 'Berlin',
	image_url: '/store-examples/home-1.webp',
	url: 'https://example.com/expose/12345',
	provider: 'ExampleHousingA',
	listing_type: 'rent',
  lat: 52.49, lon: 13.42, location_precision: 'district', location_approximate: true,
  location_area: {latitude: 52.49, longitude: 13.42, radius_m: 1200, basis: 'district'},
	onSelect: () => console.log('[Preview] result expanded')
};

export default defaultProps;

/** Named variants for different listing types */
export const variants = {
  precise: {...defaultProps, location_precision: 'building', location_approximate: false, location_exact_address: true, location_area: undefined},
  preciseNoImage: {...defaultProps, image_url: '', location_precision: 'building', location_approximate: false, location_exact_address: true, location_area: undefined},
  photoWithoutGeometry: {...defaultProps, lat: undefined, lon: undefined, location_area: undefined},
  noLocation: {...defaultProps, city: undefined, image_url: '', lat: undefined, lon: undefined, location_area: undefined},
  cityOnly: {...defaultProps, city: 'Hamburg', address: 'Hamburg', title: 'Apartment in Hamburg', image_url: '', lat: undefined, lon: undefined, location_area: undefined},
  unknownCity: {...defaultProps, city: undefined, address: 'Undisclosed street 12', image_url: '', lat: undefined, lon: undefined, location_area: undefined},
  brokenImage: {...defaultProps, image_url: 'data:image/png;base64,invalid-image'},
  noImage: {...defaultProps, image_url: ''},
  chat: {...defaultProps, resultContext: 'chat' as const},
	/** ExampleHousingC room listing */
	wgRoom: {
		embed_id: 'preview-listing-wg',
		title: 'Gemütliches WG-Zimmer in Prenzlauer Berg',
		price_label: '500 EUR/month',
		size_sqm: 18,
		rooms: 1,
		address: 'Schönhauser Allee, 10439 Berlin',
		image_url: '',
		url: 'https://example.com/fixture',
		provider: 'ExampleHousingC',
		listing_type: 'rent',
		onSelect: () => console.log('[Preview] result expanded')
	},

	/** ExampleHousingB listing */
	ExampleHousingB: {
		embed_id: 'preview-listing-ka',
		title: 'Helle 3-Zimmer-Altbauwohnung mit Balkon und EBK',
		price_label: '1.200 EUR/month',
		size_sqm: 85,
		rooms: 3,
		address: 'Friedrichshain, 10245 Berlin',
		image_url: '',
		url: 'https://example.com/fixture',
		provider: 'ExampleHousingB',
		listing_type: 'rent',
		onSelect: () => console.log('[Preview] result expanded')
	},

	/** Buy listing */
	buyListing: {
		embed_id: 'preview-listing-buy',
		title: 'Eigentumswohnung in München-Schwabing',
		price_label: '450.000 EUR',
		size_sqm: 75,
		rooms: 3,
		address: 'Leopoldstr., 80802 München',
    city: 'München',
		image_url: '',
		url: 'https://example.com/expose/99999',
		provider: 'ExampleHousingA',
		listing_type: 'buy',
		onSelect: () => console.log('[Preview] result expanded')
	},

	/** Minimal data (no image, no size) */
	minimal: {
		embed_id: 'preview-listing-minimal',
		title: 'Wohnung zur Miete',
		price_label: 'Price on request',
		address: 'Berlin',
		url: 'https://example.com/fixture',
		provider: 'ExampleHousingB',
		listing_type: 'rent',
		onSelect: () => console.log('[Preview] result expanded')
	}
};
