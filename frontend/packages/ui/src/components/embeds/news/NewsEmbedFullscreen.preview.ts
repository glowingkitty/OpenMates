/**
 * Preview mock data for NewsEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/news/NewsEmbedFullscreen
 */

/** Default props — shows a fullscreen news article view */
const defaultProps = {
	url: 'https://example.com/news/svelte-5-released',
	title: 'Svelte 5 Officially Released with Revolutionary Runes System',
	description:
		'The Svelte team has announced the stable release of Svelte 5, featuring the new runes reactivity system.',
	favicon: '',
	thumbnail: '',
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
		extra_snippets: [
			'Runes replace the old $: reactive declarations with explicit $state, $derived, and $effect primitives.',
			'The migration from Svelte 4 to Svelte 5 is incremental — existing code continues to work in compatibility mode.'
		],
		dataDate: '2025-11-15'
	},

	/** Minimal — just URL */
	minimal: {
		url: 'https://example.com/news/article',
		onClose: () => console.log('[Preview] Close clicked')
	}
};
