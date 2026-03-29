/**
 * Text-only renderers for maps embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:maps:search — composite with inline results */
export function renderMapsSearch(c: Record<string, unknown>): string {
	const query = str(c.query) ?? '';
	const lines: string[] = [];
	lines.push(`**Map Search**${query ? ` — "${query}"` : ''}`);

	const results = c.results as Array<Record<string, unknown>> | undefined;
	if (Array.isArray(results) && results.length > 0) {
		lines.push(`${results.length} places:`);
		for (const r of results.slice(0, 5)) {
			const name = str(r.displayName) ?? str(r.name) ?? '';
			const address = str(r.formattedAddress) ?? str(r.address) ?? '';
			const rating = typeof r.rating === 'number' ? `★ ${r.rating}` : '';
			if (name) lines.push(`  ${name}${rating ? `  ${rating}` : ''}`);
			if (address) lines.push(`  ${address}`);
			lines.push('');
		}
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} places`);
	}
	return lines.join('\n');
}

/** maps-place / maps — individual location */
export function renderMapsPlace(c: Record<string, unknown>): string {
	const name = str(c.displayName) ?? str(c.name) ?? '';
	const address = str(c.formattedAddress) ?? str(c.address) ?? '';
	const lines: string[] = [];
	if (name) lines.push(`**${name}**`);
	if (address) lines.push(address);
	return lines.length > 0 ? lines.join('\n') : '[Location]';
}
