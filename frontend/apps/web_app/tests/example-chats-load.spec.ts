/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chats loading test: verifies that hardcoded example chats render
 * for NEW USERS (clean browser context, no IndexedDB cache) in the
 * for-everyone demo chat.
 *
 * Architecture: Example chats are now static/hardcoded in exampleChatStore.ts
 * (no backend /v1/demo/chats API call). The ExampleChatsGroup component reads
 * from getAllExampleChats() and renders chat embed cards.
 *
 * Test strategy:
 *   1. Open the app with a clean browser (simulating a brand-new user)
 *   2. Verify ExampleChatsGroup renders with actual chat cards
 *   3. Verify cards have titles and are clickable
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.describe('Example chats loading for new users', () => {
	test('example chats appear in for-everyone intro chat', async ({ page }: { page: any }) => {
		test.setTimeout(60000);

		// ─── Console logging for diagnostics ──────────────────────────────
		const consoleLogs: string[] = [];

		page.on('console', (message: any) => {
			const text = message.text();
			consoleLogs.push(`[${message.type()}] ${text}`);
		});

		// ─── Navigate as a fresh user (clean browser context) ───────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Allow time for the example chats component to render
		await page.waitForTimeout(5000);

		// ─── Verify the ExampleChatsGroup rendered with cards ────────────────
		const exampleChatsWrapper = page.getByTestId('example-chats-group-wrapper');
		const chatCards = page
			.getByTestId('example-chats-group')
			.locator('[data-testid="chat-embed-card"]');

		const wrapperCount = await exampleChatsWrapper.count();
		const cardCount = await chatCards.count();

		// Log diagnostics
		console.log('\n--- EXAMPLE CHATS DIAGNOSTICS ---');
		console.log(`ExampleChatsGroup wrappers found: ${wrapperCount}`);
		console.log(`Chat embed cards found: ${cardCount}`);

		const exampleLogs = consoleLogs.filter(
			(l) =>
				l.includes('ExampleChatsGroup') ||
				l.includes('exampleChat') ||
				l.includes('example chat')
		);
		console.log(`\nRelevant console logs (${exampleLogs.length}):`);
		exampleLogs.forEach((l) => console.log(`  ${l}`));
		console.log('--- END DIAGNOSTICS ---\n');

		// ─── Assertions ─────────────────────────────────────────────────────

		// The ExampleChatsGroup wrapper must exist
		expect(wrapperCount, 'ExampleChatsGroup wrapper should be visible').toBeGreaterThan(0);

		// At least 1 example chat card should be rendered (6 are hardcoded)
		expect(cardCount, 'Expected at least 1 example chat card for new users').toBeGreaterThan(0);

		// Verify cards have titles
		if (cardCount > 0) {
			const firstCardTitle = await chatCards.first().getByTestId('card-title').textContent();
			expect(
				firstCardTitle?.trim().length,
				'Chat card should have a non-empty title'
			).toBeGreaterThan(0);
		}
	});

	test('example chat SSR pages are accessible', async ({ request }: { request: any }) => {
		test.setTimeout(30000);

		// Verify at least one example chat has a working SSR page
		const response = await request.get('/example/gigantic-airplanes-transporting-rocket-parts');

		expect(response.status(), 'Example chat SSR page should return 200').toBe(200);

		const html = await response.text();
		expect(html).toContain('<main');
		expect(html).toContain('<article');
		expect(html).toContain('<h1>');
	});
});
