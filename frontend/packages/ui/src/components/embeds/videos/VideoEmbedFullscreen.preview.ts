/**
 * Preview mock data for VideoEmbedFullscreen.
 *
 * Note: The embedded video player requires a valid YouTube URL to render.
 * In preview mode the iframe may not load, but the component layout/controls can be tested.
 * Access at: /dev/preview/embeds/videos/VideoEmbedFullscreen
 */

/** Default props — shows a fullscreen video view */
const defaultProps = {
	url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
	title: 'Understanding Svelte 5 Runes — Complete Tutorial',
	videoId: 'dQw4w9WgXcQ',
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

	/** With metadata passed from preview */
	withMetadata: {
		...defaultProps,
		metadata: {
			videoId: 'dQw4w9WgXcQ',
			title: 'Understanding Svelte 5 Runes — Complete Tutorial',
			channelName: 'Svelte Society',
			channelId: 'UC_abc123',
			thumbnailUrl: '',
			duration: { totalSeconds: 1028, formatted: '17:08' },
			viewCount: 245000,
			likeCount: 12400,
			publishedAt: '2025-11-15T10:00:00Z'
		}
	},

	/** Minimal — just URL */
	minimal: {
		url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
		onClose: () => console.log('[Preview] Close clicked')
	}
};
