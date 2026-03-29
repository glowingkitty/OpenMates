/**
 * Text-only renderers for news embed types.
 * Reuses web search format since news children are web-website embeds.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:news:search — composite (children are web-website) */
export function renderNewsSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const provider = str(c.provider);
	const lines: string[] = [];

	let header = '**News Search**';
	if (query) header += ` — "${trunc(query, 60)}"`;
	if (provider) header += ` via ${provider}`;
	lines.push(header);

	if (children && children.length > 0) {
		lines.push(`${children.length} articles:`);
		for (const r of children.slice(0, 5)) {
			const title = str(r.title) ?? str(r.name) ?? '';
			const url = str(r.url) ?? str(r.link) ?? '';
			const desc = str(r.description) ?? str(r.snippet) ?? '';
			if (title) lines.push(`  ${title}`);
			if (url) lines.push(`  ${url}`);
			if (desc) lines.push(`  ${trunc(desc, 150)}`);
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} articles`);
	}
	return lines.join('\n');
}
