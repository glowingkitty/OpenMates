/**
 * Text-only renderers for electronics embed types.
 * Used by copy-to-clipboard, markdown export, and CLI output.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

function formatNumber(value: unknown, unit: string): string {
	if (typeof value !== 'number' || !Number.isFinite(value)) return '';
	return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${unit}`;
}

/** electronics-component - individual component/reference-design child embed */
export function renderElectronicsComponent(c: Record<string, unknown>): string {
	const partNumber = str(c.part_number) ?? str(c.base_part_number) ?? str(c.title) ?? 'Component';
	const topology = str(c.topology) ?? '';
	const packageName = str(c.package) ?? '';
	const lines: string[] = [partNumber];
	if (topology) lines.push(topology);
	if (packageName) lines.push(packageName);

	const efficiency = formatNumber(c.efficiency_percent, '% efficiency');
	const bomCost = formatNumber(c.bom_cost_usd, 'USD BOM');
	if (efficiency) lines.push(efficiency);
	if (bomCost) lines.push(bomCost);

	const url = str(c.product_url) ?? str(c.datasheet_url) ?? '';
	if (url) lines.push(url);
	return lines.join('\n');
}

/** app:electronics:search_components - composite component search embed */
export function renderElectronicsSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? str(c.category) ?? '';
	const lines: string[] = [];
	lines.push(`**Electronics Search**${query ? ` - "${trunc(query, 60)}"` : ''}`);

	if (children && children.length > 0) {
		lines.push(`${children.length} components:`);
		for (const result of children.slice(0, 5)) {
			const rendered = renderElectronicsComponent(result);
			if (rendered) lines.push(`  ${rendered.replace(/\n/g, '\n  ')}`);
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} components`);
	}

	return lines.join('\n');
}
