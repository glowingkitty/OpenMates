/**
 * Preview mock data for TravelStaysEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelStaysEmbedPreview
 */

/** Default props — shows a finished stay search with results */
const defaultProps = {
	id: 'preview-travel-stays-1',
	query: 'Hotels in Barcelona, Mar 15-18',
	provider: 'Google',
	status: 'finished' as const,
	results: [
		{
			name: 'Hotel Arts Barcelona',
			hotel_class: 5,
			overall_rating: 4.7,
			reviews: 4521,
			currency: 'EUR',
			rate_per_night: '320',
			amenities: ['Pool', 'Spa', 'Beach access', 'Fine dining']
		},
		{
			name: 'Casa Camper Barcelona',
			hotel_class: 4,
			overall_rating: 4.4,
			reviews: 1832,
			currency: 'EUR',
			rate_per_night: '185',
			amenities: ['Free Wi-Fi', 'Rooftop terrace', 'Free snacks']
		},
		{
			name: 'Generator Barcelona',
			hotel_class: 2,
			overall_rating: 4.0,
			reviews: 3200,
			currency: 'EUR',
			rate_per_night: '55',
			amenities: ['Free Wi-Fi', 'Bar', 'Shared kitchen']
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
		id: 'preview-travel-stays-processing',
		query: 'Hotels in Paris, Apr 1-5',
		provider: 'Google',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-travel-stays-error',
		query: 'Hotels in Invalid City',
		provider: 'Google',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Cancelled state */
	cancelled: {
		id: 'preview-travel-stays-cancelled',
		query: 'Hotels in Tokyo',
		provider: 'Google',
		status: 'cancelled' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-travel-stays-mobile',
		isMobile: true
	}
};
