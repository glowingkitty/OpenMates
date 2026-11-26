/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS test helpers. */
// contract-test-file: tooling
/** Read-only, deployed-dev timings. Use the private Personal DevTest workflow. */
export {};

const { test, expect } = require('@playwright/test');
const { loginToTestAccount, waitForChatReady, dismissSecurityReminderIfPresent } = require('./helpers/chat-test-helpers');
const DEV_ORIGIN = 'https://app.dev.openmates.org';
const ROW_SELECTOR = '[data-testid="activity-history-wrapper"] [data-testid="chat-item-wrapper"][data-chat-id]';

test('Personal DevTest opens existing conversations after a cached launch', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
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
	const transports: Array<{ closed: boolean }> = [];
	page.on('websocket', (socket: any) => {
		if (!socket.url().includes('/v1/ws')) return;
		const observed = { closed: false };
		transports.push(observed);
		socket.on('close', () => { observed.closed = true; });
	});
	await page.addInitScript(() => {
		const BaseSocket = window.WebSocket;
		const chatSockets: WebSocket[] = [];
		(window as typeof window & { __devTestChatSockets?: WebSocket[] }).__devTestChatSockets = chatSockets;
		window.WebSocket = class extends BaseSocket {
			constructor(url: string | URL, protocols?: string | string[]) {
				super(url, protocols);
				if (String(url).includes('/v1/ws')) chatSockets.push(this);
			}
		};
	});
	await loginToTestAccount(page, undefined, undefined, { credentials });
	await dismissSecurityReminderIfPresent(page);
	await waitForChatReady(page);

	const recentRowsMS: number[] = [];
	const visibleMessageMS: number[] = [];
	const selected = new Set<string>();
	const active = page.getByTestId('active-chat-container');
	const assertTranscript = async (chatId: string) => {
		await expect(active).toHaveAttribute('data-current-chat-id', chatId);
		await expect.poll(async () => Number(await active.getAttribute('data-current-message-count'))).toBeGreaterThan(0);
		await expect(page.getByTestId('chat-history-content')).toBeVisible();
		await expect(active).toHaveAttribute('data-current-message-chat-consistent', 'true');
	};
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

		const current = await active.getAttribute('data-current-chat-id');
		const chatId = seen.ids.find((id: string) => id !== current && !selected.has(id));
		if (!chatId) throw new Error('Expected another existing recent conversation');
		selected.add(chatId);
		const row = page.locator(ROW_SELECTOR + '[data-chat-id="' + chatId + '"]');
		const start = await page.evaluate(() => performance.now());
		await row.click();
		await assertTranscript(chatId);
		visibleMessageMS.push(Math.round(await page.evaluate(() => performance.now()) - start));
	}
	await testInfo.attach('personal-devtest-web-timings', {
		body: JSON.stringify({ cached_navigation_to_recent_rows_ms: recentRowsMS, select_to_visible_message_ms: visibleMessageMS }),
		contentType: 'application/json',
	});

	// Use only the conversations already opened above. Keep both the existing
	// transcript and a second cached selection usable across an actual socket loss.
	const [first, , last] = [...selected];
	if (!first || !last) throw new Error('Expected three distinct existing conversations');
	const original = transports.at(-1);
	expect(original?.closed).toBe(false);
	const previousTransportCount = transports.length;
	await context.setOffline(true);
	try {
		await page.evaluate(() => {
			const sockets = (window as typeof window & { __devTestChatSockets?: WebSocket[] }).__devTestChatSockets ?? [];
			for (const socket of sockets) {
				if (socket.readyState === WebSocket.OPEN) socket.close(1000, 'Read-only development benchmark');
			}
		});
		await expect.poll(() => original?.closed).toBe(true);
		await assertTranscript(last);
		await page.evaluate((id: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(id)}`;
		}, first);
		await assertTranscript(first);
	} finally {
		await context.setOffline(false);
	}
	await expect.poll(() => transports.slice(previousTransportCount).some(socket => !socket.closed)).toBe(true);
	await waitForChatReady(page);
	await assertTranscript(first);
	await expect(active).toHaveAttribute('data-current-message-ids-unique', 'true');
});
