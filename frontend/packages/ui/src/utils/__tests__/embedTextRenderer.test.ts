// Unit tests for embedTextRenderer — shared plain-text embed renderer
//
// Bug history this test suite guards against:
// - OPE-7: Copy message output showed raw JSON embed placeholders instead of
//   human-readable text previews. This renderer was created to fix that.

import { describe, it, expect } from 'vitest';
import { renderEmbedAsText } from '../embedTextRenderer';

describe('renderEmbedAsText', () => {
	// ── Direct types ──────────────────────────────────────────────────

	describe('website embed', () => {
		it('should render title, URL, and description', () => {
			const result = renderEmbedAsText('web-website', null, null, {
				title: 'Example Article',
				url: 'https://example.com/article',
				description: 'A great article about testing'
			});
			expect(result).toContain('**Example Article**');
			expect(result).toContain('https://example.com/article');
			expect(result).toContain('A great article about testing');
		});

		it('should handle missing fields gracefully', () => {
			const result = renderEmbedAsText('web-website', null, null, {
				url: 'https://example.com'
			});
			expect(result).toContain('https://example.com');
		});
	});

	describe('code embed', () => {
		it('should render language and filename', () => {
			const result = renderEmbedAsText('code-code', null, null, {
				language: 'typescript',
				filename: 'utils.ts',
				line_count: 42,
				code: 'const x = 1;\nconst y = 2;'
			});
			expect(result).toContain('**Code**');
			expect(result).toContain('utils.ts');
			expect(result).toContain('typescript');
			expect(result).toContain('42 lines');
			expect(result).toContain('const x = 1;');
		});

		it('should truncate long code to 6 lines', () => {
			const code = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`).join('\n');
			const result = renderEmbedAsText('code-code', null, null, {
				language: 'python',
				code
			});
			expect(result).toContain('line 1');
			expect(result).toContain('line 6');
			expect(result).toContain('...');
			expect(result).not.toContain('line 7');
		});
	});

	describe('video embed', () => {
		it('should render title, channel, and URL', () => {
			const result = renderEmbedAsText('videos-video', null, null, {
				title: 'Cool Video',
				channel: 'TestChannel',
				duration: '10:30',
				url: 'https://youtube.com/watch?v=abc'
			});
			expect(result).toContain('**Cool Video**');
			expect(result).toContain('TestChannel');
			expect(result).toContain('10:30');
			expect(result).toContain('https://youtube.com/watch?v=abc');
		});
	});

	describe('maps embed', () => {
		it('should render name and address', () => {
			const result = renderEmbedAsText('maps-place', null, null, {
				displayName: 'Central Park',
				formattedAddress: 'New York, NY, USA'
			});
			expect(result).toContain('Central Park');
			expect(result).toContain('New York, NY, USA');
		});
	});

	describe('PDF embed', () => {
		it('should render filename and page count', () => {
			const result = renderEmbedAsText('pdf', null, null, {
				filename: 'report.pdf',
				page_count: 15
			});
			expect(result).toContain('report.pdf');
			expect(result).toContain('15 pages');
		});
	});

	describe('image embed', () => {
		it('should render alt text and image placeholder', () => {
			const result = renderEmbedAsText('image', null, null, {
				alt: 'A sunset photo',
				filename: 'sunset.jpg'
			});
			expect(result).toContain('A sunset photo');
			expect(result).toContain('[image]');
		});
	});

	describe('travel connection', () => {
		it('should render origin, destination, and price', () => {
			const result = renderEmbedAsText('travel-connection', null, null, {
				origin: 'Berlin',
				destination: 'Paris',
				departure: '2026-04-01T08:30:00',
				arrival: '2026-04-01T12:45:00',
				total_price: 89,
				currency: 'EUR'
			});
			expect(result).toContain('Berlin → Paris');
			expect(result).toContain('08:30');
			expect(result).toContain('12:45');
			expect(result).toContain('EUR 89');
		});
	});

	describe('mail email', () => {
		it('should render subject and receiver', () => {
			const result = renderEmbedAsText('mail-email', null, null, {
				subject: 'Meeting Tomorrow',
				receiver: 'team@example.com'
			});
			expect(result).toContain('Meeting Tomorrow');
			expect(result).toContain('To: team@example.com');
		});
	});

	describe('recording embed', () => {
		it('should render duration and placeholder', () => {
			const result = renderEmbedAsText('recording', null, null, {
				duration: '2:30'
			});
			expect(result).toContain('Duration: 2:30');
			expect(result).toContain('[audio recording]');
		});
	});

	describe('sheet embed', () => {
		it('should render dimensions', () => {
			const result = renderEmbedAsText('sheets-sheet', null, null, {
				title: 'Budget 2026',
				row_count: 50,
				col_count: 8
			});
			expect(result).toContain('Budget 2026');
			expect(result).toContain('50 rows × 8 columns');
		});
	});

	// ── Composite types ───────────────────────────────────────────────

	describe('web search composite', () => {
		it('should render query and result count without children', () => {
			const result = renderEmbedAsText('', 'web', 'search', {
				query: 'iPhone 18 rumors',
				result_count: 10
			});
			expect(result).toContain('**Web Search**');
			expect(result).toContain('iPhone 18 rumors');
			expect(result).toContain('10 results');
		});

		it('should render individual results when children provided', () => {
			const children = [
				{ title: 'NY Times Article', url: 'https://nytimes.com/article', description: 'Latest news' },
				{ title: 'MacRumors Post', url: 'https://macrumors.com/post', snippet: 'Rumors suggest' }
			];
			const result = renderEmbedAsText('', 'web', 'search', {
				query: 'iPhone 18 rumors',
				result_count: 2
			}, children);
			expect(result).toContain('2 results');
			expect(result).toContain('NY Times Article');
			expect(result).toContain('https://nytimes.com/article');
			expect(result).toContain('MacRumors Post');
		});
	});

	describe('travel connections composite', () => {
		it('should render route and price from children', () => {
			const children = [
				{
					origin: 'Berlin',
					destination: 'Munich',
					departure: '2026-04-01T06:00:00',
					arrival: '2026-04-01T10:30:00',
					duration: '4h 30m',
					total_price: 45,
					currency: 'EUR',
					stops: 0
				}
			];
			const result = renderEmbedAsText('', 'travel', 'search_connections', {
				query: 'Berlin to Munich'
			}, children);
			expect(result).toContain('**Travel Connections**');
			expect(result).toContain('Berlin → Munich');
			expect(result).toContain('06:00 – 10:30');
			expect(result).toContain('EUR 45');
			expect(result).toContain('Direct');
		});
	});

	describe('image generate composite', () => {
		it('should render model and prompt', () => {
			const result = renderEmbedAsText('', 'images', 'generate', {
				model: 'dall-e-3',
				prompt: 'A cat sitting on a rainbow'
			});
			expect(result).toContain('Model: dall-e-3');
			expect(result).toContain('Prompt: A cat sitting on a rainbow');
			expect(result).toContain('[generated image]');
		});
	});

	describe('reminder composite', () => {
		it('should render reminder text and time', () => {
			const result = renderEmbedAsText('', 'reminder', 'set-reminder', {
				prompt: 'Buy groceries',
				trigger_at_formatted: 'Tomorrow at 9:00 AM'
			});
			expect(result).toContain('Buy groceries');
			expect(result).toContain('Time: Tomorrow at 9:00 AM');
		});
	});

	describe('math calculate composite', () => {
		it('should render expression and result', () => {
			const result = renderEmbedAsText('', 'math', 'calculate', {
				results: [
					{ expression: '2^10', result: '1024' },
					{ expression: 'sqrt(144)', result: '12' }
				]
			});
			expect(result).toContain('2^10 = 1024');
			expect(result).toContain('sqrt(144) = 12');
		});
	});

	describe('video transcript composite', () => {
		it('should render title, channel, and URL', () => {
			const result = renderEmbedAsText('', 'videos', 'get_transcript', {
				title: 'Tech Talk 2026',
				channel: 'TechConf',
				url: 'https://youtube.com/watch?v=xyz'
			});
			expect(result).toContain('Tech Talk 2026');
			expect(result).toContain('TechConf');
			expect(result).toContain('https://youtube.com/watch?v=xyz');
		});
	});

	// ── Edge cases ────────────────────────────────────────────────────

	describe('edge cases', () => {
		it('should handle empty content object without crashing', () => {
			const result = renderEmbedAsText('web-website', null, null, {});
			expect(typeof result).toBe('string');
		});

		it('should handle unknown direct type with fallback', () => {
			const result = renderEmbedAsText('unknown-type', null, null, {
				foo: 'bar',
				count: 42
			});
			// Falls through to composite default which shows generic fields
			expect(result).toContain('foo: bar');
		});

		it('should handle unknown composite type with generic output', () => {
			const result = renderEmbedAsText('', 'unknown', 'skill', {
				title: 'Something',
				value: '42'
			});
			expect(result).toContain('title: Something');
		});

		it('should truncate long descriptions', () => {
			const longDesc = 'A'.repeat(300);
			const result = renderEmbedAsText('web-website', null, null, {
				title: 'Test',
				description: longDesc
			});
			expect(result.length).toBeLessThan(500);
			expect(result).toContain('…');
		});
	});
});
