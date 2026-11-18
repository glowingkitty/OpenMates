/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=real_inference_dev_only
/**
 * Mixed routes with an owned pass (dev-only real-inference proof, TASK-1047).
 *
 * Runs without mocks against the deployed dev stack through
 * scripts/travel_mixed_routes_web_real_test.py with the personal dev test account
 * (or a throwaway account when it is busy). For each trip the traveller says they
 * own a Deutschland-Ticket and asks @Gemini-3.8-Flash for the cheapest train or
 * bus options; the persisted model must be Gemini 3.8 Flash.
 *   - Munich -> Zurich (phone and laptop): a composed route appears with
 *     "2 tickets", its fullscreen lists the pass-covered train part and the paid
 *     part with its price and booking link.
 *   - Berlin -> Prague and Berlin -> Copenhagen (laptop): the answer shows
 *     connection cards; composed routes appear only when they are not beaten on
 *     both price and duration, so the spec records whether one was offered.
 * The chats are deleted afterwards. Never run in CI: it needs real providers.
 */
import type { Locator, Page } from '@playwright/test';

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

const ANSWER_TIMEOUT_MS = 300_000;
const RAW_ISO = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
const VIEWPORTS = { phone: { width: 390, height: 844 }, laptop: { width: 1280, height: 900 } } as const;

type Trip = { id: string; from: string; to: string; requireMixed: boolean; viewports: (keyof typeof VIEWPORTS)[] };
const TRIPS: Trip[] = [
	{ id: 'munich-zurich', from: 'Munich', to: 'Zurich', requireMixed: true, viewports: ['laptop', 'phone'] },
	{ id: 'berlin-prague', from: 'Berlin', to: 'Prague', requireMixed: false, viewports: ['laptop'] },
	{ id: 'berlin-copenhagen', from: 'Berlin', to: 'Copenhagen', requireMixed: false, viewports: ['laptop'] }
];

const question = (trip: Trip) =>
	` I have a Deutschland-Ticket. I am in ${trip.from} and need to get to ${trip.to} next Monday morning. ` +
	'Search train and bus connections and show me the cheapest good options, counting what I actually have to pay.';

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

async function askWithGemini(page: Page, text: string, log: any): Promise<void> {
	const editor = page.getByTestId('message-editor');
	await focusMessageEditor(editor);
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
	await page.keyboard.type(text);
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });
	log(`Sent: ${text.trim()}`);
}

async function settle(card: Locator, page: Page): Promise<void> {
	await card.evaluate(element => element.scrollIntoView({ block: 'center' }));
	await expect.poll(async () => {
		const before = await card.boundingBox();
		await page.waitForTimeout(400);
		const after = await card.boundingBox();
		return Boolean(before && after && Math.abs(before.y - after.y) < 1);
	}, { timeout: 15_000 }).toBe(true);
}

for (const trip of TRIPS) {
	for (const label of trip.viewports) {
		// contract-test: supporting surface=gui.web assertions=travel-search.mixed-routes.per-ticket-display,travel-search.mixed-routes.pass-hub-composition,travel-search.mixed-routes.total-price-ranking
		test(`${trip.from} to ${trip.to} with a Deutschland-Ticket (${label})`, async ({ page }: { page: Page }, testInfo: any) => {
			test.setTimeout(900_000);
			test.skip(Boolean(process.env.E2E_USE_MOCKS), 'Real dev inference only.');
			test.skip(!getTestAccount().email, 'Test account credentials required.');
			await page.setViewportSize(VIEWPORTS[label]);
			const log = createSignupLogger(`MIXED_${trip.id.toUpperCase()}_${label.toUpperCase()}`);
			const screenshot = createStepScreenshotter(log);
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page, log, screenshot);
			await setChatSidebarOpen(page, false, log);
			await startNewChat(page, log);

			try {
				await askWithGemini(page, question(trip), log);
				const answer = page.getByTestId('message-assistant').last();
				await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
				await waitForIdle(page);
				await expect(answer.getByTestId('generated-by')).toContainText(/Gemini 3\.8 Flash/i, { timeout: 60_000 });
				await expect(answer.getByTestId('connection-route').first()).toBeVisible({ timeout: 60_000 });
				expect(await answer.innerText()).not.toMatch(RAW_ISO);
				await testInfo.attach(`${trip.id}-${label}-answer`, { body: await page.screenshot(), contentType: 'image/png' });

				const badges = answer.getByTestId('connection-tickets-badge');
				const mixedCount = await badges.count();
				log(`Composed routes shown in the answer: ${mixedCount}`);
				testInfo.annotations.push({ type: 'mixed-routes-shown', description: String(mixedCount) });
				if (trip.requireMixed) expect(mixedCount, 'a composed route is offered').toBeGreaterThan(0);
				if (mixedCount === 0) return;

				const badge = badges.first();
				await settle(badge, page);
				await expect(badge).toContainText('2 tickets');
				await testInfo.attach(`${trip.id}-${label}-mixed-card`, { body: await page.screenshot(), contentType: 'image/png' });
				await badge.click();
				const overlay = page.getByTestId('embed-fullscreen-overlay');
				await expect(overlay).toBeVisible({ timeout: 20_000 });
				const tickets = overlay.getByTestId('route-tickets');
				await expect(tickets).toContainText('2 separate tickets', { timeout: 30_000 });
				const rows = tickets.getByTestId('route-ticket');
				await expect(rows).toHaveCount(2);
				await expect(tickets.getByTestId('route-ticket-price').filter({ hasText: 'Covered by Deutschland-Ticket' })).toHaveCount(1);
				expect(await overlay.innerText()).not.toMatch(RAW_ISO);
				await tickets.evaluate(element => element.scrollIntoView({ block: 'center' }));
				await testInfo.attach(`${trip.id}-${label}-mixed-fullscreen`, { body: await page.screenshot(), contentType: 'image/png' });
				log(`Tickets: ${(await tickets.innerText()).replace(/\s+/g, ' ')}`);
				await closeFullscreen(page, overlay);
			} finally {
				await deleteActiveChat(page, log, screenshot);
			}
		});
	}
}
