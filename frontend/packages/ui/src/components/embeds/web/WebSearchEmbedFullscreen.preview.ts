/**
 * Preview mock data for WebSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/web/WebSearchEmbedFullscreen
 */

const sampleResults = [
	{
		title: 'Top 10 Restaurants in Berlin - Local Guide',
		url: 'https://example.com/berlin-restaurants',
		description:
			'Discover the best dining experiences in Berlin, from traditional German cuisine to international flavors.',
		favicon: ''
	},
	{
		title: 'Berlin Food Scene: A Complete Guide',
		url: 'https://example.com/berlin-food-guide',
		description:
			"From street food to Michelin-starred restaurants, explore what makes Berlin one of Europe's top food destinations.",
		favicon: ''
	},
	{
		title: 'Where to Eat in Berlin - Travel Blog',
		url: 'https://example.com/eat-in-berlin',
		description:
			'A curated list of must-visit restaurants, cafes, and food markets in Berlin. Includes budget-friendly options.',
		favicon: ''
	},
	{
		title: 'Berlin Restaurant Guide 2026',
		url: 'https://example.com/berlin-2026',
		description: 'The most up-to-date guide to dining in Berlin with new openings and seasonal highlights.',
		favicon: ''
	}
];

/** Default props — shows fullscreen search results */
const defaultProps = {
	query: 'best restaurants in Berlin',
	provider: 'Brave Search',
	status: 'finished' as const,
	results: sampleResults,
	onClose: () => console.log('[Preview] Close clicked'),
	hasPreviousEmbed: false,
	hasNextEmbed: false
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state */
	processing: {
		query: 'searching...',
		provider: 'Brave Search',
		status: 'processing' as const,
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	},

	/** With navigation arrows */
	withNavigation: {
		...defaultProps,
		hasPreviousEmbed: true,
		hasNextEmbed: true,
		onNavigatePrevious: () => console.log('[Preview] Navigate previous'),
		onNavigateNext: () => console.log('[Preview] Navigate next')
	},

	/** Error state */
	error: {
		query: 'failed search',
		provider: 'Brave Search',
		status: 'error' as const,
		errorMessage: 'Search provider returned an error. Please try again.',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
