/**
 * Preview mock data for MapsSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/maps/MapsSearchEmbedPreview
 */

/** Default props — shows a finished maps search with place results */
const defaultProps = {
	id: 'preview-maps-search-1',
	query: 'coffee shops near Marienplatz Munich',
	provider: 'Google',
	status: 'finished' as const,
	results: [
		{
			name: 'Man vs. Machine Coffee Roasters',
			address: 'Müllerstraße 23, 80469 Munich',
			rating: 4.7,
			reviews: 1832,
			type: 'Coffee shop',
			latitude: 48.1321,
			longitude: 11.5718
		},
		{
			name: 'Lost Weekend',
			address: 'Schellingstraße 3, 80799 Munich',
			rating: 4.5,
			reviews: 2456,
			type: 'Coffee shop & bookstore',
			latitude: 48.1523,
			longitude: 11.5784
		},
		{
			name: 'Café Frischhut',
			address: 'Prälat-Zistl-Straße 8, 80331 Munich',
			rating: 4.6,
			reviews: 3210,
			type: 'Traditional café',
			latitude: 48.1354,
			longitude: 11.5762
		}
	],
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-maps-search-processing',
		query: 'restaurants near Brandenburg Gate',
		provider: 'Google',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-maps-search-error',
		query: 'invalid location search',
		provider: 'Google',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-maps-search-mobile',
		isMobile: true
	}
};
