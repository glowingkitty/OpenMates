/**
 * Preview mock data for VideosSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/videos/VideosSearchEmbedPreview
 */

/** Default props — shows a finished video search with results */
const defaultProps = {
	id: 'preview-videos-search-1',
	query: 'svelte 5 tutorial',
	provider: 'Brave Search',
	status: 'finished' as const,
	results: [
		{
			title: 'Svelte 5 Runes — Complete Beginner Guide',
			url: 'https://www.youtube.com/watch?v=example1',
			thumbnail: '',
			channelName: 'Svelte Society',
			duration: '17:08',
			viewCount: 245000,
			publishedAt: '2025-11-15T10:00:00Z'
		},
		{
			title: 'Migrating from Svelte 4 to 5 — Step by Step',
			url: 'https://www.youtube.com/watch?v=example2',
			thumbnail: '',
			channelName: 'Frontend Masters',
			duration: '32:15',
			viewCount: 128000,
			publishedAt: '2025-10-20T14:00:00Z'
		},
		{
			title: 'Building a Full App with SvelteKit 2',
			url: 'https://www.youtube.com/watch?v=example3',
			thumbnail: '',
			channelName: 'Fireship',
			duration: '12:42',
			viewCount: 890000,
			publishedAt: '2025-09-05T08:00:00Z'
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
		id: 'preview-videos-search-processing',
		query: 'searching for videos...',
		provider: 'Brave Search',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-videos-search-error',
		query: 'failed video search',
		provider: 'Brave Search',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-videos-search-mobile',
		isMobile: true
	}
};
