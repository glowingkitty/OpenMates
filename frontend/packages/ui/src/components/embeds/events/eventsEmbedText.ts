/**
 * Text-only renderers for event embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:events:search — composite */
export function renderEventsSearch(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? str(c.search_query) ?? '';
	const provider = str(c.provider);
	const providers = Array.isArray(c.providers) ? (c.providers as string[]) : [];
	const lines: string[] = [];

	let header = '**Event Search**';
	if (query) header += ` — "${trunc(query, 60)}"`;
	if (providers.length > 0) {
		header += ` via ${providers.join(', ')}`;
	} else if (provider && provider !== 'auto') {
		header += ` via ${provider}`;
	}
	lines.push(header);

	if (children && children.length > 0) {
		lines.push(`${children.length} events:`);
		for (const r of children.slice(0, 5)) {
			const name = str(r.name) ?? str(r.title) ?? '';
			const date = str(r.date) ?? str(r.start_date) ?? str(r.dateTime) ?? '';
			const venue = str(r.venue) ?? str(r.location) ?? '';
			const url = str(r.url) ?? str(r.link) ?? '';
			if (name) lines.push(`  ${name}`);
			if (date || venue) lines.push(`  ${[date, venue].filter(Boolean).join(' @ ')}`);
			if (url) lines.push(`  ${url}`);
			lines.push('');
		}
		if (children.length > 5) lines.push(`  + ${children.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} events`);
	}
	return lines.join('\n');
}

/** events-event — individual event */
export function renderEvent(c: Record<string, unknown>): string {
	const name = str(c.name) ?? str(c.title) ?? '';
	const date = str(c.date) ?? str(c.start_date) ?? '';
	const venue = str(c.venue) ?? str(c.location) ?? '';
	const lines: string[] = [];
	if (name) lines.push(`**${name}**`);
	if (date || venue) lines.push([date, venue].filter(Boolean).join(' @ '));
	return lines.length > 0 ? lines.join('\n') : '[Event]';
}
