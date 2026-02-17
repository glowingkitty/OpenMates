/**
 * Preview mock data for WebReadEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/web/WebReadEmbedPreview
 */

/** Default props — shows a finished web read embed with article content */
const defaultProps = {
	id: 'preview-web-read-1',
	status: 'finished' as const,
	url: 'https://example.com/article/svelte-5-migration-guide',
	results: [
		{
			url: 'https://example.com/article/svelte-5-migration-guide',
			title: 'Complete Guide to Migrating from Svelte 4 to Svelte 5',
			content:
				'Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. This guide walks you through every step of the migration process, from updating your dependencies to converting your components.',
			favicon: ''
		}
	],
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading animation while reading the page */
	processing: {
		id: 'preview-web-read-processing',
		status: 'processing' as const,
		url: 'https://example.com/article/loading',
		results: [],
		isMobile: false
	},

	/** Error state — shows error indicator */
	error: {
		id: 'preview-web-read-error',
		status: 'error' as const,
		url: 'https://example.com/article/not-found',
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-web-read-mobile',
		isMobile: true
	}
};
