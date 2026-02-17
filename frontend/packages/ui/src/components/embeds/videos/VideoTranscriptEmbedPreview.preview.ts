/**
 * Preview mock data for VideoTranscriptEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/videos/VideoTranscriptEmbedPreview
 */

/** Default props — shows a finished video transcript embed */
const defaultProps = {
	id: 'preview-video-transcript-1',
	status: 'finished' as const,
	url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
	results: [
		{
			url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
			title: 'Understanding Svelte 5 Runes',
			transcript:
				'Today we are going to learn about Svelte 5 runes. Runes are a powerful new reactivity system. ' +
				'The $state rune replaces let declarations for reactive variables. ' +
				'The $derived rune replaces $: for computed values. ' +
				'And the $effect rune replaces $: for side effects.',
			channelName: 'Svelte Society',
			durationFormatted: '17:08'
		}
	],
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading while fetching transcript */
	processing: {
		id: 'preview-video-transcript-processing',
		status: 'processing' as const,
		url: 'https://www.youtube.com/watch?v=loading',
		results: [],
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-video-transcript-error',
		status: 'error' as const,
		url: 'https://www.youtube.com/watch?v=no-transcript',
		results: [],
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-video-transcript-mobile',
		isMobile: true
	}
};
