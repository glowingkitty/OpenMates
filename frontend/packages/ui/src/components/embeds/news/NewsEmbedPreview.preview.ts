/**
 * Preview mock data for NewsEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/news/NewsEmbedPreview
 */

/** Default props — shows a finished news article embed card */
const defaultProps = {
	id: 'preview-news-1',
	url: 'https://example.com/news/svelte-5-released',
	title: 'Svelte 5 Officially Released with Revolutionary Runes System',
	description:
		'The Svelte team has announced the stable release of Svelte 5, featuring the new runes reactivity system that promises better performance and developer experience.',
	favicon: '',
	image: '',
	status: 'finished' as const,
	isMobile: false,
	onFullscreen: () => console.log('[Preview] Fullscreen clicked')
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
	/** Processing state — shows loading while fetching article */
	processing: {
		id: 'preview-news-processing',
		url: 'https://example.com/news/loading',
		status: 'processing' as const,
		isMobile: false
	},

	/** Error state */
	error: {
		id: 'preview-news-error',
		url: 'https://example.com/news/not-found',
		status: 'error' as const,
		isMobile: false
	},

	/** With all metadata */
	richMetadata: {
		id: 'preview-news-rich',
		url: 'https://techcrunch.com/2025/svelte-5-launch',
		title: 'Svelte 5 Launches to Wide Acclaim',
		description:
			'The latest version of the popular frontend framework brings fundamental changes to reactivity with the introduction of runes.',
		favicon: '',
		image: '',
		status: 'finished' as const,
		isMobile: false
	},

	/** Mobile view */
	mobile: {
		...defaultProps,
		id: 'preview-news-mobile',
		isMobile: true
	}
};
