/**
 * Preview mock data for TravelSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelSearchEmbedPreview
 */

/** Default props — shows a finished travel search with connection results */
const defaultProps = {
	id: 'preview-travel-search-1',
	query: 'Munich -> London, 2026-03-15',
	provider: 'Google',
	status: 'finished' as const,
	results: [
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
	],
	isMobile: false,
	onFullscreen: () => {}
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-travel-search-processing',
		provider: 'Google Flights',
		providers: [{ id: 'google_flights', name: 'Google Flights', icon_url: 'https://www.google.com/favicon.ico' }],
		legs: [{ origin: 'Berlin', destination: 'Paris', date: '2026-04-01' }],
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Finished empty state — keeps request metadata even with no result cards */
	empty: {
		id: 'preview-travel-search-empty',
		provider: 'Google Flights',
		providers: [{ id: 'google_flights', name: 'Google Flights', icon_url: 'https://www.google.com/favicon.ico' }],
		legs: [{ origin: 'Hamburg', destination: 'Vienna', date: '2026-04-03' }],
		status: 'finished' as const,
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-travel-search-error',
		query: 'Invalid -> Route',
		provider: 'Google',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Cancelled state */
	cancelled: {
		id: 'preview-travel-search-cancelled',
		query: 'Munich -> Tokyo',
		provider: 'Google',
		status: 'cancelled' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-travel-search-mobile',
		isMobile: true
	}
};
