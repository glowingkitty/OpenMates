/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed
/**
 * A refused or missing embed read is a missing embed, not a server failure
 * (issue JP9NV): the backend answers with a coded 404 frame and the web app
 * shows no "Server error: Embed not found" notification for it.
 */
export {};

import type { Page } from '@playwright/test';
import { randomUUID } from 'node:crypto';

const { expect, test } = require('./helpers/cookie-audit');
const { dismissSecurityReminderIfPresent, loginToTestAccount } = require('./helpers/chat-test-helpers');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type ReceivedFrame = { type: string; payload: Record<string, unknown> };

/** Keeps the app's own WebSocket reachable so the test can send one protocol frame on it. */
async function exposeAppSocket(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const NativeWebSocket = window.WebSocket;
		const sockets: WebSocket[] = [];
		(window as Window & { __embedNotFoundProbe?: (frame: string) => void }).__embedNotFoundProbe = (frame) => {
			const open = sockets.filter((socket) => socket.readyState === NativeWebSocket.OPEN).pop();
			if (!open) throw new Error('No open app WebSocket');
			open.send(frame);
		};
		function ProbeWebSocket(this: WebSocket, ...args: ConstructorParameters<typeof WebSocket>) {
			const socket = new NativeWebSocket(...args);
			sockets.push(socket);
			return socket;
		}
		Object.setPrototypeOf(ProbeWebSocket, NativeWebSocket);
		ProbeWebSocket.prototype = NativeWebSocket.prototype;
		window.WebSocket = ProbeWebSocket as unknown as typeof WebSocket;
	});
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
test('a missing embed read gets a coded 404 and no Server error notification', async ({ page }: { page: Page }) => {
	test.setTimeout(180000);
	test.skip(!getTestAccount().email, 'Test account credentials required.');

	const received: ReceivedFrame[] = [];
	page.on('websocket', (websocket) => {
		websocket.on('framereceived', (frame) => {
			try {
				const parsed = JSON.parse(String(frame.payload ?? ''));
				if (parsed && typeof parsed.type === 'string' && parsed.payload && typeof parsed.payload === 'object') {
					received.push({ type: parsed.type, payload: parsed.payload });
				}
			} catch {
				// Control frames are not JSON protocol messages.
			}
		});
	});
	await exposeAppSocket(page);

	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await loginToTestAccount(page);
	await dismissSecurityReminderIfPresent(page);
	await expect(page.locator('[data-action="message-input"]').last()).toBeVisible({ timeout: 60000 });

	// An embed that never existed: the server must refuse it as not found.
	const missingEmbedId = randomUUID();
	await expect
		.poll(() => page.evaluate((frame: string) => {
			try {
				(window as Window & { __embedNotFoundProbe?: (frame: string) => void }).__embedNotFoundProbe!(frame);
				return true;
			} catch {
				return false;
			}
		}, JSON.stringify({ type: 'request_embed', payload: { embed_id: missingEmbedId } })), { timeout: 30000 })
		.toBe(true);

	await expect
		.poll(() => received.find((frame) => frame.type === 'error' && frame.payload.embed_id === missingEmbedId)?.payload ?? null,
			{ timeout: 30000 })
		.toEqual({ message: 'Embed not found', status: 404, code: 'embed_not_found', embed_id: missingEmbedId });

	// Give the notification store time to render a toast if the frame were treated as a server failure.
	await page.waitForTimeout(2000);
	await expect(page.getByText('Server error: Embed not found', { exact: true })).toHaveCount(0);
	await test.info().attach('no-server-error-toast', { body: await page.screenshot(), contentType: 'image/png' });
});
