/**
 * Text-only renderers for home/real-estate embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, formatPrice, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:home:search — composite */
export function renderHomeSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? '';
	const lines: string[] = [];
	lines.push(`**Home Search**${query ? ` — "${query}"` : ''}`);

	if (children && children.length > 0) {
		lines.push(`${children.length} listings:`);
		for (const r of children.slice(0, 5)) {
			const title = str(r.title) ?? str(r.name) ?? '';
			const price = formatPrice(r.price ?? r.rent, r.currency);
			const address = str(r.address) ?? str(r.location) ?? '';
			if (title) lines.push(`  ${title}`);
			if (price) lines.push(`  ${price}`);
			if (address) lines.push(`  ${address}`);
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} listings`);
	}
	return lines.join('\n');
}

/** home-listing — individual listing */
export function renderListing(c: Record<string, unknown>): string {
	const title = str(c.title) ?? str(c.name) ?? '';
	const price = formatPrice(c.price ?? c.rent, c.currency);
	const address = str(c.address) ?? str(c.location) ?? '';
	const lines: string[] = [];
	if (title) lines.push(`**${title}**`);
	if (price) lines.push(price);
	if (address) lines.push(address);
	return lines.length > 0 ? lines.join('\n') : '[Listing]';
}
