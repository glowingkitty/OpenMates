/**
 * Preview mock data for VideoTranscriptEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/videos/VideoTranscriptEmbedFullscreen
 */

const sampleResults = [
	{
		url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
		title: 'Understanding Svelte 5 Runes',
		transcript:
			'Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system ' +
			'that replaces the old reactive declarations.\n\n' +
			'The $state rune replaces let declarations for reactive variables. When you declare a variable ' +
			'with $state, Svelte automatically tracks all assignments to it.\n\n' +
			'The $derived rune replaces $: for computed values. It takes an expression and re-evaluates ' +
			'it whenever its dependencies change.\n\n' +
			'And the $effect rune replaces $: for side effects. It runs whenever any of its reactive ' +
			'dependencies change, similar to useEffect in React.',
		channelName: 'Svelte Society',
		durationFormatted: '17:08'
	}
];

/** Default props — shows a fullscreen video transcript view */
const defaultProps = {
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

	/** No results yet */
	empty: {
		results: [],
		onClose: () => console.log('[Preview] Close clicked')
	}
};
