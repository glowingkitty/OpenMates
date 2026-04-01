/**
 * Preview mock data for HomeListingEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/home
 */

/** Default props — shows fullscreen listing detail */
const defaultProps = {
	title: 'Schöne 2-Zimmer-Wohnung in Kreuzberg',
	price_label: '850 EUR/month',
	size_sqm: 55,
	rooms: 2,
	address: 'Bergmannstr. 12, 10961 Berlin',
	image_url: '',
	url: 'https://www.immobilienscout24.de/expose/12345',
	provider: 'ImmoScout24',
	listing_type: 'rent',
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** WG-Gesucht room */
	wgRoom: {
		title: 'Gemütliches WG-Zimmer in Prenzlauer Berg — ab sofort, möbliert',
		price_label: '500 EUR/month',
		size_sqm: 18,
		rooms: 1,
		address: 'Schönhauser Allee, 10439 Berlin',
		image_url: '',
		url: 'https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html',
		provider: 'WG-Gesucht',
		listing_type: 'rent',
		onClose: () => {}
	},

	/** Buy listing */
	buyListing: {
		title: 'Eigentumswohnung in München-Schwabing — ruhige Lage',
		price_label: '450.000 EUR',
		size_sqm: 75,
		rooms: 3,
		address: 'Leopoldstr., 80802 München',
		image_url: '',
		url: 'https://www.immobilienscout24.de/expose/99999',
		provider: 'ImmoScout24',
		listing_type: 'buy',
		onClose: () => {}
	}
};
