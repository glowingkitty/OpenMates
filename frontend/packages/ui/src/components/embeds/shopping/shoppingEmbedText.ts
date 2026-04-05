/**
 * Text-only renderers for shopping embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, formatPrice, resolveResultCount } from '../../../data/embedTextRenderers';

/** shopping-product — individual product child embed */
export function renderShoppingProduct(c: Record<string, unknown>): string {
	const title = str(c.title) ?? str(c.name) ?? 'Product';
	const brand = str(c.brand) ?? '';
	const price = str(c.price_eur) ?? str(c.price) ?? formatPrice(c.price_amount, c.currency_symbol);
	const lines: string[] = [title];
	if (brand) lines.push(brand);
	if (price) lines.push(price);
	return lines.join('\n');
}

/** app:shopping:search_products — composite (children are shopping-product) */
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
