/**
 * Preview mock data for VideosSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/videos/VideosSearchEmbedFullscreen
 */

const sampleResults = [
	{
		title: 'Svelte 5 Runes — Complete Beginner Guide',
		url: 'https://www.youtube.com/watch?v=example1',
		thumbnail: '',
		channelName: 'Svelte Society',
		duration: '17:08',
		viewCount: 245000
	},
	{
		title: 'Migrating from Svelte 4 to 5 — Step by Step',
		url: 'https://www.youtube.com/watch?v=example2',
		thumbnail: '',
		channelName: 'Frontend Masters',
		duration: '32:15',
		viewCount: 128000
	},
	{
		title: 'Building a Full App with SvelteKit 2',
		url: 'https://www.youtube.com/watch?v=example3',
		thumbnail: '',
		channelName: 'Fireship',
		duration: '12:42',
		viewCount: 890000
	}
];

/** Default props — shows a fullscreen video search results view */
const defaultProps = {
	query: 'svelte 5 tutorial',
	provider: 'Brave Search',
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

	/** Empty results */
	noResults: {
		query: 'extremely obscure search',
		provider: 'Brave Search',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
