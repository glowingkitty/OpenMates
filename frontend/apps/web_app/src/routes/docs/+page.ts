/**
 * Docs index page — prerender + SSR config for SEO.
 * Loads only the lightweight docs manifest so the landing page does not hydrate
 * the full documentation corpus.
 */
import manifest from '$lib/generated/docs-manifest.json';

export const prerender = true;
export const ssr = true;

export function load() {
	return { manifest };
}
