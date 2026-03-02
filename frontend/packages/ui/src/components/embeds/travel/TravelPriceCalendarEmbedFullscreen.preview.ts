/**
 * Preview mock data for TravelPriceCalendarEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelPriceCalendarEmbedFullscreen
 */

const sampleResults = [
	{ date: '2026-03-01', price: 89, currency: 'EUR' },
	{ date: '2026-03-02', price: 95, currency: 'EUR' },
	{ date: '2026-03-05', price: 72, currency: 'EUR' },
	{ date: '2026-03-08', price: 110, currency: 'EUR' },
	{ date: '2026-03-10', price: 65, currency: 'EUR' },
	{ date: '2026-03-12', price: 78, currency: 'EUR' },
	{ date: '2026-03-15', price: 145, currency: 'EUR' },
	{ date: '2026-03-18', price: 82, currency: 'EUR' },
	{ date: '2026-03-20', price: 99, currency: 'EUR' },
	{ date: '2026-03-22', price: 68, currency: 'EUR' },
	{ date: '2026-03-25', price: 120, currency: 'EUR' },
	{ date: '2026-03-28', price: 155, currency: 'EUR' }
];

/** Default props — shows a fullscreen price calendar view */
const defaultProps = {
	query: 'Munich -> Barcelona, March 2026',
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
		query: 'Berlin -> Rome, April 2026',
		status: 'processing' as const,
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	},

	/** Error state */
	error: {
		query: 'Invalid route',
		status: 'error' as const,
		errorMessage: 'Could not retrieve price calendar for the selected route.',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
