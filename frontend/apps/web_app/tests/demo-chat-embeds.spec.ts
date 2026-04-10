/* eslint-disable no-console */
/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Demo chat embed rendering test: verifies that embeds inside community demo
 * chats actually render for unauthenticated users — not just that the chats
 * load, but that inline embed references ([!](embed:ref), [text](embed:ref))
 * and block embeds (```json with embed_id) all resolve and display content.
 *
 * Bug this guards against:
 *   embed_ref → embed_id mappings were never registered for demo (cleartext)
 *   embeds, so EmbedPreviewLarge / EmbedInlineLink failed to resolve them
 *   and showed perpetual loading spinners or empty cards.
 *
 * Test strategy:
 *   1. Navigate to the app and wait for demo chats to load
 *   2. Click into an example chat card that has embeds
 *   3. Verify embeds actually render (data-testid="embed-preview" with status="finished")
 *   4. No credentials required — tests the unauthenticated public flow
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

test.describe('Demo chat embed rendering', () => {
	test('embeds inside demo chats render for unauthenticated users', async ({ page }) => {
		test.setTimeout(90000);

		// ─── Console logging for diagnostics ────────────────────────────────
		const consoleLogs: string[] = [];
		page.on('console', (message: any) => {
			const text = message.text();
			if (
				text.includes('registerDemoEmbedRefs') ||
				text.includes('loadCommunityDemos') ||
				text.includes('[embedResolver]')
			) {
				consoleLogs.push(`[${message.type()}] ${text}`);
			}
		});

		// ─── Navigate as a fresh user ───────────────────────────────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// Wait for community demos to load (they fetch sequentially from the API)
		await page.waitForTimeout(10000);

		// ─── Find and click an example chat card ────────────────────────────
		// The ExampleChatsGroup renders cards with data-testid="chat-embed-card"
		const chatCards = page.getByTestId('example-chats-group').locator('[data-testid="chat-embed-card"]');
		const cardCount = await chatCards.count();

		console.log(`\n--- DEMO CHAT EMBED TEST ---`);
		console.log(`Example chat cards found: ${cardCount}`);

		expect(cardCount, 'Expected at least 1 example chat card').toBeGreaterThan(0);

		// Click the first example chat card to navigate into it
		await chatCards.first().click();

		// Wait for the chat view to load and embeds to render
		// The assistant message should appear with embed previews
		const assistantMessage = page.getByTestId('message-assistant').first();
		await expect(assistantMessage).toBeVisible({ timeout: 15000 });

		console.log('  Assistant message visible — chat loaded');

		// Wait additional time for embed resolution (embed_ref → embed_id lookup,
		// then async resolveEmbed + component mount + render)
		await page.waitForTimeout(5000);

		// ─── Count rendered embeds ──────────────────────────────────────────
		const allEmbedPreviews = page.locator('[data-testid="embed-preview"]');
		const renderedCount = await allEmbedPreviews.count();

		const finishedEmbeds = page.locator(
			'[data-testid="embed-preview"][data-status="finished"]'
		);
		const finishedCount = await finishedEmbeds.count();

		const processingEmbeds = page.locator(
			'[data-testid="embed-preview"][data-status="processing"]'
		);
		const processingCount = await processingEmbeds.count();

		console.log(`  Rendered embed previews: ${renderedCount}`);
		console.log(`  Finished embeds: ${finishedCount}`);
		console.log(`  Processing embeds: ${processingCount}`);

		// ─── Diagnostics: console logs from embed resolution ────────────────
		console.log(`\n  Embed resolution logs (${consoleLogs.length}):`);
		consoleLogs.slice(0, 20).forEach((l) => console.log(`    ${l}`));
		if (consoleLogs.length > 20) {
			console.log(`    ... and ${consoleLogs.length - 20} more`);
		}
		console.log(`--- END ---\n`);

		// ─── Assertions ─────────────────────────────────────────────────────
		// At least 1 embed preview must be rendered
		expect(
			renderedCount,
			`Expected at least 1 embed preview to render in demo chat, found ${renderedCount}`
		).toBeGreaterThan(0);

		// At least 1 embed must have reached "finished" status
		expect(
			finishedCount,
			`Expected at least 1 embed to reach "finished" status, found ${finishedCount} finished (${processingCount} still processing)`
		).toBeGreaterThan(0);
	});
});
