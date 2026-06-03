/**
 * Docs slug page — prerender + SSR config for SEO.
 *
 * The entries() function generates all known doc slugs at build time while
 * load() fetches only the current page's static payload.
 */
import manifest from '$lib/generated/docs-manifest.json';
import type { DocFile, DocManifestFile, DocManifestFolder, DocManifestStructure } from '$lib/types/docs';

export const prerender = true;
export const ssr = true;

type PageData =
	| { type: 'file'; data: DocFile }
	| { type: 'folder'; data: DocManifestFolder }
	| null;

function findManifestData(slug: string): { type: 'file'; data: DocManifestFile } | { type: 'folder'; data: DocManifestFolder } | null {
	const parts = slug.split('/').filter(Boolean);
	if (parts.length === 0) return null;

	let current: DocManifestStructure | DocManifestFolder = manifest.structure as DocManifestStructure;

	for (let i = 0; i < parts.length; i++) {
		const part = parts[i];
		const isLast = i === parts.length - 1;

		const file = current.files.find((f) => f.slug === slug || f.name.replace('.md', '') === part);
		if (file && isLast) return { type: 'file', data: file };

		const folder = current.folders.find((f) => f.name === part);
		if (folder) {
			if (isLast) {
				const indexFile = folder.files.find((f) => f.name === 'README.md' || f.name === 'index.md');
				if (indexFile) return { type: 'file', data: indexFile };
				return { type: 'folder', data: folder };
			}
			current = folder;
			continue;
		}

		return null;
	}

	return null;
}

export async function load({ fetch, params }: { fetch: typeof globalThis.fetch; params: { slug?: string } }) {
	const slug = params.slug || '';
	const manifestData = findManifestData(slug);
	let pageData: PageData = null;

	if (manifestData?.type === 'file') {
		const response = await fetch(manifestData.data.pagePayload);
		if (response.ok) {
			pageData = { type: 'file', data: await response.json() };
		}
	} else if (manifestData?.type === 'folder') {
		pageData = manifestData;
	}

	return {
		slug,
		pageData,
		manifest,
	};
}

/** Generate all doc page slugs for prerendering */
export function entries() {
	const slugs: Array<{ slug: string }> = [];

	function collectSlugs(folder: DocManifestFolder | DocManifestStructure, parentPath = '') {
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

	collectSlugs(manifest.structure as DocManifestStructure);
	return slugs;
}
