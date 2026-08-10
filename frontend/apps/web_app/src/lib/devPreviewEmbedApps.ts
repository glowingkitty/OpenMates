/**
 * Embed app showcase slugs.
 *
 * Centralizes the one-segment /dev/preview/embeds/<app> route matcher list.
 * Component previews under /dev/preview/embeds/... use the generic preview
 * catch-all route and must not be captured by the app showcase route.
 */
export const EMBED_APP_SLUGS = [
	'code',
	'docs',
	'web',
	'videos',
	'images',
	'news',
	'travel',
	'maps',
	'math',
	'music',
	'events',
	'reminder',
	'sheets',
	'audio',
	'health',
	'mail',
	'pdf',
	'shopping',
	'fitness',
	'electronics',
	'home',
	'nutrition',
	'social_media',
	'weather',
	'tasks',
	'finance',
	'workflows'
] as const;
