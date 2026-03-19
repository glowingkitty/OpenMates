/**
 * Docs slug page — prerender + SSR config for SEO.
 *
 * The entries() function generates all known doc slugs at build time,
 * allowing SvelteKit to prerender every docs page to static HTML.
 * This is critical for SEO — without it, the Vercel catch-all rewrite
 * would serve the SPA shell instead of the docs content.
 */
import docsData from '$lib/generated/docs-data.json';
import type { DocFolder, DocStructure } from '$lib/types/docs';

export const prerender = true;
export const ssr = true;

/** Generate all doc page slugs for prerendering */
export function entries() {
	const slugs: Array<{ slug: string }> = [];

	function collectSlugs(folder: DocFolder | DocStructure, parentPath = '') {
		// Collect file slugs
		for (const file of folder.files) {
			slugs.push({ slug: file.slug });
		}

		// Recurse into subfolders
		for (const subfolder of folder.folders) {
			const folderPath = parentPath ? `${parentPath}/${subfolder.name}` : subfolder.name;
			// Also add the folder itself as a slug (for folder index pages)
			slugs.push({ slug: folderPath });
			collectSlugs(subfolder, folderPath);
		}
	}

	collectSlugs(docsData.structure as DocStructure);
	return slugs;
}
