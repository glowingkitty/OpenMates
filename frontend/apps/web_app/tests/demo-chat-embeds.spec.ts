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
 *   1. Fetch demo chat list from the API (flexible to content changes)
 *   2. Pick a sample of chats that have embeds
 *   3. Navigate to each and verify embeds actually render
 *   4. No credentials required — tests the unauthenticated public flow
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

/** Maximum number of demo chats to test (to keep test time bounded) */
const MAX_CHATS_TO_TEST = 4;

/** Time to wait for embeds to render after navigating to a demo chat (ms) */
const EMBED_RENDER_TIMEOUT = 15000;

test.describe('Demo chat embed rendering', () => {
	test('embeds inside demo chats render for unauthenticated users', async ({ page }) => {
		test.setTimeout(120000);

		// ─── Console logging for diagnostics ────────────────────────────────
		const consoleLogs: string[] = [];
		page.on('console', (message: any) => {
			const text = message.text();
			if (
				text.includes('embedResolver') ||
				text.includes('registerDemoEmbedRefs') ||
				text.includes('EmbedPreviewLarge') ||
				text.includes('EmbedReferencePreview') ||
				text.includes('loadCommunityDemos') ||
				text.includes('embed_ref')
			) {
				consoleLogs.push(`[${message.type()}] ${text}`);
			}
		});

		// ─── Navigate and let demo chats load ───────────────────────────────
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		// ─── Fetch demo chat list from the API (inside the browser to handle CORS) ─
		const demoChatsWithEmbeds: Array<{ demoId: string; title: string; embedCount: number }> =
			await page.evaluate(async () => {
				const origin = window.location.origin;
				let apiBase = origin.replace('://app.', '://api.');
				if (!apiBase.includes('://api.')) {
					apiBase = origin.replace('://', '://api.');
				}

				const listRes = await fetch(`${apiBase}/v1/demo/chats?lang=en`);
				if (!listRes.ok) return [];

				const data = await listRes.json();
				const demos = data.demo_chats || [];
				const results: Array<{ demoId: string; title: string; embedCount: number }> = [];

				// Fetch each demo to find ones with embeds
				for (const demo of demos) {
					try {
						const chatRes = await fetch(`${apiBase}/v1/demo/chat/${demo.demo_id}?lang=en`);
						if (!chatRes.ok) continue;
						const chatData = await chatRes.json();
						const embeds = chatData.chat_data?.embeds || [];
						if (embeds.length > 0) {
							results.push({
								demoId: demo.demo_id,
								title: demo.title,
								embedCount: embeds.length,
							});
						}
					} catch {
						// Skip failed fetches
					}
				}

				return results;
			});

		console.log(`\n--- DEMO CHATS WITH EMBEDS ---`);
		console.log(`Found ${demoChatsWithEmbeds.length} demo chats with embeds`);
		demoChatsWithEmbeds.forEach((d) =>
			console.log(`  ${d.demoId}: ${d.title} (${d.embedCount} embeds)`)
		);

		// Must have at least 1 demo chat with embeds
		expect(
			demoChatsWithEmbeds.length,
			'Expected at least 1 demo chat with embeds'
		).toBeGreaterThan(0);

		// ─── Test a sample of demo chats ────────────────────────────────────
		const chatsToTest = demoChatsWithEmbeds.slice(0, MAX_CHATS_TO_TEST);
		const testResults: Array<{
			demoId: string;
			title: string;
			expectedEmbeds: number;
			renderedEmbeds: number;
			finishedEmbeds: number;
			stuckLoading: number;
			passed: boolean;
		}> = [];

		for (const chat of chatsToTest) {
			console.log(`\n--- Testing: ${chat.title} (${chat.demoId}) ---`);

			// Navigate to this demo chat
			await page.goto(getE2EDebugUrl(`/#chat-id=${chat.demoId}`), {
				waitUntil: 'domcontentloaded',
			});
			await page.waitForLoadState('networkidle');

			// Wait for demo chats to load and embeds to render
			// We need to wait for:
			// 1. loadCommunityDemos() to fetch and store embed data
			// 2. registerDemoEmbedRefs() to populate the ref index
			// 3. Embed components to resolve and render
			await page.waitForTimeout(EMBED_RENDER_TIMEOUT);

			// Count rendered embed previews (UnifiedEmbedPreview wraps all embeds)
			const allEmbedPreviews = page.locator('[data-testid="embed-preview"]');
			const renderedCount = await allEmbedPreviews.count();

			// Count embeds that reached "finished" status
			const finishedEmbeds = page.locator(
				'[data-testid="embed-preview"][data-status="finished"]'
			);
			const finishedCount = await finishedEmbeds.count();

			// Count embeds stuck in loading/processing state
			const stuckEmbeds = page.locator(
				'[data-testid="embed-preview"][data-status="processing"]'
			);
			const stuckCount = await stuckEmbeds.count();

			const passed = renderedCount > 0 && finishedCount > 0;

			testResults.push({
				demoId: chat.demoId,
				title: chat.title,
				expectedEmbeds: chat.embedCount,
				renderedEmbeds: renderedCount,
				finishedEmbeds: finishedCount,
				stuckLoading: stuckCount,
				passed,
			});

			console.log(`  Expected embeds (from API): ${chat.embedCount}`);
			console.log(`  Rendered embed previews: ${renderedCount}`);
			console.log(`  Finished embeds: ${finishedCount}`);
			console.log(`  Stuck in processing: ${stuckCount}`);
			console.log(`  Result: ${passed ? 'PASS' : 'FAIL'}`);
		}

		// ─── Final diagnostics ──────────────────────────────────────────────
		console.log(`\n--- EMBED RESOLUTION LOGS ---`);
		consoleLogs.forEach((l) => console.log(`  ${l}`));
		console.log(`--- END ---\n`);

		// ─── Assertions ─────────────────────────────────────────────────────
		for (const result of testResults) {
			// Each demo chat must have at least 1 rendered embed
			expect(
				result.renderedEmbeds,
				`Demo "${result.title}" (${result.demoId}): expected rendered embeds but found ${result.renderedEmbeds}`
			).toBeGreaterThan(0);

			// Each demo chat must have at least 1 finished embed
			expect(
				result.finishedEmbeds,
				`Demo "${result.title}" (${result.demoId}): no embeds reached "finished" status (${result.stuckLoading} stuck loading)`
			).toBeGreaterThan(0);
		}
	});
});
