/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed
/**
 * Follow-ups on a backend whose chat recovery protocol epoch is not activated
 * (production default; the default CI profile has no epoch fixture).
 * - Reported flow (prod issue LKYPL): after a reload, send-time reply discovery
 *   answers 'disabled'; the follow-up must send instead of bouncing back into
 *   the editor.
 * - In-session flow: the first turn is admitted as LEGACY, so its reply must be
 *   stored through legacy storage; otherwise the follow-up waits forever.
 */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount, startNewChat, sendMessage, waitForChatReady } = require('./helpers/chat-test-helpers');
const { openChatAfterContextSync } = require('./helpers/chat-hydration');

const { email, password, otpKey } = getTestAccount();

function captureProtocol(page: any) {
	const state = {
		discoveries: [] as Array<{ status?: string }>,
		sendErrors: [] as string[],
		frames: [] as string[],
		consoleLines: [] as string[],
	};
	page.on('websocket', (socket: any) => {
		const capture = (direction: string) => (frame: any) => {
			try {
				const parsed = JSON.parse(String(frame.payload));
				state.frames.push(`${new Date().toISOString()} ${direction} ${parsed.type}${parsed.payload?.state ? `:${parsed.payload.state}` : ''}`);
				if (direction === 'received' && parsed.type === 'recovery_outputs_discovery_complete') {
					state.discoveries.push(parsed.payload ?? {});
				}
			} catch { /* Ignore non-JSON control frames. */ }
		};
		socket.on('framesent', capture('sent'));
		socket.on('framereceived', capture('received'));
	});
	page.on('console', (message: any) => {
		const text = message.text();
		if (message.type() === 'error' && text.includes('Failed to handle message send')) state.sendErrors.push(text);
		if (['error', 'warning'].includes(message.type()) || /ChatSyncService|recovery|predecessor/i.test(text)) {
			state.consoleLines.push(`${new Date().toISOString()} ${message.type()} ${text.slice(0, 400)}`);
		}
	});
	const storageConfirmations = () => state.frames.filter(line => line.endsWith('received ai_response_storage_confirmed')).length;
	return { state, storageConfirmations };
}

async function attachProtocol(testInfo: any, name: string, state: Record<string, unknown> & { consoleLines: string[] }) {
	await testInfo.attach(name, {
		body: JSON.stringify({ ...state, consoleLines: state.consoleLines.slice(-300) }),
		contentType: 'application/json',
	});
}

async function expectFollowupAnswered(page: any, sendErrors: string[]) {
	await expect(page.getByTestId('message-user')).toHaveCount(2, { timeout: 30000 });
	await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 90000 });
	await expect(page.getByTestId('message-user').last()).not.toHaveAttribute('data-status', 'failed');
	await expect(page.getByTestId('message-editor').last()).not.toContainText('And the next capital?');
	expect(sendErrors).toEqual([]);
}

// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.completion.lease-fenced
test('follow-up after reload sends while recovery discovery is disabled', async ({ page }: { page: any }, testInfo: any) => {
	skipWithoutCredentials(test, email, password, otpKey);
	test.setTimeout(240000);
	const { state, storageConfirmations } = captureProtocol(page);
	const log = (msg: string, meta?: Record<string, unknown>) => console.log(`[FOLLOWUP_DISABLED_RELOAD] ${msg}`, meta ?? '');
	try {
		await loginToTestAccount(page, log);
		await startNewChat(page, log);
		await sendMessage(page, withMockMarker('What is the capital?', 'chat_flow_capital'), log);
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
		const chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)![1];
		await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
		// The epoch-zero reply is stored through legacy storage and acknowledged.
		await expect.poll(storageConfirmations, { timeout: 60000 }).toBeGreaterThan(0);

		// Like the reporting user: come back to the chat in a fresh page session.
		await page.reload({ waitUntil: 'domcontentloaded' });
		await waitForChatReady(page, log);
		await openChatAfterContextSync(page, chatId, testInfo);
		await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 30000 });

		const discoveriesBeforeFollowup = state.discoveries.length;
		await sendMessage(page, withMockMarker('And the next capital?', 'chat_flow_capital'), log);
		await expect.poll(() => state.discoveries.slice(discoveriesBeforeFollowup).map(d => d.status), { timeout: 30000 })
			.toContain('disabled');
		await expectFollowupAnswered(page, state.sendErrors);
	} finally {
		await attachProtocol(testInfo, 'followup-recovery-disabled-reload', state);
	}
});

// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.completion.lease-fenced
test('immediate in-session follow-up is not blocked by a LEGACY first turn', async ({ page }: { page: any }, testInfo: any) => {
	skipWithoutCredentials(test, email, password, otpKey);
	test.setTimeout(180000);
	const { state, storageConfirmations } = captureProtocol(page);
	const log = (msg: string, meta?: Record<string, unknown>) => console.log(`[FOLLOWUP_DISABLED_INSESSION] ${msg}`, meta ?? '');
	try {
		await loginToTestAccount(page, log);
		await startNewChat(page, log);
		await sendMessage(page, withMockMarker('What is the capital?', 'chat_flow_capital'), log);
		await expect(page).toHaveURL(/chat-id=[a-zA-Z0-9-]+/, { timeout: 15000 });
		await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 90000 });
		expect(state.frames.some(line => line.endsWith('received chat_turn_preflight_ack:LEGACY'))).toBe(true);

		await sendMessage(page, withMockMarker('And the next capital?', 'chat_flow_capital'), log);
		await expectFollowupAnswered(page, state.sendErrors);
		// Both LEGACY replies were handed to legacy storage and acknowledged.
		await expect.poll(storageConfirmations, { timeout: 60000 }).toBeGreaterThanOrEqual(2);
	} finally {
		await attachProtocol(testInfo, 'followup-recovery-disabled-in-session', state);
	}
});
