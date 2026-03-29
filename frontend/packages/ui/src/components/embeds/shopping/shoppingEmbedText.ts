/**
 * Text-only renderers for shopping embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, formatPrice, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:shopping:search_products — composite (children are web-website) */
export function renderShoppingSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const lines: string[] = [];
	lines.push(`**Shopping Search**${query ? ` — "${trunc(query, 60)}"` : ''}`);

	if (children && children.length > 0) {
		lines.push(`${children.length} products:`);
		for (const r of children.slice(0, 5)) {
			const title = str(r.title) ?? str(r.name) ?? '';
			const price = formatPrice(r.price, r.currency);
			const url = str(r.url) ?? str(r.link) ?? '';
			if (title) lines.push(`  ${title}`);
			if (price) lines.push(`  ${price}`);
			if (url) lines.push(`  ${url}`);
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} products`);
	}
	return lines.join('\n');
}
