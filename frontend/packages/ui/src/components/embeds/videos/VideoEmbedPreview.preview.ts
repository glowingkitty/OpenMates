/**
 * Preview mock data for VideoEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/videos/VideoEmbedPreview
 */

/** Default props — shows a finished video embed card with metadata */
const defaultProps = {
	id: 'preview-video-1',
	url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
	title: 'Understanding Svelte 5 Runes — Complete Tutorial',
	status: 'finished' as const,
	channelName: 'Svelte Society',
	channelId: 'UC_abc123',
	channelThumbnail: '',
	thumbnail: '',
	durationSeconds: 1028,
	durationFormatted: '17:08',
	viewCount: 245000,
	likeCount: 12400,
	publishedAt: '2025-11-15T10:00:00Z',
	videoId: 'dQw4w9WgXcQ',
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading while fetching video metadata */
	processing: {
		id: 'preview-video-processing',
		url: 'https://www.youtube.com/watch?v=loading',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-video-error',
		url: 'https://www.youtube.com/watch?v=invalid',
		status: 'error' as const,
		isMobile: false
	},

	/** Short video — under 1 minute */
	shortVideo: {
		...defaultProps,
		id: 'preview-video-short',
		title: 'Svelte 5 in 60 Seconds',
		durationSeconds: 58,
		durationFormatted: '0:58',
		viewCount: 89000
	},

	/** Long video — lecture/conference talk */
	longVideo: {
		...defaultProps,
		id: 'preview-video-long',
		title: 'SvelteKit Deep Dive — Full Conference Talk',
		channelName: 'Frontend Masters',
		durationSeconds: 5420,
		durationFormatted: '1:30:20',
		viewCount: 52000,
		likeCount: 3200
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-video-mobile',
		isMobile: true
	}
};
