/**
 * Text-only renderers for web embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc } from '../../../data/embedTextRenderers';

/** app:web:search — composite with child web-website embeds */
export function renderWebSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const provider = str(c.provider);
	const lines: string[] = [];

	let header = '**Web Search**';
	if (query) header += ` — "${trunc(query, 60)}"`;
	if (provider) header += ` via ${provider}`;
	lines.push(header);

	if (children && children.length > 0) {
		lines.push(`${children.length} results:`);
		const shown = children.slice(0, 5);
		for (const r of shown) {
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
		if (count !== null) lines.push(`${count} results`);
	}

	return lines.join('\n');
}

/** app:web:read — web page content */
export function renderWebRead(c: Record<string, unknown>): string {
	const url = str(c.url) ?? '';
	const title = str(c.title) ?? '';
	const lines: string[] = [];
	lines.push('**Web Read**');
	if (title) lines.push(title);
	if (url) lines.push(url);
	return lines.join('\n');
}

/** web-website — individual website embed */
export function renderWebsite(c: Record<string, unknown>): string {
	const title = str(c.title) ?? '';
	const url = str(c.url) ?? '';
	const desc = str(c.description) ?? str(c.snippet) ?? '';
	const lines: string[] = [];
	if (title) lines.push(`**${title}**`);
	if (url) lines.push(url);
	if (desc) lines.push(trunc(desc, 200));
	return lines.length > 0 ? lines.join('\n') : '[Website]';
}

function resolveResultCount(c: Record<string, unknown>): number | null {
	if (typeof c.result_count === 'number') return c.result_count;
	const embedIds = c.embed_ids;
	if (typeof embedIds === 'string') return embedIds.split('|').filter(Boolean).length;
	if (Array.isArray(embedIds)) return embedIds.length;
	return null;
}
