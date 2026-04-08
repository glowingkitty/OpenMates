/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Unauthenticated app load test: verifies the core experience for a brand-new
 * visitor who has never signed up — the most common first impression.
 *
 * Bug history this test suite guards against:
 * - OPE-245: Daily inspirations returned empty when celery beat missed its
 *   06:30 UTC scheduled run after a container restart. The endpoint now falls
 *   back to yesterday's defaults, and the API triggers the task on startup
 *   if today's defaults are missing.
 *
 * Test covers:
 *   1. App loads without errors for a clean browser (no auth, no IndexedDB)
 *   2. The for-everyone demo chat opens automatically within a few seconds
 *   3. The new-chat button opens the new chat interface
 *   4. Daily inspiration banner appears with actual content in the new chat view
 *   5. No missing translation keys visible on the page
 *
 * No credentials required — this tests the non-authenticated flow.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');

test.describe('Unauthenticated app load', () => {
	const consoleLogs: string[] = [];
	const consoleErrors: string[] = [];
	const networkRequests: string[] = [];

	test.beforeEach(async () => {
		consoleLogs.length = 0;
		consoleErrors.length = 0;
		networkRequests.length = 0;
	});

	// eslint-disable-next-line no-empty-pattern
	test.afterEach(async ({}, testInfo: any) => {
		if (testInfo.status !== 'passed') {
			console.log('\n--- DEBUG INFO ON FAILURE ---');
			console.log('\n[RECENT CONSOLE LOGS]');
			consoleLogs.slice(-30).forEach((log) => console.log(log));
			console.log('\n[CONSOLE ERRORS]');
			consoleErrors.forEach((err) => console.log(err));
			console.log('\n[NETWORK REQUESTS]');
			networkRequests.slice(-20).forEach((req) => console.log(req));
			console.log('\n--- END DEBUG INFO ---\n');
		}
	});

	test('app loads, shows for-everyone chat, and daily inspirations appear in new chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);

		// ─── Console + network logging for diagnostics ──────────────────────
		page.on('console', (msg: any) => {
			const timestamp = new Date().toISOString();
			const text = `[${timestamp}] [${msg.type()}] ${msg.text()}`;
			consoleLogs.push(text);
			if (msg.type() === 'error') {
				consoleErrors.push(text);
			}
		});

		page.on('response', (response: any) => {
			const url = response.url();
			if (url.includes('/v1/')) {
				networkRequests.push(`${response.status()} ${url}`);
			}
		});

		// ─── 1. Navigate as a fresh user (clean browser context) ────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// ─── 2. Verify the for-everyone demo chat opens automatically ───────
		// The app auto-navigates to the for-everyone intro chat for new visitors.
		// The chat ID appears in the URL hash.
		await page.waitForFunction(
			() => window.location.hash.includes('demo-for-everyone'),
			null,
			{ timeout: 15000 }
		);
		console.log('[unauthenticated-load] for-everyone demo chat opened in URL hash');

		// Verify the active chat container is visible
		const activeChatContainer = page.getByTestId('active-chat-container');
		await expect(activeChatContainer).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] Active chat container is visible');

		// ─── 3. Click the new-chat button to open the new chat interface ────
		const newChatButton = page.getByTestId('new-chat-button');
		await expect(newChatButton).toBeVisible({ timeout: 10000 });
		await newChatButton.click();
		console.log('[unauthenticated-load] Clicked new-chat button');

		// Wait for the message editor to appear (indicates new chat view is open)
		const messageEditor = page.getByTestId('message-editor');
		await expect(messageEditor).toBeVisible({ timeout: 10000 });
		console.log('[unauthenticated-load] New chat interface opened (message editor visible)');

		// ─── 4. Verify daily inspiration banner appears with content ────────
		// The banner should load from /v1/default-inspirations for unauthenticated
		// users. It may take a moment as the server defaults are fetched async.
		const inspirationBanner = page.getByTestId('daily-inspiration-banner').first();
		await expect(inspirationBanner).toBeVisible({ timeout: 15000 });
		console.log('[unauthenticated-load] Daily inspiration banner is visible');

		// Verify the banner has actual text content (not empty / loading placeholder)
		const bannerText = await inspirationBanner.textContent();
		expect(
			bannerText?.trim().length,
			'Daily inspiration banner should have non-empty text content'
		).toBeGreaterThan(5);
		console.log(
			`[unauthenticated-load] Banner text verified (${bannerText?.trim().length} chars)`
		);

		// Verify the /v1/default-inspirations endpoint was called and succeeded
		const inspirationApiCalled = networkRequests.some(
			(r) => r.includes('/v1/default-inspirations') && r.startsWith('200')
		);
		expect(
			inspirationApiCalled,
			'Expected /v1/default-inspirations API call to succeed (200). ' +
				`Requests seen: ${networkRequests.filter((r) => r.includes('inspiration')).join(', ') || 'none'}`
		).toBe(true);
		console.log('[unauthenticated-load] /v1/default-inspirations returned 200');

		// ─── 5. No missing translations ─────────────────────────────────────
		await assertNoMissingTranslations(page);
		console.log('[unauthenticated-load] No missing translations detected');

		console.log('[unauthenticated-load] All checks passed');
	});
});
