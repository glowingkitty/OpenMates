/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (the Playwright video and attached screenshots cover each checkpoint)
/**
 * Conference questions are answered through the Events app (real-inference proof, TASK-2134).
 *
 * Runs in the `real_inference` CI group (isolated per-run stack with real Gemini, Mistral, Brave
 * and Jev keys) and still manually against dev through
 * scripts/events_question_web_real_test.py:
 *   1. @Gemini-3.8-Flash is asked for the largest open source conference in
 *      Europe and when it happens. The Events app search skill must run first
 *      (its app icon in the answer's activity line), never plain web search only.
 *   2. When Events found events, its card opens fullscreen. When it found no
 *      dated edition, the answer falls back to a web search card instead of
 *      answering from memory (specialised skill first, web search as fallback).
 *   3. A chat header image bubble, when the header shows one, opens fullscreen
 *      without the "Embed not found" server error.
 * The chat is deleted afterwards.
 */
import path from 'node:path';
import { proofAudioLaunchArgs, useProofMicrophone, withProofAudio } from './helpers/proof-audio';
import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
	deleteActiveChat,
	focusMessageEditor,
	loginToTestAccount,
	setChatSidebarOpen,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { closeFullscreen, openFullscreen } = require('./helpers/embed-test-helpers');
const { requireRealInference } = require('./helpers/real-inference-guard');
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org';
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

const QUESTION = ' What is the largest open source software conference in Europe and when does it happen?';
const ANSWER_TIMEOUT_MS = 300_000;
const EMBED_NOT_FOUND = /Embed not found/i;

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

async function selectGeminiMention(page: Page): Promise<void> {
	await page.keyboard.insertText('@Gemini-3.8-Flash');
	const dropdown = page.getByTestId('mention-dropdown');
	await expect(dropdown.getByTestId('mention-result-name').filter({ hasText: /Gemini 3\.8 Flash/i }).first()).toBeVisible({ timeout: 10_000 });
	await page.keyboard.press('Tab');
	await expect(dropdown).toBeHidden({ timeout: 5_000 });
}

async function askWithGemini(page: Page, log: any): Promise<void> {
	const editor = page.getByTestId('message-editor');
	await focusMessageEditor(editor);
	await selectGeminiMention(page);
	await page.keyboard.type(QUESTION);
	await page.locator('[data-action="send-message"]').click();
	await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 20_000 });
	log('Sent the largest open source conference question with @Gemini-3.8-Flash.');
}

// contract-test: direct surface=gui.web assertions=ai-model-routing.preprocessing.conditional-context
test('the largest open source conference question is answered through the Events app, with web search only as fallback', async ({ page }: { page: Page }, testInfo: any) => {
	test.setTimeout(900_000);
	requireRealInference('Events question', BASE_URL);
	test.skip(!getTestAccount().email, 'Test account credentials required.');
	await page.setViewportSize({ width: 1280, height: 900 });
	const log = createSignupLogger('EVENTS_QUESTION');
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

		// The Events app search skill ran first: its app icon and its search card are in the answer.
		const eventsActivity = answer.locator('[data-testid="assistant-skill-app-icon"][data-app-id="events"]').first();
		await expect(eventsActivity, 'the Events app ran for this answer').toBeAttached({ timeout: 60_000 });
		const eventsCard = page.locator('[data-testid="embed-preview"][data-app-id="events"][data-skill-id="search"]').first();
		// Collapsed activity lines show only answer cards; open the line when the card sits inside it.
		if (!(await eventsCard.waitFor({ state: 'visible', timeout: 20_000 }).then(() => true, () => false))) {
			await answer.getByTestId('assistant-activity-toggle').first().click();
		}
		await expect(eventsCard, 'the Events app search card is in the answer').toBeVisible({ timeout: 60_000 });
		await expect(eventsCard).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
		await eventsCard.evaluate(element => element.scrollIntoView({ block: 'center' }));
		await testInfo.attach('answer-with-events-card', { body: await page.screenshot(), contentType: 'image/png' });

		const overlay = await openFullscreen(page, eventsCard);
		await expect(overlay).not.toContainText(EMBED_NOT_FOUND);
		await page.waitForTimeout(1_500);
		const eventsFoundNothing = await overlay.getByTestId('search-no-results-message').isVisible();
		await testInfo.attach('events-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
		await closeFullscreen(page, overlay);

		if (eventsFoundNothing) {
			// Events found no dated edition: the answer must fall back to web search, never to memory.
			log('Events found no dated edition; expecting the web search fallback.');
			const webSearchCard = answer.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]').first();
			await expect(webSearchCard, 'web search ran as the fallback after an empty Events result').toBeVisible({ timeout: 60_000 });
			await expect(webSearchCard).toHaveAttribute('data-status', 'finished', { timeout: 120_000 });
			await webSearchCard.evaluate(element => element.scrollIntoView({ block: 'center' }));
			await testInfo.attach('answer-with-web-search-fallback', { body: await page.screenshot(), contentType: 'image/png' });
			const webOverlay = await openFullscreen(page, webSearchCard);
			await expect(webOverlay).not.toContainText(EMBED_NOT_FOUND);
			await page.waitForTimeout(1_500);
			await testInfo.attach('web-search-fallback-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
			await closeFullscreen(page, webOverlay);
		} else {
			log('Events found events: the Events search card lists them.');
			// The announced edition has a published venue. Check the address in the
			// actual result, where a city-only pin previously hid the missing venue.
			const fosdem = answer.locator('[data-testid="embed-preview"][data-app-id="events"][data-skill-id="event"]')
				.filter({ has: page.getByText(/^FOSDEM(?: 2027)?$/i) }).first();
			if (await fosdem.count()) {
				const event = await openFullscreen(page, fosdem);
				const date = event.getByTestId('event-date-label');
				if (await date.count() && /Jan(?:uary)?\s+30,?\s+2027/i.test(await date.innerText())) {
					await expect(event.getByTestId('event-venue-card')).toContainText(/Roosevelt\s+50/i);
					await expect(event.getByTestId('result-map')).toBeVisible();
					await testInfo.attach('fosdem-venue-map', { body: await page.screenshot(), contentType: 'image/png' });
				}
				await closeFullscreen(page, event);
			}
		}

		// A header image bubble opens fullscreen without "Embed not found".
		await page.evaluate(() => window.scrollTo(0, 0));
		const bubble = page.locator('[data-testid="chat-header-image-bubble-left"], [data-testid="chat-header-image-bubble-right"]').first();
		if (await bubble.isVisible().catch(() => false)) {
			const bubbleOverlay = await openFullscreen(page, bubble);
			await page.waitForTimeout(2_000);
			await expect(page.getByText(EMBED_NOT_FOUND)).toHaveCount(0);
			await testInfo.attach('header-bubble-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
			await closeFullscreen(page, bubbleOverlay);
		} else {
			log('The chat header shows no image bubble for this answer.');
		}
		await expect(page.getByText(EMBED_NOT_FOUND)).toHaveCount(0);
	} finally {
		await deleteActiveChat(page, log, screenshot);
	}
});

const dictatedTest = withProofAudio(test);
dictatedTest.use({ launchOptions: { args: proofAudioLaunchArgs({ voiceWav: null }) }, permissions: ['microphone'] });
const DICTATION = /Are there any upcoming open[- ]source software conferences in Europe/i;

dictatedTest.describe('dictated conference discovery', () => {
	const test = dictatedTest;

	// contract-test: direct surface=gui.web assertions=events-search.results.actionable,events-search.answer.states-dates,authored-results.groups.same-response-and-reuse,authored-results.presentation.standard-results-view,message-input.audio.editable-transcript
	test('one Events result view contains the dated conferences and sourced venue details', async ({ page }, testInfo) => {
		test.setTimeout(600_000);
		requireRealInference('Dictated conference discovery', BASE_URL);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		const log = createSignupLogger('DICTATED_EVENTS');
		const screenshot = createStepScreenshotter(log);
		await page.setViewportSize({ width: 1280, height: 900 });
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await loginToTestAccount(page, log, screenshot);
		await setChatSidebarOpen(page, false, log);
		await startNewChat(page, log);

		try {
			await useProofMicrophone(page, path.resolve(__dirname, 'fixtures/upcoming-conferences-dictation.mp3'));
			const field = page.getByTestId('message-field').filter({ visible: true });
			const editor = field.getByTestId('message-editor').locator('[contenteditable="true"]');
			const microphone = page.locator(
				'[data-record-audio-trigger="true"]:visible, [data-testid="record-audio-button"]:visible'
			).first();
			await expect(microphone).toBeVisible({ timeout: 15_000 });
			await microphone.dispatchEvent('mousedown', { button: 0 }, { timeout: 15_000 });
			const overlay = page.getByTestId('record-overlay');
			await expect(overlay).toBeVisible({ timeout: 15_000 });
			log('The new-chat microphone is recording.');
			await expect(editor).toContainText(DICTATION, { timeout: 35_000 });
			await overlay.getByTestId('record-finish-button').click();
			await expect(overlay).toBeHidden({ timeout: 45_000 });
			await expect(editor).toContainText(DICTATION);
			log('The real microphone transcript is ready in the composer.');
			await editor.press('Control+Home');
			await selectGeminiMention(page);
			await expect(editor).toContainText(DICTATION);
			log('Selected the per-message Gemini 3.8 Flash route, matching the reported reply.');
			await field.locator('[data-action="send-message"]').click();
			await expect(page.getByTestId('message-user').last()).toContainText(DICTATION);
			log('Sent the dictated conference question.');
			const answer = page.getByTestId('message-assistant').last();
			await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
			await waitForIdle(page);
			await expect(answer.getByTestId('generated-by')).toContainText(/Gemini 3\.8 Flash/i);
			await expect(answer.locator('[data-testid="assistant-skill-app-icon"][data-app-id="events"]')).toBeAttached();
			const results = answer.getByTestId('embeds-map-view');
			await expect(results.first()).toBeVisible({ timeout: 60_000 });
			await testInfo.attach('conference-results', { body: await page.screenshot(), contentType: 'image/png' });
			await expect(answer.getByTestId('authored-results-preview')).toHaveCount(0);
			await expect(results).toHaveCount(1);

			const map = results.getByRole('tab', { name: 'Map', exact: true });
			const calendar = results.getByRole('tab', { name: 'Calendar', exact: true });
			await expect(map).toBeVisible();
			await expect(calendar).toBeVisible();
			const fosdem = results.getByTestId('embeds-map-view-card').filter({ has: page.getByRole('heading', { name: /^FOSDEM(?: 2027)?$/i }) });
			await expect(fosdem).toHaveCount(1);
			await expect(fosdem).toHaveAttribute('data-entry-mapped', 'true');
			const badge = fosdem.getByTestId('embed-calendar-date');
			for (const width of [1280, 390]) {
				await page.setViewportSize({ width, height: 900 });
				await page.mouse.move(0, 0);
				await fosdem.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'center' }));
				await expect(badge).toBeVisible();
				await expect(badge.locator('span')).toHaveText('Sat');
				await expect(badge.locator('strong')).toHaveText('30');
				await expect.poll(() => badge.evaluate(element => {
					const node = element as HTMLElement;
					const prior = node.style.pointerEvents;
					node.style.pointerEvents = 'auto';
					try {
						const { x, y, width, height } = node.getBoundingClientRect();
						return node.checkVisibility({ opacityProperty: true, visibilityProperty: true })
							&& node.contains(document.elementFromPoint(x + width / 2, y + height / 2));
					} finally {
						node.style.pointerEvents = prior;
					}
				})).toBe(true);
				await testInfo.attach(`fosdem-date-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
			}
			await page.setViewportSize({ width: 1280, height: 900 });
			await calendar.click();
			await expect(calendar).toHaveAttribute('aria-selected', 'true');
			const calendarPanel = results.getByRole('tabpanel', { name: 'Calendar results' });
			await expect(calendarPanel).toBeVisible();
			const fosdemDates = calendarPanel.getByTestId('embeds-results-view-calendar-date-only')
				.filter({ hasText: /FOSDEM(?: 2027)?/i });
			const nextWeek = calendarPanel.getByRole('button', { name: 'Next week' });
			for (let week = 0; week < 12 && !await fosdemDates.count() && await nextWeek.isEnabled(); week++) {
				await nextWeek.click();
			}
			await expect(fosdemDates).toHaveText([/2027-01-30/, /2027-01-31/]);
			await testInfo.attach('conference-calendar', { body: await page.screenshot(), contentType: 'image/png' });
			for (const [label, name] of [
				['open-source-week', /EU Open Source Week/i],
				['policy-summit', /EU Open Source Policy Summit/i],
			] as const) {
				const listing = calendarPanel.getByRole('button', { name }).first();
				if (!await listing.count()) continue;
				const detail = await openFullscreen(page, listing);
				const description = detail.getByTestId('event-description');
				await expect(description).toBeVisible();
				const text = await description.innerText();
				expect(text.trim().split(/\s+/).length).toBeGreaterThanOrEqual(20);
				if (label === 'policy-summit') await expect(detail.getByTestId('result-map')).toHaveCount(0);
				log(`${label} description: ${text}`);
				await testInfo.attach(label, { body: await page.screenshot(), contentType: 'image/png' });
				await closeFullscreen(page, detail);
			}
			await map.click();

			const event = await openFullscreen(page, fosdem.getByTestId('embed-preview'));
			await expect(event.getByTestId('event-venue-card')).toContainText(/Solbosch/i);
			await expect(event.getByTestId('event-venue-card')).toContainText(/Roosevelt\s+50/i);
			await expect(event.getByTestId('result-map')).toBeVisible();
			const description = event.getByTestId('event-description');
			await expect(description).toBeVisible();
			const text = await description.innerText();
			expect(text.trim().split(/\s+/).length).toBeGreaterThanOrEqual(15);
			const venue = event.getByTestId('event-venue-card');
			const latitude = Number(await venue.getAttribute('data-venue-lat'));
			const longitude = Number(await venue.getAttribute('data-venue-lon'));
			expect(latitude).toBeGreaterThan(50.808);
			expect(latitude).toBeLessThan(50.818);
			expect(longitude).toBeGreaterThan(4.375);
			expect(longitude).toBeLessThan(4.388);
			const image = event.getByTestId('event-source-image');
			if (await image.count()) {
				await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBeGreaterThan(0);
			}
			log(`FOSDEM description: ${text}`);
			log(`FOSDEM venue: ${await event.getByTestId('event-venue-card').innerText()}`);
			await testInfo.attach('fosdem-fullscreen', { body: await page.screenshot(), contentType: 'image/png' });
			await closeFullscreen(page, event);
		} finally {
			await deleteActiveChat(page, log, screenshot);
		}
	});
});
