/**
 * Text-only renderers for travel embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str, trunc, formatPrice, resolveResultCount } from '../../../data/embedTextRenderers';

/** app:travel:search_connections — composite */
export function renderTravelConnections(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? '';
	const lines: string[] = [];
	lines.push(`**Travel Connections**${query ? ` — "${trunc(query, 60)}"` : ''}`);

	const results = children ?? (c.results as Record<string, unknown>[] | undefined) ?? [];
	if (results.length > 0) {
		lines.push(`${results.length} connections:`);
		for (const r of results.slice(0, 5)) {
			const origin = str(r.origin) ?? '';
			const dest = str(r.destination) ?? '';
			const dep = str(r.departure)?.slice(11, 16) ?? '';
			const arr = str(r.arrival)?.slice(11, 16) ?? '';
			const duration = str(r.duration) ?? '';
			const price = formatPrice(r.total_price ?? r.price, r.currency);
			const stops = typeof r.stops === 'number' ? (r.stops === 0 ? 'Direct' : `${r.stops} stops`) : '';
			if (origin && dest) lines.push(`  ${origin} → ${dest}`);
			if (dep && arr) lines.push(`  ${dep} – ${arr}${duration ? `  (${duration})` : ''}`);
			if (price || stops) lines.push(`  ${[price, stops].filter(Boolean).join('  · ')}`);
			lines.push('');
		}
		if (results.length > 5) lines.push(`  + ${results.length - 5} more`);
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} connections`);
	}
	return lines.join('\n');
}

/** app:travel:search_stays — composite */
export function renderTravelStays(
	c: Record<string, unknown>,
	children?: Record<string, unknown>[]
): string {
	const query = str(c.query) ?? '';
	const lines: string[] = [];
	lines.push(`**Travel Stays**${query ? ` — "${trunc(query, 60)}"` : ''}`);

	const results = children ?? (c.results as Record<string, unknown>[] | undefined) ?? [];
	if (results.length > 0) {
		lines.push(`${results.length} stays:`);
		for (const r of results.slice(0, 5)) {
			const name = str(r.name) ?? str(r.hotel_name) ?? '';
			const price = formatPrice(r.total_price ?? r.price, r.currency);
			const rating = typeof r.rating === 'number' ? `★ ${r.rating}` : '';
			const address = str(r.address) ?? '';
			if (name) lines.push(`  ${name}${rating ? `  ${rating}` : ''}`);
			if (price) lines.push(`  ${price}`);
			if (address) lines.push(`  ${address}`);
			lines.push('');
		}
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} stays`);
	}
	return lines.join('\n');
}

/** app:travel:price_calendar */
export function renderPriceCalendar(c: Record<string, unknown>): string {
	const origin = str(c.origin) ?? '';
	const dest = str(c.destination) ?? '';
	const cheapest = c.cheapest_price;
	const currency = str(c.currency) ?? 'EUR';
	const lines: string[] = [];
	lines.push('**Price Calendar**');
	if (origin && dest) lines.push(`${origin} → ${dest}`);
	if (cheapest !== undefined && cheapest !== null) lines.push(`From ${currency} ${cheapest}`);
	return lines.join('\n');
}

/** app:travel:get_flight */
export function renderFlight(c: Record<string, unknown>): string {
	const lines: string[] = ['**Flight Info**'];
	const fields: [string, unknown][] = [
		['Flight', c.flight_number ?? c.callsign],
		['Airline', c.airline],
		['Route', c.origin && c.destination ? `${c.origin} → ${c.destination}` : null],
		['Departure', c.departure],
		['Arrival', c.arrival],
		['Status', c.flight_status]
	];
	for (const [label, value] of fields) {
		if (value !== null && value !== undefined) lines.push(`${label}: ${value}`);
	}
	return lines.join('\n');
}

/** travel-connection — individual */
export function renderConnection(c: Record<string, unknown>): string {
	const origin = str(c.origin) ?? '';
	const dest = str(c.destination) ?? '';
	const dep = str(c.departure)?.slice(11, 16) ?? '';
	const arr = str(c.arrival)?.slice(11, 16) ?? '';
	const price = formatPrice(c.total_price ?? c.price, c.currency);
	const lines: string[] = [];
	if (origin && dest) lines.push(`${origin} → ${dest}`);
	if (dep && arr) lines.push(`${dep} – ${arr}`);
	if (price) lines.push(price);
	return lines.length > 0 ? lines.join('\n') : '[Connection]';
}

/** travel-stay — individual */
export function renderStay(c: Record<string, unknown>): string {
	const name = str(c.name) ?? str(c.hotel_name) ?? '';
	const price = formatPrice(c.total_price ?? c.price, c.currency);
	const rating = typeof c.rating === 'number' ? `★ ${c.rating}` : '';
	const lines: string[] = [];
	if (name) lines.push(`${name}${rating ? `  ${rating}` : ''}`);
	if (price) lines.push(price);
	return lines.length > 0 ? lines.join('\n') : '[Stay]';
}
