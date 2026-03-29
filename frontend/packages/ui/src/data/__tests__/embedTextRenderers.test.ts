// Unit tests for the embed text renderer registry
//
// Bug history this test suite guards against:
// - OPE-7 (0c521b2): Copy message showed raw JSON embed placeholders.
//   First fix used TipTap doc walking which missed embedPreviewLarge nodes.
//   This registry-based approach renders per-domain text alongside Svelte previews.

import { describe, it, expect } from 'vitest';
import { renderEmbedAsText, EMBED_TEXT_RENDERERS, str, trunc, formatPrice } from '../embedTextRenderers';

describe('EMBED_TEXT_RENDERERS registry', () => {
	it('should have entries for all major embed types', () => {
		const expectedKeys = [
			'app:web:search', 'app:web:read', 'web-website',
			'app:events:search', 'events-event',
			'app:videos:search', 'videos-video', 'app:videos:get_transcript',
			'app:travel:search_connections', 'app:travel:search_stays', 'travel-connection', 'travel-stay',
			'app:images:generate', 'image', 'images-image-result',
			'app:maps:search', 'maps-place', 'maps',
			'app:home:search', 'home-listing',
			'app:health:search_appointments', 'health-appointment',
			'app:mail:search', 'mail-email',
			'app:math:calculate', 'math-plot',
			'code-code', 'app:code:get_docs',
			'docs-doc', 'sheets-sheet', 'pdf', 'recording',
			'app:reminder:set-reminder',
			'app:shopping:search_products',
			'app:news:search',
			'focus-mode-activation'
		];
		for (const key of expectedKeys) {
			expect(EMBED_TEXT_RENDERERS[key], `Missing renderer for "${key}"`).toBeDefined();
		}
	});
});

describe('renderEmbedAsText', () => {
	// ── Web domain ──────────────────────────────────────────────────

	it('web search without children shows count', () => {
		const result = renderEmbedAsText('app:web:search', {
			query: 'test query',
			result_count: 10
		});
		expect(result).toContain('**Web Search**');
		expect(result).toContain('test query');
		expect(result).toContain('10 results');
	});

	it('web search with children shows individual results', () => {
		const children = [
			{ title: 'Result 1', url: 'https://example.com/1', description: 'Desc 1' },
			{ title: 'Result 2', url: 'https://example.com/2', snippet: 'Snippet 2' }
		];
		const result = renderEmbedAsText('app:web:search', { query: 'test' }, children);
		expect(result).toContain('2 results:');
		expect(result).toContain('Result 1');
		expect(result).toContain('https://example.com/1');
		expect(result).toContain('Result 2');
	});

	it('website renders title, URL, description', () => {
		const result = renderEmbedAsText('web-website', {
			title: 'Example', url: 'https://example.com', description: 'A site'
		});
		expect(result).toContain('**Example**');
		expect(result).toContain('https://example.com');
		expect(result).toContain('A site');
	});

	// ── Events domain ───────────────────────────────────────────────

	it('event search with children shows events', () => {
		const children = [
			{ name: 'AI Meetup', date: '2026-04-05', venue: 'Berlin' },
			{ title: 'Hack Night', start_date: '2026-04-12', location: 'Munich' }
		];
		const result = renderEmbedAsText('app:events:search', {
			query: 'AI meetups'
		}, children);
		expect(result).toContain('**Event Search**');
		expect(result).toContain('AI meetups');
		expect(result).toContain('AI Meetup');
		expect(result).toContain('Berlin');
		expect(result).toContain('Hack Night');
	});

	it('individual event renders name and date', () => {
		const result = renderEmbedAsText('events-event', {
			name: 'Tech Talk', date: '2026-04-01', venue: 'co.up'
		});
		expect(result).toContain('**Tech Talk**');
		expect(result).toContain('2026-04-01');
		expect(result).toContain('co.up');
	});

	// ── Code domain ─────────────────────────────────────────────────

	it('code embed renders language and snippet', () => {
		const result = renderEmbedAsText('code-code', {
			language: 'typescript',
			filename: 'utils.ts',
			line_count: 42,
			code: 'const x = 1;\nconst y = 2;'
		});
		expect(result).toContain('**Code**');
		expect(result).toContain('utils.ts');
		expect(result).toContain('42 lines');
		expect(result).toContain('const x = 1;');
	});

	// ── Travel domain ───────────────────────────────────────────────

	it('travel connections with children shows routes', () => {
		const children = [{
			origin: 'Berlin', destination: 'Paris',
			departure: '2026-04-01T08:30:00', arrival: '2026-04-01T12:45:00',
			total_price: 89, currency: 'EUR', stops: 0
		}];
		const result = renderEmbedAsText('app:travel:search_connections', {
			query: 'Berlin to Paris'
		}, children);
		expect(result).toContain('Berlin → Paris');
		expect(result).toContain('08:30 – 12:45');
		expect(result).toContain('EUR 89');
		expect(result).toContain('Direct');
	});

	// ── Home domain ─────────────────────────────────────────────────

	it('home search with children shows listings', () => {
		const children = [
			{ title: '2BR Apartment', price: 1200, currency: 'EUR', address: 'Berlin Mitte' }
		];
		const result = renderEmbedAsText('app:home:search', { query: 'Berlin apartments' }, children);
		expect(result).toContain('**Home Search**');
		expect(result).toContain('2BR Apartment');
		expect(result).toContain('EUR 1200');
		expect(result).toContain('Berlin Mitte');
	});

	// ── Image domain ────────────────────────────────────────────────

	it('image generate shows model and prompt', () => {
		const result = renderEmbedAsText('app:images:generate', {
			model: 'dall-e-3', prompt: 'A cat on a rainbow'
		});
		expect(result).toContain('Model: dall-e-3');
		expect(result).toContain('Prompt: A cat on a rainbow');
		expect(result).toContain('[image]');
	});

	// ── Other types ─────────────────────────────────────────────────

	it('PDF renders filename and pages', () => {
		const result = renderEmbedAsText('pdf', { filename: 'report.pdf', page_count: 15 });
		expect(result).toContain('report.pdf');
		expect(result).toContain('15 pages');
	});

	it('reminder renders prompt and time', () => {
		const result = renderEmbedAsText('app:reminder:set-reminder', {
			prompt: 'Buy groceries', trigger_at_formatted: 'Tomorrow 9 AM'
		});
		expect(result).toContain('Buy groceries');
		expect(result).toContain('Time: Tomorrow 9 AM');
	});

	it('math calculate renders expressions', () => {
		const result = renderEmbedAsText('app:math:calculate', {
			results: [{ expression: '2^10', result: '1024' }]
		});
		expect(result).toContain('2^10 = 1024');
	});

	it('sheet renders dimensions', () => {
		const result = renderEmbedAsText('sheets-sheet', {
			title: 'Budget', row_count: 50, col_count: 8
		});
		expect(result).toContain('Budget');
		expect(result).toContain('50 rows × 8 columns');
	});

	// ── Fallback ────────────────────────────────────────────────────

	it('unknown key produces fallback with key label', () => {
		const result = renderEmbedAsText('unknown-type', { foo: 'bar' });
		expect(result).toContain('[unknown-type]');
		expect(result).toContain('foo: bar');
	});
});

describe('helpers', () => {
	it('str returns null for empty/non-string', () => {
		expect(str('')).toBeNull();
		expect(str(null)).toBeNull();
		expect(str(42)).toBeNull();
		expect(str('hello')).toBe('hello');
	});

	it('trunc truncates long strings', () => {
		expect(trunc('short', 10)).toBe('short');
		expect(trunc('a very long string here', 10)).toBe('a very lon…');
	});

	it('formatPrice formats correctly', () => {
		expect(formatPrice(89, 'eur')).toBe('EUR 89');
		expect(formatPrice(null, 'eur')).toBe('');
		expect(formatPrice(42, null)).toBe('42');
	});
});
