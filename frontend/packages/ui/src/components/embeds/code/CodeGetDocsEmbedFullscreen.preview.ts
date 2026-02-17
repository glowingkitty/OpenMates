/**
 * Preview mock data for CodeGetDocsEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/code/CodeGetDocsEmbedFullscreen
 */

const sampleResults = [
	{
		title: '$state — Svelte 5 Runes',
		content:
			'The `$state` rune declares reactive state. When you assign to a `$state` variable, ' +
			'Svelte automatically updates all DOM nodes that depend on it.\n\n' +
			'## Basic Usage\n\n' +
			'```svelte\n<script>\nlet count = $state(0);\n</script>\n\n' +
			'<button onclick={() => count++}>\n  Clicks: {count}\n</button>\n```\n\n' +
			'## Deep Reactivity\n\n' +
			'`$state` provides deep reactivity for objects and arrays. Changes to nested ' +
			'properties are tracked automatically.\n\n' +
			'```svelte\n<script>\nlet user = $state({ name: "Alice", age: 30 });\n</script>\n\n' +
			'<input bind:value={user.name} />\n```',
		url: 'https://svelte.dev/docs/svelte/$state',
		source: 'svelte.dev'
	}
];

/** Default props — shows a fullscreen code docs view */
const defaultProps = {
	library: 'svelte',
	question: 'How to use $state rune in Svelte 5?',
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
		library: 'obscure-lib',
		question: 'How to use undocumented feature?',
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
