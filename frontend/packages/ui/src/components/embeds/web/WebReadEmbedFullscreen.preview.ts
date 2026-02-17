/**
 * Preview mock data for WebReadEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/web/WebReadEmbedFullscreen
 */

const sampleResults = [
	{
		url: 'https://example.com/article/svelte-5-migration-guide',
		title: 'Complete Guide to Migrating from Svelte 4 to Svelte 5',
		content:
			'Svelte 5 introduces runes, a powerful new reactivity system that replaces the $: reactive statements. ' +
			'This guide walks you through every step of the migration process.\n\n' +
			'## Step 1: Update Dependencies\n\n' +
			'First, update your package.json to use Svelte 5.\n\n' +
			'## Step 2: Replace Reactive Declarations\n\n' +
			'Replace all `$:` statements with `$derived()` or `$effect()` runes.\n\n' +
			'## Step 3: Update Component Props\n\n' +
			'Use `$props()` instead of `export let` for component properties.',
		favicon: ''
	}
];

/** Default props — shows a fullscreen web read view */
const defaultProps = {
	results: sampleResults,
	url: 'https://example.com/article/svelte-5-migration-guide',
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

	/** No results yet — processing state */
	processing: {
		url: 'https://example.com/article/loading',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
