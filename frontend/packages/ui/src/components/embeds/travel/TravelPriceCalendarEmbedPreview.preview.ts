/**
 * Preview mock data for TravelPriceCalendarEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/travel/TravelPriceCalendarEmbedPreview
 */

/** Default props — shows a finished price calendar with results */
const defaultProps = {
	id: 'preview-travel-price-calendar-1',
	query: 'Munich -> Barcelona, March 2026',
	status: 'finished' as const,
	results: [
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
	],
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation */
	processing: {
		id: 'preview-travel-price-calendar-processing',
		query: 'Berlin -> Rome, April 2026',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-travel-price-calendar-error',
		query: 'Invalid route',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Cancelled state */
	cancelled: {
		id: 'preview-travel-price-calendar-cancelled',
		query: 'Munich -> Tokyo, May 2026',
		status: 'cancelled' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-travel-price-calendar-mobile',
		isMobile: true
	}
};
