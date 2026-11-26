/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS test helpers. */
// contract-test-file: tooling
/** Read-only, deployed-dev timings. Use the private Personal DevTest workflow. */
export {};

const { test, expect } = require('@playwright/test');
const { loginToTestAccount, waitForChatReady, dismissSecurityReminderIfPresent } = require('./helpers/chat-test-helpers');
const DEV_ORIGIN = 'https://app.dev.openmates.org';
const ROW_SELECTOR = '[data-testid="activity-history-wrapper"] [data-testid="chat-item-wrapper"][data-chat-id]';

test('Personal DevTest opens existing conversations after a cached launch', async ({ page }: { page: any }, testInfo: any) => {
	test.skip(process.env.OPENMATES_PRIVATE_ACCOUNT_TIMINGS !== '1', 'Private Personal DevTest workflow only');
	test.setTimeout(240000);
	if (process.env.PLAYWRIGHT_TEST_BASE_URL !== DEV_ORIGIN) throw new Error('Personal DevTest requires the development app');
	const credentials = {
		email: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_EMAIL,
		password: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_PASSWORD,
		otpKey: process.env.OPENMATES_PERSONAL_TEST_ACOUNT_OTP_KEY,
	};
	if (!credentials.email || !credentials.password || !credentials.otpKey) {
		throw new Error('Personal DevTest repository secrets are required');
	}
	await loginToTestAccount(page, undefined, undefined, { credentials });
	await dismissSecurityReminderIfPresent(page);
	await waitForChatReady(page);

	const recentRowsMS: number[] = [];
	const visibleMessageMS: number[] = [];
	const selected = new Set<string>();
	for (let sample = 0; sample < 3; sample++) {
		await page.goto('/', { waitUntil: 'domcontentloaded' });
		if (new URL(page.url()).origin !== DEV_ORIGIN) throw new Error('Unexpected application origin');
		const sidebar = page.getByTestId('activity-history-wrapper');
		if (!(await sidebar.isVisible())) await page.getByTestId('sidebar-toggle').click();
		const rows = page.locator(ROW_SELECTOR);
		await expect(rows.first()).toBeVisible();
		const seen = await page.evaluate((rowSelector: string) => {
			const ids = Array.from(document.querySelectorAll<HTMLElement>(rowSelector))
				.filter(row => row.getClientRects().length > 0)
				.map(row => row.dataset.chatId)
				.filter((id): id is string => Boolean(id && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(id)));
			return { ids, at: performance.now() };
		}, ROW_SELECTOR);
		recentRowsMS.push(Math.round(seen.at));

		const active = page.getByTestId('active-chat-container');
		const current = await active.getAttribute('data-current-chat-id');
		const chatId = seen.ids.find((id: string) => id !== current && !selected.has(id));
		if (!chatId) throw new Error('Expected another existing recent conversation');
		selected.add(chatId);
		const row = page.locator(ROW_SELECTOR + '[data-chat-id="' + chatId + '"]');
		const start = await page.evaluate(() => performance.now());
		await row.click();
		await expect(active).toHaveAttribute('data-current-chat-id', chatId);
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count'))).toBeGreaterThan(0);
		await expect(page.getByTestId('chat-history-content')).toBeVisible();
		await expect(active).toHaveAttribute('data-current-message-chat-consistent', 'true');
		visibleMessageMS.push(Math.round(await page.evaluate(() => performance.now()) - start));
	}
	await testInfo.attach('personal-devtest-web-timings', {
		body: JSON.stringify({ cached_navigation_to_recent_rows_ms: recentRowsMS, select_to_visible_message_ms: visibleMessageMS }),
		contentType: 'application/json',
	});
});
