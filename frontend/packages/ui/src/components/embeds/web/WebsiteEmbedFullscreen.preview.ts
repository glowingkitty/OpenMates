/**
 * Preview mock data for WebsiteEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/web/WebsiteEmbedFullscreen
 */

/** Default props — shows a fullscreen website view with metadata */
const defaultProps = {
	url: 'https://svelte.dev',
	title: 'Svelte — Cybernetically enhanced web apps',
	description:
		'Svelte is a radical new approach to building user interfaces. Write less code, use no virtual DOM, and create truly reactive apps.',
	favicon: 'https://svelte.dev/favicon.png',
	image: '',
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

	/** With extra snippets */
	withSnippets: {
		...defaultProps,
		url: 'https://github.com/sveltejs/svelte',
		title: 'sveltejs/svelte: Cybernetically enhanced web apps',
		extra_snippets: [
			'Svelte shifts work from the browser to a compile step that happens when you build your app.',
			'Instead of using techniques like virtual DOM diffing, Svelte writes code that updates the DOM when state changes.'
		]
	},

	/** Minimal — just URL, no prefetched metadata */
	minimal: {
		url: 'https://example.com/page',
		onClose: () => console.log('[Preview] Close clicked')
	}
};
