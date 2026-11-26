/* eslint-disable @typescript-eslint/no-require-imports -- CommonJS test helpers. */
// contract-test-file: tooling
/** Read-only, deployed-dev timings. Use the private Personal DevTest workflow. */
import type { WebSocketRoute } from "@playwright/test";

const { test, expect } = require('@playwright/test');
const { createBrowserProcessEvidence } = require('./helpers/browser-process-evidence.cjs');
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
	let offline = false;
	const transports: Array<{ socket: WebSocketRoute; server: WebSocketRoute }> = [];
	let receivedFrames = 0;
	let receivedBytes = 0;
	await page.routeWebSocket(/\/v1\/ws(?:\?|$)/, async (socket: WebSocketRoute) => {
		if (offline) {
			await socket.close({ code: 3001, reason: 'Development benchmark transport offline' });
			return;
		}
		const server = socket.connectToServer();
		transports.push({ socket, server });
		server.onMessage((data) => {
			receivedFrames++;
			receivedBytes += typeof data === 'string' ? Buffer.byteLength(data) : data.length;
			socket.send(data);
		});
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
	const hasOpenTransport = () => page.evaluate(() => {
		const sockets = (window as typeof window & { __devTestChatSockets?: WebSocket[] }).__devTestChatSockets ?? [];
		return sockets.some(socket => socket.readyState === WebSocket.OPEN);
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
		recentRowsMS.push(Math.round(await page.evaluate(() => performance.now())));

		// The first cached row is the startup milestone. More rows may be
		// published in later frames, so find a different candidate separately.
		const findAnotherChat = async () => {
			const current = await active.getAttribute('data-current-chat-id');
			return page.evaluate(({ rowSelector, excluded }: { rowSelector: string; excluded: string[] }) =>
				Array.from(document.querySelectorAll<HTMLElement>(rowSelector))
					.filter(row => row.getClientRects().length > 0)
					.map(row => row.dataset.chatId)
					.find(id => !!id && /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(id) && !excluded.includes(id)) ?? null,
			{ rowSelector: ROW_SELECTOR, excluded: [...selected, current ?? ''] });
		};
		let candidate: string | null = null;
		await expect.poll(async () => {
			candidate = await findAnotherChat();
			return candidate !== null;
		}, { timeout: 15000, message: 'A different existing recent chat becomes selectable' }).toBe(true);
		const chatId = candidate!;
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

	// Capture idle work in the same known browser process tree. Store only
	// resource totals and process aggregates in encrypted CI evidence.
	const processMeter = await createBrowserProcessEvidence(page);
	try {
		const begin = await processMeter.begin();
		const start = { frames: receivedFrames, bytes: receivedBytes };
		await new Promise(resolve => setTimeout(resolve, 15000));
		const end = await processMeter.end();
		await testInfo.attach('personal-devtest-web-idle', {
			body: JSON.stringify({ observation_ms: 15000, begin, end,
				received_websocket_frames: receivedFrames - start.frames,
				received_websocket_bytes: receivedBytes - start.bytes }),
			contentType: 'application/json',
		});
	} finally {
		await processMeter.close();
	}

	// Use only the conversations already opened above. Keep both the existing
	// transcript and a second cached selection usable across an actual socket loss.
	const [first, , last] = [...selected];
	if (!first || !last) throw new Error('Expected three distinct existing conversations');
	await expect.poll(hasOpenTransport, { timeout: 15000 }).toBe(true);
	const original = transports.at(-1);
	if (!original) throw new Error('Expected the real development WebSocket route');
	const previousTransportCount = transports.length;
	offline = true;
	await context.setOffline(true);
	try {
		// Closing the route in both directions also works when the network can
		// no longer complete a browser-initiated close handshake.
		const close = { code: 3001, reason: 'Read-only development benchmark disconnect' };
		await Promise.all(transports.flatMap(({ socket, server }) => [socket.close(close), server.close(close)]));
		await expect.poll(hasOpenTransport, { timeout: 15000 }).toBe(false);
		await assertTranscript(last);
		await page.evaluate((id: string) => {
			window.location.hash = `chat-id=${encodeURIComponent(id)}`;
		}, first);
		await assertTranscript(first);
	} finally {
		offline = false;
		await context.setOffline(false);
	}
	await expect.poll(() => transports.length, { timeout: 30000 }).toBeGreaterThan(previousTransportCount);
	await expect.poll(hasOpenTransport, { timeout: 30000 }).toBe(true);
	await waitForChatReady(page);
	await assertTranscript(first);
	await expect(active).toHaveAttribute('data-current-message-ids-unique', 'true');
});
