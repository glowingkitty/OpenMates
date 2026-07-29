/**
 * Embed app showcase route matcher.
 *
 * Restricts /dev/preview/embeds/<app> to real showcase slugs. Generic
 * component previews such as /dev/preview/embeds/EmbedsMapView must fall
 * through to the catch-all preview route instead.
 */
import { EMBED_APP_SLUGS } from '$lib/devPreviewEmbedApps';

const EMBED_APP_SLUG_SET = new Set<string>(EMBED_APP_SLUGS);

export function match(param: string): boolean {
	return EMBED_APP_SLUG_SET.has(param);
}
