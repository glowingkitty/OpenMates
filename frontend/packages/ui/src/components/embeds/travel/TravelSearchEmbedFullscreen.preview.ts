/**
 * Preview mock data for TravelSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelSearchEmbedFullscreen
 */

const sampleResults = [
	{
		price: '189.00',
		currency: 'EUR',
		transport_method: 'airplane',
		origin: 'Munich (MUC)',
		destination: 'London Heathrow (LHR)',
		departure: '2026-03-15T08:30:00',
		arrival: '2026-03-15T10:00:00',
		duration: '2h 30m',
		stops: 0,
		carriers: ['Lufthansa']
	},
	{
		price: '245.50',
		currency: 'EUR',
		transport_method: 'airplane',
		origin: 'Munich (MUC)',
		destination: 'London Gatwick (LGW)',
		departure: '2026-03-15T14:15:00',
		arrival: '2026-03-15T17:45:00',
		duration: '4h 30m',
		stops: 1,
		carriers: ['British Airways', 'Eurowings']
	}
];

/** Default props — shows a fullscreen travel search results view */
const defaultProps = {
	query: 'Munich -> London, 2026-03-15',
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
		query: 'Berlin -> Paris, 2026-04-01',
		provider: 'Google',
		status: 'processing' as const,
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	},

	/** Error state */
	error: {
		query: 'Invalid -> Route',
		provider: 'Google',
		status: 'error' as const,
		errorMessage: 'No connections found for the selected route.',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
