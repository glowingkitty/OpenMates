/**
 * Maps docs folder names to chat category identifiers.
 * These categories control the gradient colors and icons in ChatHeader.
 *
 * Architecture: Uses the same CATEGORY_GRADIENTS from categoryUtils.ts
 * to give each docs section a distinctive visual identity.
 */

/** Maps a docs folder path to a chat category string for ChatHeader gradients */
export const DOCS_FOLDER_CATEGORY: Record<string, string> = {
	'apis': 'software_development',
	'apps': 'maker_prototyping',
	'architecture': 'electrical_engineering',
	'contributing': 'activism',
	'design-guide': 'design',
	'getting-started': 'onboarding_support',
	'self-hosting': 'software_development',
	'user-guide': 'general_knowledge',
	'api': 'software_development',
};

/** Maps a docs folder path to a Lucide icon name */
export const DOCS_FOLDER_ICON: Record<string, string> = {
	'apis': 'plug',
	'apps': 'layout-grid',
	'architecture': 'building-2',
	'contributing': 'git-pull-request',
	'design-guide': 'palette',
	'getting-started': 'rocket',
	'self-hosting': 'server',
	'user-guide': 'book-open',
	'api': 'file-code',
};

/**
 * Get category and icon for a doc based on its slug path.
 * Extracts the top-level folder from the slug.
 */
function getDocCategoryInfo(slug: string): { category: string; icon: string } {
	const topFolder = slug.split('/')[0] || '';
	return {
		category: DOCS_FOLDER_CATEGORY[topFolder] || 'general_knowledge',
		icon: DOCS_FOLDER_ICON[topFolder] || 'file-text',
	};
}
