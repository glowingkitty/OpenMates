/**
 * Text-only renderers for Fitness Urban Sports search embeds.
 * Used by copy-to-clipboard, markdown export, and CLI rendering.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';
import { getFitnessResultAddress, getFitnessResultTitle } from './fitnessEmbedData';

export function renderFitnessSearch(c: Record<string, unknown>): string {
	const groups = Array.isArray(c.results) ? c.results as Record<string, unknown>[] : [];
	const firstGroup = groups[0];
	const filters = firstGroup?.filters && typeof firstGroup.filters === 'object'
		? firstGroup.filters as Record<string, unknown>
		: {};
	const summary = str(firstGroup?.summary) ?? '';
	const location = str(filters.address) ?? str(filters.city) ?? str(c.query) ?? '';
	const count = typeof firstGroup?.result_count === 'number' ? firstGroup.result_count : resolveResultCount(c);
	const lines = ['**Fitness Search**'];
	if (location) lines.push(`Location: ${trunc(location, 80)}`);
	if (count !== null) lines.push(`${count} results`);
	if (summary) lines.push(summary);
	return lines.join('\n');
}

export function renderFitnessResult(c: Record<string, unknown>): string {
	const title = getFitnessResultTitle(c);
	const subtitle = str(c.venue_name) ?? getFitnessResultAddress(c);
	const lines = [`**${title}**`];
	if (subtitle) lines.push(trunc(subtitle, 100));
	if (c.date || c.time_range) lines.push([c.date, c.time_range].filter(Boolean).join(' '));
	if (c.distance_km !== null && c.distance_km !== undefined) lines.push(`${c.distance_km} km`);
	return lines.join('\n');
}
