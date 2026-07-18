// frontend/packages/ui/src/components/embeds/design/designEmbedText.ts
//
// Plain-text renderers for Design app embeds.
// Used by copy/export flows and CLI output so new design embed types remain
// portable outside the browser UI.
//
// Architecture: docs/architecture/embeds.md

import { resolveResultCount, str } from '../../../data/embedTextRenderers';

export function renderDesignIconSearch(content: Record<string, unknown>): string {
	const query = str(content.query) ?? 'Icon search';
	const provider = str(content.provider) ?? 'Iconify';
	const count = resolveResultCount(content);
	const lines = ['**Design | Icon search**', `query: ${query}`, `provider: ${provider}`];
	if (count !== null) lines.push(`icons: ${count}`);
	return lines.join('\n');
}

export function renderDesignIconResult(content: Record<string, unknown>): string {
	const title = str(content.display_name) ?? str(content.name) ?? str(content.icon_id) ?? 'Icon';
	const collection = str(content.collection_name) ?? str(content.prefix);
	const license = str(content.license_title) ?? str(content.license_spdx);
	const svgPath = str(content.svg_path);
	const lines = [`**${title}**`];
	if (collection) lines.push(`collection: ${collection}`);
	if (license) lines.push(`license: ${license}`);
	if (svgPath) lines.push(svgPath);
	return lines.join('\n');
}
