/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * First send on iPhone-sized web: composer collapse and chat titles (TASK-6864).
 *
 * Guards two regressions:
 *   1. After Send the composer stayed open and focused (keyboard up on iPhone)
 *      until the user tapped outside. It must collapse and lose focus at once,
 *      while the message is still being processed.
 *   2. "Untitled chat" appeared in the header right after the first message and
 *      on start-screen cards while the generated title was pending. The display
 *      title is the first message until the preprocessor's title replaces it.
 *
 * REQUIRED ENV VARS:
 * - OPENMATES_TEST_ACCOUNT_EMAIL / _PASSWORD / _OTP_KEY
 * - PLAYWRIGHT_TEST_BASE_URL
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withMockMarker
} = require('./signup-flow-helpers');
const { deleteActiveChat, loginToTestAccount, setChatSidebarOpen, startNewChat } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createVideoProofRuntime, defineVideoProof } = require('./helpers/video-proof');

// iPhone 15-sized touch context (Chromium; WebKit is not installed in CI).
test.use({ viewport: { width: 393, height: 852 }, deviceScaleFactor: 3, hasTouch: true, isMobile: true });

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const UNTITLED = 'Untitled chat';
const FIRST_MESSAGE = 'Plan a relaxed weekend in Lisbon with one museum';
const GENERATED_TITLE = 'Capital of Germany';

const FIRST_SEND_PROOF = defineVideoProof({
	id: 'first-send-title-and-composer',
	title: 'First send collapses the composer and titles the chat',
	surface: 'web',
	devices: ['web-phone'],
	domain: 'app.dev.openmates.org',
	transcript: [
		{ id: 'collapse', text: 'After Send the composer collapses and loses focus while the message is processed.', checkpoint: 'composer-collapsed', devices: ['web-phone'] },
		{ id: 'title', text: 'The header shows the first message until the generated title replaces it, never Untitled chat.', checkpoint: 'header-title', devices: ['web-phone'] }
	],
	assertions: [
		{ id: 'message-input.send.collapse-at-send', checkpoint: 'composer-collapsed', visual: 'The composer is collapsed with the keyboard focus gone right after Send.', devices: ['web-phone'] },
		{ id: 'chats.titles.first-message-fallback', checkpoint: 'header-title', visual: 'The chat header shows the first message or the generated title, never Untitled chat.', devices: ['web-phone'] }
	],
	tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1200, maximumHoldMs: 3000 }
});

const consoleLogs: string[] = [];

test.afterEach(async ({ page: _page }: { page: any }, testInfo: any) => {
	void _page;
	if (testInfo.status !== 'passed') consoleLogs.slice(-60).forEach((log) => console.log(log));
});

// contract-test: direct surface=gui.web assertions=message-input.send.collapse-at-send,chats.titles.first-message-fallback
test('first send collapses the composer at once and the chat is never shown as Untitled chat', async ({
	page
}: {
	page: any;
}, testInfo: any) => {
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	test.setTimeout(300000);
	const logStep = createSignupLogger('FIRST_SEND_TITLE');
	const takeStepScreenshot = createStepScreenshotter(logStep, { filenamePrefix: 'first-send-title' });
	await archiveExistingScreenshots(logStep);
	const proof = createVideoProofRuntime(FIRST_SEND_PROOF, {
		device: 'web-phone',
		attach: testInfo.attach.bind(testInfo),
		captureFrame: () => page.screenshot({ type: 'png' })
	});
	page.on('console', (msg: any) => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
	const attach = async (name: string) =>
		test.info().attach(name, { body: await page.screenshot(), contentType: 'image/png' });

	await loginToTestAccount(page, logStep, takeStepScreenshot);
	let chatId: string | null = null;
	try {
		await startNewChat(page, logStep);
		const field = page.getByTestId('message-field').last();
		await field.getByTestId('message-editor').tap();
		await expect(field).toHaveAttribute('data-focused', 'true');
		await page.keyboard.insertText(withMockMarker(FIRST_MESSAGE, 'chat_flow_capital'));
		const send = field.getByTestId('composer-send-button');
		await expect(send).toBeVisible();
		await attach('01-composer-open-before-send');

		// Record the header text every 50 ms and main-thread long tasks during the send.
		await page.evaluate(() => {
			const w = window as any;
			w.__headerTexts = [];
			w.__longTasks = [];
			w.__headerSampler = setInterval(() => {
				const text = document.querySelector('[data-testid="chat-header-banner"]')?.textContent?.trim();
				if (text) w.__headerTexts.push(text);
			}, 50);
			new PerformanceObserver((list) => {
				for (const entry of list.getEntries()) w.__longTasks.push(Math.round(entry.duration));
			}).observe({ type: 'longtask', buffered: false });
		});

		const sentAt = Date.now();
		await send.tap();
		const collapseMs = await proof.assert('message-input.send.collapse-at-send', async () => {
			await expect(field).toHaveAttribute('data-focused', 'false', { timeout: 1500 });
			const elapsed = Date.now() - sentAt;
			await expect(field).not.toHaveClass(/fullscreen-expanded/);
			expect(await page.evaluate(() => !!document.activeElement?.closest('[data-testid="message-field"]'))).toBe(false);
			return elapsed;
		});
		await attach('02-composer-collapsed-after-send');
		const longTasks: number[] = await page.evaluate(() => (window as any).__longTasks);
		test.info().annotations.push({ type: 'collapse-ms', description: String(collapseMs) });
		test.info().annotations.push({ type: 'long-tasks-ms', description: JSON.stringify(longTasks) });
		logStep(`Composer collapsed ${collapseMs} ms after Send; long tasks: ${JSON.stringify(longTasks)}`);

		await expect.poll(() => page.url(), { timeout: 20000 }).toMatch(/chat-id=/);
		chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ?? null;
		const banner = page.getByTestId('chat-header-banner');
		await proof.assert('chats.titles.first-message-fallback', async () => {
			await expect(banner).toContainText(FIRST_MESSAGE.slice(0, 24), { timeout: 15000 });
			await expect(banner).not.toContainText(UNTITLED);
			// The first-message title is clamped inside the phone-width banner, not pushed above it.
			await expect
				.poll(() =>
					page.evaluate(() => {
						const title = document.querySelector('[data-testid="chat-header-provisional-title"]')?.getBoundingClientRect();
						const box = document.querySelector('[data-testid="chat-header-banner"]')?.getBoundingClientRect();
						return !title || (!!box && title.top >= box.top - 1 && title.bottom <= box.bottom + 1);
					})
				)
				.toBe(true);
		});
		// After Send the chat scrolls the banner partly out of view; bring it back so the title is on screen.
		await banner.evaluate((el: HTMLElement) => el.scrollIntoView({ block: 'start' }));
		await expect(banner.getByText(FIRST_MESSAGE.slice(0, 24))).toBeInViewport();
		await attach('03-header-first-message-title');

		// The generated title (committed fixture: "Capital of Germany") replaces the first-message title.
		await expect(banner).toContainText(GENERATED_TITLE, { timeout: 90000 });
		await expect(banner).not.toContainText(FIRST_MESSAGE.slice(0, 24));
		await banner.evaluate((el: HTMLElement) => el.scrollIntoView({ block: 'start' }));
		await expect(banner.getByText(GENERATED_TITLE)).toBeInViewport();
		await attach('04-header-generated-title');
		const headerTexts: string[] = await page.evaluate(() => {
			const w = window as any;
			clearInterval(w.__headerSampler);
			return w.__headerTexts;
		});
		expect(headerTexts.length).toBeGreaterThan(0);
		expect(headerTexts.filter((text) => text.includes(UNTITLED))).toEqual([]);

		// Reopened chat, sidebar rows and start-screen cards never say Untitled chat.
		await page.reload();
		await expect(page.getByTestId('chat-header-banner')).toBeVisible({ timeout: 30000 });
		await expect(page.getByTestId('chat-header-banner')).not.toContainText(UNTITLED);
		await setChatSidebarOpen(page, true, logStep);
		await expect(page.getByTestId('activity-history-wrapper')).toBeVisible({ timeout: 10000 });
		await expect(page.locator('[data-testid="chat-item-wrapper"]').first()).toBeVisible({ timeout: 15000 });
		await expect(page.getByTestId('chat-title').filter({ hasText: UNTITLED })).toHaveCount(0);
		await attach('05-sidebar-titles');
		// Two Close buttons exist at phone width (sidebar and chat); close the sidebar's own.
		await page.getByTestId('chats-close-button').tap();
		await expect(page.getByTestId('sidebar-toggle')).toHaveAttribute('aria-expanded', 'false');
		await startNewChat(page, logStep);
		const welcome = page.getByTestId('welcome-content');
		await expect(welcome).toBeVisible({ timeout: 15000 });
		await expect(welcome).not.toContainText(UNTITLED);
		await attach('06-start-screen-cards');
	} finally {
		if (chatId) {
			await page.goto(`/#chat-id=${chatId}`).catch(() => undefined);
			await deleteActiveChat(page, logStep, takeStepScreenshot, 'first-send-title-cleanup').catch((error: Error) =>
				logStep(`Cleanup failed: ${error.message}`)
			);
		}
	}
});
