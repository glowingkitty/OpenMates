/**
 * Shared plain-text embed renderer.
 *
 * Converts decoded embed content to human-readable text for:
 *   - Clipboard copy (text/plain MIME)
 *   - Markdown chat export (.md download)
 *   - CLI terminal output (via wrapper that adds ANSI codes)
 *
 * NOT used for: YML export (keeps JSON refs), sending to backend (needs JSON refs).
 *
 * Rendering logic extracted from the CLI's embedRenderers.ts but without
 * ANSI escape codes or process.stdout.write — pure string output.
 *
 * Architecture doc: docs/architecture/embeds.md
 */

// ---------------------------------------------------------------------------
// Helpers (mirrors CLI helpers, no ANSI codes)
// ---------------------------------------------------------------------------

const str = (v: unknown): string | null =>
	typeof v === 'string' && v.length > 0 ? v : null;

function trunc(s: string, max: number): string {
	return s.length > max ? s.slice(0, max) + '…' : s;
}

function formatPrice(amount: unknown, currency: unknown): string {
	if (amount === null || amount === undefined) return '';
	const cur = str(currency)?.toUpperCase() ?? '';
	return cur ? `${cur} ${amount}` : String(amount);
}

/** Direct types for child embeds — dispatched by type, not app/skill */
const DIRECT_TYPES = new Set([
	'code',
	'code-code',
	'docs-doc',
	'doc',
	'sheets-sheet',
	'sheet',
	'pdf',
	'image',
	'web-website',
	'videos-video',
	'travel-connection',
	'travel-stay',
	'maps',
	'maps-place',
	'recording',
	'mail-email',
	'math-plot',
	'events-event',
	'health-appointment',
	'shopping-product',
	'images-image-result',
	'news-article',
	'home-listing',
	'focus-mode-activation'
]);

/** Human-readable labels for embed types */
const TYPE_LABELS: Record<string, string> = {
	'code': 'Code',
	'code-code': 'Code',
	'docs-doc': 'Document',
	'doc': 'Document',
	'sheets-sheet': 'Sheet',
	'sheet': 'Sheet',
	'pdf': 'PDF',
	'image': 'Image',
	'web-website': 'Website',
	'videos-video': 'Video',
	'travel-connection': 'Connection',
	'travel-stay': 'Stay',
	'maps': 'Place',
	'maps-place': 'Place',
	'recording': 'Recording',
	'mail-email': 'Email',
	'math-plot': 'Math Plot',
	'events-event': 'Event',
	'health-appointment': 'Appointment',
	'shopping-product': 'Product',
	'images-image-result': 'Image',
	'news-article': 'Article',
	'home-listing': 'Listing',
	'focus-mode-activation': 'Focus Mode'
};

/** Skill labels for composite embeds */
const SKILL_LABELS: Record<string, string> = {
	'web/search': 'Web Search',
	'news/search': 'News Search',
	'shopping/search_products': 'Shopping Search',
	'images/search': 'Image Search',
	'mail/search': 'Email Search',
	'events/search': 'Event Search',
	'videos/search': 'Video Search',
	'maps/search': 'Map Search',
	'travel/search_connections': 'Travel Connections',
	'travel/search_stays': 'Travel Stays',
	'travel/price_calendar': 'Price Calendar',
	'travel/get_flight': 'Flight Info',
	'code/get_docs': 'Documentation',
	'web/read': 'Web Read',
	'math/calculate': 'Math',
	'reminder/set-reminder': 'Reminder',
	'reminder/list-reminders': 'Reminders',
	'reminder/cancel-reminder': 'Reminder',
	'images/generate': 'Generated Image',
	'images/generate_draft': 'Image Draft',
	'videos/get_transcript': 'Video Transcript',
	'health/search_appointments': 'Health Search',
	'audio/transcribe': 'Audio Transcription',
	'home/search': 'Home Search'
};

function resolveResultCount(c: Record<string, unknown>): number | null {
	if (typeof c.result_count === 'number') return c.result_count;
	const embedIds = c.embed_ids;
	if (typeof embedIds === 'string')
		return embedIds.split('|').filter(Boolean).length;
	if (Array.isArray(embedIds)) return embedIds.length;
	return null;
}

// ---------------------------------------------------------------------------
// Main entry point
// ---------------------------------------------------------------------------

/**
 * Render decoded embed content as human-readable plain text.
 *
 * @param embedType - The embed type (e.g. "web-website", "code-code")
 * @param appId - App identifier for composite embeds (e.g. "web", "travel")
 * @param skillId - Skill identifier for composite embeds (e.g. "search")
 * @param content - Decoded TOON content as key-value object
 * @param childContents - Optional resolved child embed contents for composite embeds
 * @returns Human-readable plain text representation
 */
export function renderEmbedAsText(
	embedType: string,
	appId: string | null,
	skillId: string | null,
	content: Record<string, unknown>,
	childContents?: Record<string, unknown>[]
): string {
	// Direct types: dispatch by embed type
	if (DIRECT_TYPES.has(embedType)) {
		return renderDirectType(embedType, content);
	}

	// Composite types: dispatch by app/skill
	const key = `${appId ?? ''}/${skillId ?? ''}`;
	return renderCompositeType(key, content, childContents);
}

// ---------------------------------------------------------------------------
// Composite type renderers (app/skill dispatch)
// ---------------------------------------------------------------------------

function renderCompositeType(
	key: string,
	c: Record<string, unknown>,
	childContents?: Record<string, unknown>[]
): string {
	const label = SKILL_LABELS[key] ?? key;
	const query = str(c.query) ?? str(c.search_query) ?? str(c.question);
	const provider = str(c.provider);
	const lines: string[] = [];

	// Header
	let header = `**${label}**`;
	if (query) header += ` — "${trunc(query, 60)}"`;
	if (provider) header += ` (via ${provider})`;
	lines.push(header);

	switch (key) {
		// ── Search types ─────────────────────────────────────────────
		case 'web/search':
		case 'news/search':
		case 'shopping/search_products':
		case 'images/search':
		case 'mail/search':
			renderSearchText(c, lines, childContents);
			break;

		case 'events/search':
			renderEventsSearchText(c, lines, childContents);
			break;

		case 'videos/search':
			renderVideosSearchText(c, lines, childContents);
			break;

		case 'maps/search':
			renderMapsSearchText(c, lines);
			break;

		// ── Travel types ─────────────────────────────────────────────
		case 'travel/search_connections':
			renderTravelConnectionsText(c, lines, childContents);
			break;

		case 'travel/search_stays':
			renderTravelStaysText(c, lines, childContents);
			break;

		case 'travel/price_calendar':
			renderPriceCalendarText(c, lines);
			break;

		case 'travel/get_flight':
			renderFlightText(c, lines);
			break;

		// ── Content types ────────────────────────────────────────────
		case 'code/get_docs':
			renderCodeDocsText(c, lines);
			break;

		case 'web/read':
			renderWebReadText(c, lines);
			break;

		case 'math/calculate':
			renderMathText(c, lines);
			break;

		// ── Reminders ────────────────────────────────────────────────
		case 'reminder/set-reminder':
		case 'reminder/list-reminders':
		case 'reminder/cancel-reminder':
			renderReminderText(c, lines);
			break;

		// ── Media types ──────────────────────────────────────────────
		case 'images/generate':
		case 'images/generate_draft':
			renderImageGenerateText(c, lines);
			break;

		case 'videos/get_transcript':
			renderVideoTranscriptText(c, lines);
			break;

		case 'health/search_appointments':
			renderHealthSearchText(c, lines, childContents);
			break;

		case 'audio/transcribe':
			renderAudioTranscribeText(c, lines);
			break;

		case 'home/search':
			renderHomeSearchText(c, lines, childContents);
			break;

		default: {
			// Generic fallback: show first few non-internal fields
			let count = 0;
			for (const [k, v] of Object.entries(c)) {
				if (count >= 4) break;
				if (
					v !== null &&
					v !== undefined &&
					typeof v !== 'object' &&
					!k.startsWith('_')
				) {
					lines.push(`${k}: ${trunc(String(v), 80)}`);
					count++;
				}
			}
		}
	}

	return lines.join('\n');
}

// ---------------------------------------------------------------------------
// Search renderers
// ---------------------------------------------------------------------------

function renderSearchText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const count = resolveResultCount(c);

	if (childContents && childContents.length > 0) {
		// Show individual results with URLs
		lines.push(`${childContents.length} results:`);
		for (const r of childContents) {
			const title = str(r.title) ?? str(r.name) ?? '';
			const url = str(r.url) ?? str(r.link) ?? '';
			const desc =
				str(r.description) ?? str(r.snippet) ?? str(r.summary) ?? '';
			if (title) lines.push(`  ${title}`);
			if (url) lines.push(`  ${url}`);
			if (desc) lines.push(`  ${trunc(desc, 200)}`);
			lines.push('');
		}
	} else if (count !== null) {
		lines.push(`${count} results`);
	}
}

function renderEventsSearchText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const count = resolveResultCount(c);

	if (childContents && childContents.length > 0) {
		lines.push(`${childContents.length} events:`);
		for (const r of childContents) {
			const name = str(r.name) ?? str(r.title) ?? '';
			const date = str(r.date) ?? str(r.start_date) ?? str(r.dateTime) ?? '';
			const venue = str(r.venue) ?? str(r.location) ?? '';
			const url = str(r.url) ?? str(r.link) ?? '';
			if (name) lines.push(`  ${name}`);
			if (date || venue)
				lines.push(`  ${[date, venue].filter(Boolean).join(' @ ')}`);
			if (url) lines.push(`  ${url}`);
			lines.push('');
		}
	} else if (count !== null) {
		lines.push(`${count} events`);
	}
}

function renderVideosSearchText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const count = resolveResultCount(c);

	if (childContents && childContents.length > 0) {
		lines.push(`${childContents.length} videos:`);
		for (const r of childContents) {
			const title = str(r.title) ?? '';
			const channel = str(r.channel) ?? str(r.author) ?? '';
			const duration = str(r.duration) ?? '';
			const url = str(r.url) ?? str(r.link) ?? '';
			if (title) lines.push(`  ${title}`);
			if (channel || duration)
				lines.push(`  ${[channel, duration].filter(Boolean).join('  ')}`);
			if (url) lines.push(`  ${url}`);
			lines.push('');
		}
	} else if (count !== null) {
		lines.push(`${count} videos`);
	}
}

function renderMapsSearchText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const results = c.results as Array<Record<string, unknown>> | undefined;
	if (Array.isArray(results) && results.length > 0) {
		lines.push(`${results.length} places:`);
		for (const r of results) {
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
}

// ---------------------------------------------------------------------------
// Travel renderers
// ---------------------------------------------------------------------------

function renderTravelConnectionsText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const results = childContents ?? (c.results as Record<string, unknown>[] | undefined) ?? [];

	if (results.length > 0) {
		lines.push(`${results.length} connections:`);
		for (const r of results) {
			const origin = str(r.origin) ?? '';
			const dest = str(r.destination) ?? '';
			const dep = str(r.departure)?.slice(11, 16) ?? '';
			const arr = str(r.arrival)?.slice(11, 16) ?? '';
			const duration = str(r.duration) ?? '';
			const price = formatPrice(r.total_price ?? r.price, r.currency);
			const stops =
				typeof r.stops === 'number'
					? r.stops === 0
						? 'Direct'
						: `${r.stops} stops`
					: '';
			if (origin && dest) lines.push(`  ${origin} → ${dest}`);
			if (dep && arr)
				lines.push(`  ${dep} – ${arr}${duration ? `  (${duration})` : ''}`);
			if (price || stops)
				lines.push(`  ${[price, stops].filter(Boolean).join('  · ')}`);
			lines.push('');
		}
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} connections`);
	}
}

function renderTravelStaysText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const results = childContents ?? (c.results as Record<string, unknown>[] | undefined) ?? [];

	if (results.length > 0) {
		lines.push(`${results.length} stays:`);
		for (const r of results) {
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
}

function renderPriceCalendarText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const origin = str(c.origin) ?? '';
	const dest = str(c.destination) ?? '';
	if (origin && dest) lines.push(`${origin} → ${dest}`);
	const cheapest = c.cheapest_price;
	const currency = str(c.currency) ?? 'EUR';
	if (cheapest !== undefined && cheapest !== null) {
		lines.push(`From ${currency} ${cheapest}`);
	}
	const prices = c.prices as Array<Record<string, unknown>> | undefined;
	if (Array.isArray(prices) && prices.length > 0) {
		for (const p of prices.slice(0, 10)) {
			const date = str(p.date) ?? '';
			const price = p.price ?? p.amount;
			if (date && price !== undefined) lines.push(`  ${date}  ${currency} ${price}`);
		}
		if (prices.length > 10) lines.push(`  ... and ${prices.length - 10} more`);
	}
}

function renderFlightText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const fields: [string, unknown][] = [
		['Flight', c.flight_number ?? c.callsign],
		['Airline', c.airline],
		['Route', c.origin && c.destination ? `${c.origin} → ${c.destination}` : null],
		['Departure', c.departure],
		['Arrival', c.arrival],
		['Status', c.flight_status],
		['Aircraft', c.aircraft]
	];
	for (const [label, value] of fields) {
		if (value !== null && value !== undefined) {
			lines.push(`${label}: ${value}`);
		}
	}
}

// ---------------------------------------------------------------------------
// Content type renderers
// ---------------------------------------------------------------------------

function renderCodeDocsText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const results = c.results as Array<Record<string, unknown>> | undefined;
	const first = Array.isArray(results) ? results[0] : null;
	const libId =
		(first?.library as Record<string, unknown>)?.id ??
		first?.library_id ??
		str(c.library);
	if (libId) lines.push(`Library: ${String(libId)}`);
	const wordCount = first?.word_count ?? c.word_count;
	if (wordCount) lines.push(`${String(wordCount)} words`);
}

function renderWebReadText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const url = str(c.url);
	if (url) lines.push(url);
}

function renderMathText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const results = c.results as Array<Record<string, unknown>> | undefined;
	if (Array.isArray(results)) {
		for (const r of results) {
			const expr = str(r.expression) ?? str(r.input) ?? '';
			const result = str(r.result) ?? str(r.output) ?? '';
			if (expr && result) lines.push(`${expr} = ${result}`);
			else if (result) lines.push(result);
		}
	}
}

function renderReminderText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const prompt = str(c.prompt) ?? str(c.message) ?? str(c.reminder_text) ?? '';
	const time = str(c.trigger_at_formatted) ?? str(c.trigger_at) ?? '';
	if (prompt) lines.push(prompt);
	if (time) lines.push(`Time: ${time}`);
	if (c.is_repeating === true) lines.push('Repeating');
}

function renderImageGenerateText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const model = str(c.model);
	const prompt = str(c.prompt);
	if (model) lines.push(`Model: ${model}`);
	if (prompt) lines.push(`Prompt: ${trunc(prompt, 100)}`);
	lines.push('[generated image]');
}

function renderVideoTranscriptText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const title = str(c.title) ?? str(c.video_title) ?? '';
	const url = str(c.url) ?? str(c.video_url) ?? '';
	const channel = str(c.channel) ?? str(c.author) ?? '';
	if (title) lines.push(title);
	if (channel) lines.push(channel);
	if (url) lines.push(url);
}

function renderHealthSearchText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const results = childContents ?? [];

	if (results.length > 0) {
		lines.push(`${results.length} appointments:`);
		for (const r of results) {
			const slotDt = str(r.slot_datetime) ?? str(r.next_slot) ?? str(r.date) ?? '';
			const name = str(r.name) ?? str(r.doctor_name) ?? str(r.title) ?? '';
			const speciality = str(r.speciality) ?? '';
			const address = str(r.address) ?? '';
			if (slotDt) lines.push(`  ${slotDt}`);
			if (name) lines.push(`  ${name}${speciality ? ` · ${speciality}` : ''}`);
			if (address) lines.push(`  ${address}`);
			lines.push('');
		}
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} appointments`);
	}
}

function renderAudioTranscribeText(
	c: Record<string, unknown>,
	lines: string[]
): void {
	const duration = str(c.duration) ?? str(c.length) ?? '';
	const language = str(c.language) ?? '';
	if (duration) lines.push(`Duration: ${duration}`);
	if (language) lines.push(`Language: ${language}`);
	const text = str(c.text) ?? str(c.transcript) ?? '';
	if (text) lines.push(trunc(text, 200));
}

function renderHomeSearchText(
	c: Record<string, unknown>,
	lines: string[],
	childContents?: Record<string, unknown>[]
): void {
	const results = childContents ?? [];

	if (results.length > 0) {
		lines.push(`${results.length} listings:`);
		for (const r of results) {
			const title = str(r.title) ?? str(r.name) ?? '';
			const price = formatPrice(r.price ?? r.rent, r.currency);
			const address = str(r.address) ?? str(r.location) ?? '';
			if (title) lines.push(`  ${title}`);
			if (price) lines.push(`  ${price}`);
			if (address) lines.push(`  ${address}`);
			lines.push('');
		}
	} else {
		const count = resolveResultCount(c);
		if (count !== null) lines.push(`${count} listings`);
	}
}

// ---------------------------------------------------------------------------
// Direct type renderer
// ---------------------------------------------------------------------------

function renderDirectType(
	type: string,
	c: Record<string, unknown>
): string {
	const label = TYPE_LABELS[type] ?? type;
	const lines: string[] = [];

	switch (type) {
		case 'code':
		case 'code-code': {
			const lang = str(c.language) ?? '';
			const filename = str(c.filename) ?? '';
			const lineCount = c.line_count;
			const header = [filename, lang].filter(Boolean).join(' · ');
			if (header) lines.push(`**${label}** — ${header}`);
			else lines.push(`**${label}**`);
			if (lineCount) lines.push(`${lineCount} lines`);
			const code = str(c.code) ?? str(c.content) ?? '';
			if (code) {
				const codeLines = code.split('\n').slice(0, 6);
				lines.push('```' + (lang || ''));
				lines.push(...codeLines);
				if (code.split('\n').length > 6) lines.push('...');
				lines.push('```');
			}
			break;
		}

		case 'docs-doc':
		case 'doc': {
			const title = str(c.title) ?? str(c.filename) ?? '';
			const wordCount = c.word_count;
			lines.push(`**${label}**${title ? ` — ${title}` : ''}`);
			if (wordCount) lines.push(`${wordCount} words`);
			break;
		}

		case 'sheets-sheet':
		case 'sheet': {
			const title = str(c.title) ?? '';
			const rows = c.row_count ?? c.rows;
			const cols = c.col_count ?? c.cols;
			lines.push(`**${label}**${title ? ` — ${title}` : ''}`);
			if (rows && cols) lines.push(`${rows} rows × ${cols} columns`);
			const table = str(c.table) ?? str(c.content) ?? '';
			if (table) {
				const tableRows = table
					.split('\n')
					.filter((l) => l.trim().startsWith('|'))
					.slice(0, 4);
				lines.push(...tableRows);
			}
			break;
		}

		case 'pdf': {
			const filename = str(c.filename) ?? '';
			const pageCount = c.page_count;
			lines.push(`**${label}**${filename ? ` — ${filename}` : ''}`);
			if (pageCount) lines.push(`${pageCount} pages`);
			break;
		}

		case 'image': {
			const alt = str(c.alt) ?? str(c.caption) ?? str(c.filename) ?? '';
			lines.push(`**${label}**${alt ? ` — ${alt}` : ''}`);
			lines.push('[image]');
			break;
		}

		case 'web-website': {
			const title = str(c.title) ?? '';
			const url = str(c.url) ?? '';
			const desc = str(c.description) ?? str(c.snippet) ?? '';
			if (title) lines.push(`**${title}**`);
			if (url) lines.push(url);
			if (desc) lines.push(trunc(desc, 200));
			break;
		}

		case 'videos-video': {
			const title = str(c.title) ?? '';
			const channel = str(c.channel) ?? str(c.author) ?? '';
			const duration = str(c.duration) ?? '';
			const url = str(c.url) ?? str(c.link) ?? '';
			if (title) lines.push(`**${title}**`);
			if (channel || duration)
				lines.push([channel, duration].filter(Boolean).join('  '));
			if (url) lines.push(url);
			break;
		}

		case 'travel-connection': {
			const origin = str(c.origin) ?? '';
			const dest = str(c.destination) ?? '';
			const dep = str(c.departure)?.slice(11, 16) ?? '';
			const arr = str(c.arrival)?.slice(11, 16) ?? '';
			const price = formatPrice(c.total_price ?? c.price, c.currency);
			lines.push(`**${label}**`);
			if (origin && dest) lines.push(`${origin} → ${dest}`);
			if (dep && arr) lines.push(`${dep} – ${arr}`);
			if (price) lines.push(price);
			break;
		}

		case 'travel-stay': {
			const name = str(c.name) ?? str(c.hotel_name) ?? '';
			const price = formatPrice(c.total_price ?? c.price, c.currency);
			const rating = typeof c.rating === 'number' ? `★ ${c.rating}` : '';
			lines.push(`**${label}**${name ? ` — ${name}` : ''}`);
			if (rating) lines.push(rating);
			if (price) lines.push(price);
			break;
		}

		case 'maps':
		case 'maps-place': {
			const name = str(c.displayName) ?? str(c.name) ?? '';
			const address = str(c.formattedAddress) ?? str(c.address) ?? '';
			lines.push(`**${label}**${name ? ` — ${name}` : ''}`);
			if (address) lines.push(address);
			break;
		}

		case 'recording': {
			const duration = str(c.duration) ?? '';
			lines.push(`**${label}**`);
			if (duration) lines.push(`Duration: ${duration}`);
			lines.push('[audio recording]');
			break;
		}

		case 'mail-email': {
			const subject = str(c.subject) ?? '';
			const receiver = str(c.receiver) ?? '';
			lines.push(`**${label}**${subject ? ` — ${subject}` : ''}`);
			if (receiver) lines.push(`To: ${receiver}`);
			break;
		}

		case 'math-plot':
			lines.push(`**${label}**`);
			lines.push('[mathematical plot]');
			break;

		case 'events-event': {
			const name = str(c.name) ?? str(c.title) ?? '';
			const date = str(c.date) ?? str(c.start_date) ?? '';
			const venue = str(c.venue) ?? str(c.location) ?? '';
			lines.push(`**${label}**${name ? ` — ${name}` : ''}`);
			if (date || venue)
				lines.push([date, venue].filter(Boolean).join(' @ '));
			break;
		}

		case 'health-appointment': {
			const slotDt = str(c.slot_datetime) ?? str(c.next_slot) ?? str(c.date) ?? '';
			const name = str(c.name) ?? str(c.doctor_name) ?? str(c.title) ?? '';
			lines.push(`**${label}**${name ? ` — ${name}` : ''}`);
			if (slotDt) lines.push(slotDt);
			break;
		}

		case 'shopping-product': {
			const title = str(c.title) ?? str(c.name) ?? '';
			const price = formatPrice(c.price, c.currency);
			const url = str(c.url) ?? str(c.link) ?? '';
			if (title) lines.push(`**${title}**`);
			if (price) lines.push(price);
			if (url) lines.push(url);
			break;
		}

		case 'images-image-result': {
			const title = str(c.title) ?? '';
			const source = str(c.source) ?? str(c.url) ?? '';
			lines.push(`**${label}**${title ? ` — ${title}` : ''}`);
			if (source) lines.push(source);
			break;
		}

		case 'news-article': {
			const title = str(c.title) ?? '';
			const url = str(c.url) ?? str(c.link) ?? '';
			const desc = str(c.description) ?? str(c.snippet) ?? '';
			if (title) lines.push(`**${title}**`);
			if (url) lines.push(url);
			if (desc) lines.push(trunc(desc, 200));
			break;
		}

		case 'home-listing': {
			const title = str(c.title) ?? str(c.name) ?? '';
			const price = formatPrice(c.price ?? c.rent, c.currency);
			const address = str(c.address) ?? str(c.location) ?? '';
			lines.push(`**${label}**${title ? ` — ${title}` : ''}`);
			if (price) lines.push(price);
			if (address) lines.push(address);
			break;
		}

		case 'focus-mode-activation': {
			const modeName = str(c.focus_mode_name) ?? '';
			lines.push(`**${label}**${modeName ? ` — ${modeName}` : ''}`);
			break;
		}

		default: {
			lines.push(`**${label}**`);
			// Generic fallback
			let count = 0;
			for (const [k, v] of Object.entries(c)) {
				if (count >= 4) break;
				if (
					v !== null &&
					v !== undefined &&
					typeof v !== 'object' &&
					!k.startsWith('_')
				) {
					lines.push(`${k}: ${trunc(String(v), 80)}`);
					count++;
				}
			}
		}
	}

	return lines.join('\n');
}
