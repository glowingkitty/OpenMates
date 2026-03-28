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
	image_url: '',
	url: 'https://www.immobilienscout24.de/expose/12345',
	provider: 'ImmoScout24',
	listing_type: 'rent',
	onSelect: () => {}
};

export default defaultProps;

/** Named variants for different listing types */
export const variants = {
	/** WG-Gesucht room listing */
	wgRoom: {
		embed_id: 'preview-listing-wg',
		title: 'Gemütliches WG-Zimmer in Prenzlauer Berg',
		price_label: '500 EUR/month',
		size_sqm: 18,
		rooms: 1,
		address: 'Schönhauser Allee, 10439 Berlin',
		image_url: '',
		url: 'https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html',
		provider: 'WG-Gesucht',
		listing_type: 'rent',
		onSelect: () => {}
	},

	/** Kleinanzeigen listing */
	kleinanzeigen: {
		embed_id: 'preview-listing-ka',
		title: 'Helle 3-Zimmer-Altbauwohnung mit Balkon und EBK',
		price_label: '1.200 EUR/month',
		size_sqm: 85,
		rooms: 3,
		address: 'Friedrichshain, 10245 Berlin',
		image_url: '',
		url: 'https://www.kleinanzeigen.de/s-anzeige/67890',
		provider: 'Kleinanzeigen',
		listing_type: 'rent',
		onSelect: () => {}
	},

	/** Buy listing */
	buyListing: {
		embed_id: 'preview-listing-buy',
		title: 'Eigentumswohnung in München-Schwabing',
		price_label: '450.000 EUR',
		size_sqm: 75,
		rooms: 3,
		address: 'Leopoldstr., 80802 München',
		image_url: '',
		url: 'https://www.immobilienscout24.de/expose/99999',
		provider: 'ImmoScout24',
		listing_type: 'buy',
		onSelect: () => {}
	},

	/** Minimal data (no image, no size) */
	minimal: {
		embed_id: 'preview-listing-minimal',
		title: 'Wohnung zur Miete',
		price_label: 'Price on request',
		address: 'Berlin',
		url: 'https://www.kleinanzeigen.de/s-anzeige/00000',
		provider: 'Kleinanzeigen',
		listing_type: 'rent',
		onSelect: () => {}
	}
};
