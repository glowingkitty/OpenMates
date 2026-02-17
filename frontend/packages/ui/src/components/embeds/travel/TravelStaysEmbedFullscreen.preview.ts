/**
 * Preview mock data for TravelStaysEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelStaysEmbedFullscreen
 */

const sampleResults = [
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
];

/** Default props — shows a fullscreen stays search results view */
const defaultProps = {
	query: 'Hotels in Barcelona, Mar 15-18',
	provider: 'Google',
	status: 'finished' as const,
	results: sampleResults,
	onClose: () => console.log('[Preview] Close clicked'),
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
		onNavigatePrevious: () => console.log('[Preview] Navigate previous'),
		onNavigateNext: () => console.log('[Preview] Navigate next')
	},

	/** Processing state */
	processing: {
		query: 'Hotels in Paris, Apr 1-5',
		provider: 'Google',
		status: 'processing' as const,
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	},

	/** Error state */
	error: {
		query: 'Hotels in Invalid City',
		provider: 'Google',
		status: 'error' as const,
		errorMessage: 'Could not find stays for the specified location.',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
