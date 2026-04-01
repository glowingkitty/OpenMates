/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Example chats loading test: verifies that community demo chats (example chats)
 * load for NEW USERS (clean browser context, no IndexedDB cache) in the
 * for-everyone demo chat.
 *
 * Bug history this test suite guards against:
 * - commit TBD: Production demo chats had empty slug fields in DB. The list endpoint
 *   generated fallback slugs from titles, but the individual endpoint only looked up
 *   by stored slug field → 404 for all individual demo fetches for new users.
 *
 * Test strategy:
 *   1. Open the app with a clean browser (simulating a brand-new user)
 *   2. Monitor the /v1/demo/ API calls for success/failure
 *   3. Verify ExampleChatsGroup renders with actual chat cards
 *   4. Verify all demo slugs from the list endpoint can be individually fetched
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('@playwright/test');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.describe('Example chats loading for new users', () => {
	test('community demo chats appear in for-everyone intro chat', async ({ page }) => {
		test.setTimeout(60000);

		// ─── Console + network logging for diagnostics ──────────────────────
		const consoleLogs: string[] = [];
		const networkRequests: string[] = [];

		page.on('console', (message: any) => {
			const text = message.text();
			consoleLogs.push(`[${message.type()}] ${text}`);
		});

		page.on('response', (response: any) => {
			const url = response.url();
			if (url.includes('/v1/demo/')) {
				networkRequests.push(`${response.status()} ${url}`);
			}
		});

		// ─── Navigate as a fresh user (clean browser context) ───────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Give extra time for community demos to load (they fetch sequentially)
		// Each demo chat requires an individual API call after the list is fetched
		await page.waitForTimeout(8000);

		// ─── Verify the ExampleChatsGroup rendered with cards ────────────────
		const exampleChatsWrapper = page.getByTestId('example-chats-group-wrapper');
		const chatCards = page.getByTestId('example-chats-group').locator('[data-testid="chat-embed-card"]');

		const wrapperCount = await exampleChatsWrapper.count();
		const cardCount = await chatCards.count();

		// Check API calls AFTER the timeout (they may not have fired by networkidle)
		const demoChatsApiCalled = networkRequests.some((r) => r.includes('/v1/demo/chats'));

		// Log diagnostics
		console.log('\n--- EXAMPLE CHATS DIAGNOSTICS ---');
		console.log(`Demo chats API called: ${demoChatsApiCalled}`);
		console.log(`API requests to /v1/demo/: ${networkRequests.length}`);
		networkRequests.forEach((r) => console.log(`  ${r}`));
		console.log(`ExampleChatsGroup wrappers found: ${wrapperCount}`);
		console.log(`Chat embed cards found: ${cardCount}`);

		// Filter relevant console logs
		const demoLogs = consoleLogs.filter(
			(l) =>
				l.includes('loadCommunityDemos') ||
				l.includes('CommunityDemoStore') ||
				l.includes('ExampleChatsGroup') ||
				l.includes('community demo')
		);
		console.log(`\nRelevant console logs (${demoLogs.length}):`);
		demoLogs.forEach((l) => console.log(`  ${l}`));

		// Check for errors in console
		const errorLogs = consoleLogs.filter(
			(l) => l.startsWith('[error]') && (l.includes('demo') || l.includes('community'))
		);
		if (errorLogs.length > 0) {
			console.log(`\nError logs related to demos:`);
			errorLogs.forEach((l) => console.log(`  ${l}`));
		}
		console.log('--- END DIAGNOSTICS ---\n');

		// ─── Assertions ─────────────────────────────────────────────────────

		// The demo chats list API must have been called
		expect(
			demoChatsApiCalled,
			'Expected /v1/demo/chats API to be called for new user'
		).toBe(true);

		// The ExampleChatsGroup wrapper must exist (placeholder was rendered)
		expect(wrapperCount, 'ExampleChatsGroup wrapper should be visible').toBeGreaterThan(0);

		// At least 1 example chat card should be rendered
		expect(cardCount, 'Expected at least 1 example chat card for new users').toBeGreaterThan(0);

		// Verify cards have titles
		if (cardCount > 0) {
			const firstCardTitle = await chatCards.first().getByTestId('card-title').textContent();
			expect(firstCardTitle?.trim().length, 'Chat card should have a non-empty title').toBeGreaterThan(0);
		}
	});

	test('all demo chat slugs from list endpoint are individually fetchable', async ({ page }) => {
		test.setTimeout(60000);

		// Navigate first so the browser has a proper origin for CORS
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });

		// Use page.evaluate to call the API from the browser context
		// (Playwright's request context uses the frontend base URL, not the API domain)
		const results = await page.evaluate(async () => {
			// Discover API URL from the app's environment
			const origin = window.location.origin;
			// Map frontend domain → API domain
			// app.dev.openmates.org → api.dev.openmates.org
			// openmates.org → api.openmates.org
			let apiBase = origin.replace('://app.', '://api.');
			if (!apiBase.includes('://api.')) {
				apiBase = origin.replace('://', '://api.');
			}

			const listRes = await fetch(`${apiBase}/v1/demo/chats?lang=en`);
			if (!listRes.ok) return { error: `List failed: ${listRes.status}`, demos: [], failures: [] };

			const data = await listRes.json();
			const demos = data.demo_chats || [];
			const failures: string[] = [];

			// Test each demo's individual endpoint (slug-based lookup)
			for (const demo of demos) {
				try {
					const chatRes = await fetch(`${apiBase}/v1/demo/chat/${demo.demo_id}?lang=en`);
					if (!chatRes.ok) {
						failures.push(`${demo.demo_id} → ${chatRes.status}`);
					}
				} catch (e: any) {
					failures.push(`${demo.demo_id} → error: ${e.message}`);
				}
			}

			return { error: null, demos: demos.map((d: any) => d.demo_id), failures };
		});

		console.log(`\n--- DEMO CHAT SLUG LOOKUP ---`);
		console.log(`Total demos: ${results.demos.length}`);
		if (results.failures.length > 0) {
			console.log(`FAILURES (${results.failures.length}):`);
			results.failures.forEach((f: string) => console.log(`  ${f}`));
		} else {
			console.log('All slugs resolved successfully');
		}
		console.log(`--- END ---\n`);

		expect(results.error, 'List endpoint should succeed').toBeNull();
		expect(results.demos.length, 'Should have demo chats').toBeGreaterThan(0);
		expect(
			results.failures,
			`All demo chats should be fetchable by slug. Failed: ${results.failures.join(', ')}`
		).toEqual([]);
	});
});
