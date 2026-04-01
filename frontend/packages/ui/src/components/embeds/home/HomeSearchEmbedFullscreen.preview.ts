/**
 * Preview mock data for HomeSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/home
 */

const sampleListings = [
	{
		title: 'Schöne 2-Zimmer-Wohnung in Kreuzberg',
		price_label: '850 EUR/month',
		size_sqm: 55,
		rooms: 2,
		address: 'Bergmannstr., 10961 Berlin',
		image_url: '',
		url: 'https://www.immobilienscout24.de/expose/12345',
		provider: 'ImmoScout24',
		listing_type: 'rent'
	},
	{
		title: 'WG-Zimmer in Prenzlauer Berg — möbliert, ab sofort',
		price_label: '500 EUR/month',
		size_sqm: 18,
		rooms: 1,
		address: 'Schönhauser Allee, 10439 Berlin',
		image_url: '',
		url: 'https://www.wg-gesucht.de/wg-zimmer-in-Berlin.12345.html',
		provider: 'WG-Gesucht',
		listing_type: 'rent'
	},
	{
		title: 'Helle 3-Zimmer-Altbauwohnung mit Balkon',
		price_label: '1.200 EUR/month',
		size_sqm: 85,
		rooms: 3,
		address: 'Friedrichshain, 10245 Berlin',
		image_url: '',
		url: 'https://www.kleinanzeigen.de/s-anzeige/67890',
		provider: 'Kleinanzeigen',
		listing_type: 'rent'
	},
	{
		title: 'Großzügiges Loft in Mitte mit Dachterrasse',
		price_label: '2.100 EUR/month',
		size_sqm: 120,
		rooms: 4,
		address: 'Rosenthaler Str., 10119 Berlin',
		image_url: '',
		url: 'https://www.immobilienscout24.de/expose/99999',
		provider: 'ImmoScout24',
		listing_type: 'rent'
	}
];

/** Default props — shows fullscreen search results */
const defaultProps = {
	query: 'Berlin',
	provider: 'Multi',
	status: 'finished' as const,
	results: sampleListings,
	onClose: () => {},
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state */
	processing: {
		query: 'Berlin',
		provider: 'Multi',
		status: 'processing' as const,
		results: [],
		onClose: () => {}
	},

	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => {},
		onNavigateNext: () => {}
	},

	/** Error state */
	error: {
		query: 'Berlin',
		provider: 'Multi',
		status: 'error' as const,
		errorMessage: 'All providers failed. Please try again.',
		results: [],
		onClose: () => {}
	}
};
