/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and attached screenshots cover each checkpoint)
/**
 * Travel answers show complete connection cards (dev-only real-inference proof, TASK-3927).
 *
 * Runs without mocks against the deployed dev stack through
 * scripts/travel_results_web_real_test.py with the personal dev test account
 * (or a throwaway account when it is busy), on a phone and a laptop viewport:
 *   1. @Gemini-3.8-Flash searches train connections Munich -> Zurich and
 *      presents its picks; the persisted model must be Gemini 3.8 Flash.
 *   2. Every connection card in the answer opens a fullscreen with a route map
 *      (a complete skill card, not a thin re-authored copy) and readable times,
 *      never a raw ISO timestamp.
 *   3. The results view Calendar keeps its day headers and hour column in view
 *      while it scrolls.
 * The chat is deleted afterwards. Never run in CI: it needs real providers.
 */
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
	deleteActiveChat,
	focusMessageEditor,
	loginToTestAccount,
	setChatSidebarOpen,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const QUESTION =
	' I am in Munich and need to get to Zurich next Monday. Search train connections for Monday morning and show me your three best picks.';
const RAW_ISO = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const ANSWER_TIMEOUT_MS = 300_000;
const VIEWPORTS = { phone: { width: 390, height: 844 }, laptop: { width: 1280, height: 900 } } as const;

/** The turn is over when the stop button and typing indicator stay hidden for 5 s. */
async function waitForIdle(page: Page): Promise<void> {
	const busy = page.locator('[data-testid="stop-processing-button"]:visible, [data-testid="typing-indicator"]:visible');
	let idleSince = 0;
	await expect
		.poll(async () => {
			if ((await busy.count()) > 0) {
				idleSince = 0;
				return false;
			}
			idleSince ||= Date.now();
			return Date.now() - idleSince >= 5_000;
		}, { timeout: ANSWER_TIMEOUT_MS, intervals: [1_000] })
		.toBe(true);
}

/** Select the model through the @mention dropdown, then type the question and send it. */
async function askWithGemini(page: Page, log: any): Promise<void> {
	const editor = page.getByTestId('message-editor');
	await focusMessageEditor(editor);
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
	await page.keyboard.type(QUESTION);
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });
	log('Sent the Munich to Zurich train request with @Gemini-3.8-Flash.');
}

for (const [label, viewport] of Object.entries(VIEWPORTS)) {
	test.describe(`travel results (real dev inference, ${label})`, () => {
		// contract-test: direct surface=gui.web assertions=authored-results.groups.same-response-and-reuse,authored-results.content.typed-and-useful,authored-results.presentation.standard-results-view
		test(`train picks open complete connection cards with readable times (${label})`, async ({ page }: { page: Page }, testInfo: any) => {
			test.setTimeout(900_000);
			test.skip(Boolean(process.env.E2E_USE_MOCKS), 'Real dev inference only.');
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await page.setViewportSize(viewport);
			const log = createSignupLogger(`TRAVEL_RESULTS_${label.toUpperCase()}`);
			const screenshot = createStepScreenshotter(log);
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page, log, screenshot);
			await setChatSidebarOpen(page, false, log);
			await startNewChat(page, log);

			try {
				await askWithGemini(page, log);
				const answer = page.getByTestId('message-assistant').last();
				await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
				await waitForIdle(page);
				await expect(answer.getByTestId('generated-by')).toContainText(/Gemini 3\.8 Flash/i, { timeout: 60_000 });
				await testInfo.attach(`${label}-answer`, { body: await page.screenshot(), contentType: 'image/png' });

				// Every connection card in the answer is a complete card: route map and readable times.
				const cards = answer.getByTestId('connection-route');
				await expect(cards.first()).toBeVisible({ timeout: 60_000 });
				const count = Math.min(await cards.count(), 4);
				for (let index = 0; index < count; index += 1) {
					// Center the card clear of the composer and wait until it stops moving: a layout
					// shift between press and release turns the tap into a text-selection drag.
					await cards.nth(index).evaluate(element => element.scrollIntoView({ block: 'center' }));
					await expect.poll(async () => {
						const before = await cards.nth(index).boundingBox();
						await page.waitForTimeout(400);
						const after = await cards.nth(index).boundingBox();
						return Boolean(before && after && Math.abs(before.y - after.y) < 1);
					}, { timeout: 15_000 }).toBe(true);
					await cards.nth(index).click();
					const overlay = page.getByTestId('embed-fullscreen-overlay');
					await expect(overlay).toBeVisible({ timeout: 20_000 });
					await expect(overlay.getByTestId('result-map'), `connection ${index + 1} has its route map`).toBeVisible({ timeout: 30_000 });
					expect(await overlay.innerText(), `connection ${index + 1} shows readable times`).not.toMatch(RAW_ISO);
					await testInfo.attach(`${label}-connection-${index + 1}`, { body: await page.screenshot(), contentType: 'image/png' });
					await closeFullscreen(page, overlay);
				}
				expect(await answer.innerText()).not.toMatch(RAW_ISO);

				// The results calendar keeps its day headers and hour column while it scrolls.
				const results = answer.getByTestId('embeds-map-view').first();
				if (await results.getByTestId('embeds-results-view-tab-calendar').count()) {
					await results.getByTestId('embeds-results-view-tab-calendar').click();
					const calendar = results.getByTestId('embeds-results-view-calendar');
					await expect(calendar).toBeVisible();
					const header = calendar.getByTestId('embeds-results-view-calendar-day-header').first();
					const headerTop = (await header.boundingBox())?.y ?? 0;
					await calendar.evaluate(element => { element.scrollTop = 300; element.scrollLeft = 200; });
					await expect.poll(async () => Math.round((await header.boundingBox())?.y ?? -1)).toBe(Math.round(headerTop));
					const frameX = (await calendar.boundingBox())?.x ?? 0;
					const hoursX = (await calendar.getByTestId('embeds-results-view-calendar-time-column').boundingBox())?.x ?? -1;
					expect(Math.round(hoursX)).toBe(Math.round(frameX));
					await testInfo.attach(`${label}-calendar-scrolled`, { body: await page.screenshot(), contentType: 'image/png' });
				}
			} finally {
				await deleteActiveChat(page, log, screenshot);
			}
		});
	});
}
