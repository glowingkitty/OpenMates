/**
 * Preview mock data for HomeSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/home
 */

/** Default props — shows a finished search with listings */
const defaultProps = {
	id: 'preview-home-search-1',
	query: 'Berlin',
	provider: 'Multi',
	status: 'finished' as const,
	results: [
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
			title: 'WG-Zimmer in Prenzlauer Berg',
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
		}
	],
	isMobile: false,
	onFullscreen: () => {}
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-home-search-processing',
		query: 'Berlin',
		provider: 'Multi',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state — shows error indicator */
	error: {
		id: 'preview-home-search-error',
		query: 'invalid city',
		provider: 'Multi',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Cancelled state */
	cancelled: {
		id: 'preview-home-search-cancelled',
		query: 'Berlin',
		provider: 'Multi',
		status: 'cancelled' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-home-search-mobile',
		isMobile: true
	}
};
