/**
 * Text-only renderers for nutrition embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

/** nutrition-recipe — individual recipe child embed */
export function renderNutritionRecipe(c: Record<string, unknown>): string {
	const title = str(c.title) ?? 'Recipe';
	const lines: string[] = [title];
	if (typeof c.total_time_minutes === 'number') lines.push(`${c.total_time_minutes} min`);
	const difficulty = str(c.difficulty);
	if (difficulty) lines.push(difficulty);
	if (Array.isArray(c.dietary_tags) && c.dietary_tags.length > 0) {
		lines.push((c.dietary_tags as string[]).join(', '));
	}
	return lines.join('\n');
}

/** app:nutrition:search_recipes — composite (children are nutrition-recipe) */
export function renderNutritionSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const lines: string[] = [];
	lines.push(`**Recipe Search**${query ? ` — "${trunc(query, 60)}"` : ''}`);

	if (children && children.length > 0) {
		lines.push(`${children.length} recipes:`);
		for (const r of children.slice(0, 5)) {
			const title = str(r.title) ?? '';
			if (title) lines.push(`  ${title}`);
			if (typeof r.total_time_minutes === 'number') {
				lines.push(`  ${r.total_time_minutes} min`);
			}
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} recipes`);
	}
	return lines.join('\n');
}
