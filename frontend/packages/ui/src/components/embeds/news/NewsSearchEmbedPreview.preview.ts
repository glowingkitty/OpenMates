/**
 * Preview mock data for NewsSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/news/NewsSearchEmbedPreview
 */

/** Default props — shows a finished news search with results */
const defaultProps = {
	id: 'preview-news-search-1',
	query: 'latest technology news 2026',
	provider: 'Brave Search',
	status: 'finished' as const,
	results: [
		{
			title: 'AI Advances Continue to Transform Software Development',
			url: 'https://example.com/news/ai-advances',
			description:
				'New AI-powered development tools are changing how developers write, test, and deploy software.',
			favicon: '',
			image: '',
			publishedAt: '2026-02-15T08:00:00Z'
		},
		{
			title: 'WebAssembly 3.0 Specification Finalized',
			url: 'https://example.com/news/wasm-3',
			description:
				'The W3C has finalized the WebAssembly 3.0 specification, bringing garbage collection and improved threading.',
			favicon: '',
			image: '',
			publishedAt: '2026-02-10T12:00:00Z'
		},
		{
			title: 'European Tech Scene Sees Record Venture Capital Investment',
			url: 'https://example.com/news/eu-vc',
			description:
				'European startups raised a record €45 billion in venture capital funding in Q4 2025.',
			favicon: '',
			publishedAt: '2026-01-28T09:00:00Z'
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
		id: 'preview-news-search-processing',
		query: 'searching for news...',
		provider: 'Brave Search',
		status: 'processing' as const,
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-news-search-error',
		query: 'failed news search',
		provider: 'Brave Search',
		status: 'error' as const,
		results: [],
		isMobile: false
	},

	/** Cancelled state */
	cancelled: {
		id: 'preview-news-search-cancelled',
		query: 'cancelled news search',
		provider: 'Brave Search',
		status: 'cancelled' as const,
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-news-search-mobile',
		isMobile: true
	}
};
