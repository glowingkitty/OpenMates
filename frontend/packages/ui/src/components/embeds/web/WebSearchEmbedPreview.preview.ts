/**
 * Preview mock data for WebSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/web/WebSearchEmbedPreview
 */

/** Default props — shows a finished search with results */
const defaultProps = {
	id: 'preview-web-search-1',
	query: 'best restaurants in Berlin',
	provider: 'Brave Search',
	status: 'finished' as const,
	results: [
		{
			title: 'Top 10 Restaurants in Berlin - Local Guide',
			url: 'https://example.com/berlin-restaurants',
			description:
				'Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors. Updated for 2026.',
			favicon: ''
		},
		{
			title: 'Berlin Food Scene: A Complete Guide',
			url: 'https://example.com/berlin-food-guide',
			description:
				'From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe\'s top food destinations.',
			favicon: ''
		},
		{
			title: 'Where to Eat in Berlin - Travel Blog',
			url: 'https://example.com/eat-in-berlin',
			description:
				'A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options.',
			favicon: ''
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
		id: 'preview-web-search-processing',
		query: 'searching for something...',
		provider: 'Brave Search',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state — shows error indicator */
	error: {
		id: 'preview-web-search-error',
		query: 'failed search query',
		provider: 'Brave Search',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Cancelled state */
	cancelled: {
		id: 'preview-web-search-cancelled',
		query: 'cancelled search',
		provider: 'Brave Search',
		status: 'cancelled' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-web-search-mobile',
		isMobile: true
	}
};
