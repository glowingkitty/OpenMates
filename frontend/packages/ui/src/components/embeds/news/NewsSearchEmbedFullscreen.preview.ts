/**
 * Preview mock data for NewsSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/news/NewsSearchEmbedFullscreen
 */

const sampleResults = [
	{
		title: 'AI Advances Continue to Transform Software Development',
		url: 'https://example.com/news/ai-advances',
		description:
			'New AI-powered development tools are changing how developers write, test, and deploy software.',
		favicon: '',
		publishedAt: '2026-02-15T08:00:00Z'
	},
	{
		title: 'WebAssembly 3.0 Specification Finalized',
		url: 'https://example.com/news/wasm-3',
		description:
			'The W3C has finalized the WebAssembly 3.0 specification, bringing garbage collection and improved threading.',
		favicon: '',
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
];

/** Default props — shows a fullscreen news search results view */
const defaultProps = {
	query: 'latest technology news 2026',
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
		query: 'extremely obscure news topic',
		provider: 'Brave Search',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
