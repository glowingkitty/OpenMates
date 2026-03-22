/**
 * Maps docs folder names to chat category identifiers.
 * These categories control the gradient colors and icons in ChatHeader.
 *
 * Architecture: Uses the same CATEGORY_GRADIENTS from categoryUtils.ts
 * to give each docs section a distinctive visual identity.
 */

/** Maps a docs folder path to a chat category string for ChatHeader gradients */
export const DOCS_FOLDER_CATEGORY: Record<string, string> = {
	'user-guide': 'general_knowledge',
	'self-hosting': 'software_development',
	'design-guide': 'design',
	'architecture': 'electrical_engineering',
	'cli': 'software_development',
	'api': 'software_development',
};

/** Maps a docs folder path to a Lucide icon name */
export const DOCS_FOLDER_ICON: Record<string, string> = {
	'user-guide': 'book-open',
	'self-hosting': 'server',
	'design-guide': 'palette',
	'architecture': 'building-2',
	'cli': 'terminal',
	'api': 'file-code',
};

/** Controls display order of docs categories on the landing page */
export const DOCS_FOLDER_ORDER: Record<string, number> = {
	'user-guide': 1,
	'self-hosting': 2,
	'design-guide': 3,
	'architecture': 4,
	'cli': 5,
	'api': 6,
};

/**
 * Get category and icon for a doc based on its slug path.
 * Extracts the top-level folder from the slug.
 */
export function getDocCategoryInfo(slug: string): { category: string; icon: string } {
	const topFolder = slug.split('/')[0] || '';
	return {
		category: DOCS_FOLDER_CATEGORY[topFolder] || 'general_knowledge',
		icon: DOCS_FOLDER_ICON[topFolder] || 'file-text',
	};
}
