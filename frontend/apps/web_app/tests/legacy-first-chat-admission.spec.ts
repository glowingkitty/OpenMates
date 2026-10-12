/* eslint-disable @typescript-eslint/no-require-imports */
/** Epoch-zero first send must have an owner-scoped durable chat before inference. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady, startNewChat,
	sendMessage, waitForAssistantMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');

const { email, password, otpKey } = getTestAccount();
const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
skipWithoutCredentials(test, email, password, otpKey);

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
test('epoch-zero first chat survives reload with one canonical user row and a follow-up', async ({ page }: { page: any }) => {
	test.setTimeout(180_000);
	const admissionFrames: Array<Record<string, any>> = [];
	const acknowledgements: Array<Record<string, any>> = [];
	const errors: Array<Record<string, any>> = [];
	page.on('websocket', (socket: any) => {
		if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
		for (const [event, target, type] of [
			['framesent', admissionFrames, 'chat_turn_admit'],
			['framereceived', acknowledgements, 'chat_turn_preflight_ack'],
			['framereceived', errors, 'error'],
		] as const) {
			socket.on(event, (frame: { payload?: string }) => {
				try {
					const envelope = JSON.parse(String(frame.payload || ''));
					if (envelope.type === type) target.push(envelope.payload ?? {});
				} catch { /* WebSocket control frame. */ }
			});
		}
	});
	// The isolated CI stack has no provider key; this only opens the UI send gate.
	await page.route('**/v1/settings/server-status', async (route: any) => {
		const response = await route.fetch();
		if (!response.ok()) throw new Error(`Server status failed (${response.status()}).`);
		await route.fulfill({ response, json: { ...await response.json(), ai_models_configured: true } });
	});
	await loginToTestAccount(page);
	await waitForChatReady(page);
	await startNewChat(page);
	await waitForChatReady(page);
	await expect(page.getByTestId('message-user')).toHaveCount(0);

	await sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
	await waitForAssistantMessage(page, { contains: 'Berlin', timeout: 60_000 });
	const first = admissionFrames[0];
	expect(first?.expected_messages_v).toBe(0);
	expect(first?.encrypted_chat_metadata?.encrypted_chat_key).toBe(first?.encrypted_chat_key);
	expect(first?.encrypted_user_message?.client_message_id).toBe(first?.message_id);
	expect(acknowledgements.find((ack) => ack.turn_id === first.turn_id)).toEqual(
		expect.objectContaining({ state: 'LEGACY', committed_messages_v: 1 }),
	);
	const chatId = first.chat_id as string;
	const firstMessageId = first.message_id as string;
	const canonicalWindow = async () => {
		const response = await page.request.get(
			`${apiUrl}/v1/chats/${encodeURIComponent(chatId)}/messages/window?limit=20&respect_compression_boundary=false`,
		);
		if (!response.ok()) return { status: response.status(), messages: [] as Record<string, any>[] };
		const body = await response.json();
		return { status: response.status(), messages: body.messages as Record<string, any>[] };
	};
	await expect.poll(async () => {
		const window = await canonicalWindow();
		const matching = window.messages.filter((row) => row.message_id === firstMessageId);
		return window.status === 200 && matching.length === 1
			&& matching[0].encrypted_content === first.encrypted_user_message.encrypted_content;
	}, { timeout: 30_000, message: 'First user ciphertext must exist exactly once in Directus' }).toBe(true);
	await page.reload();
	await waitForChatReady(page);
	await expect(page.getByTestId('message-user')).toHaveCount(1, { timeout: 30_000 });
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Berlin' })).toBeVisible();

	await sendMessage(page, withMockMarker('Capital of Germany again?', 'chat_flow_capital', 'instant'));
	await expect(page.getByTestId('message-user')).toHaveCount(2, { timeout: 60_000 });
	await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 60_000 });
	await expect.poll(async () => {
		const window = await canonicalWindow();
		const users = window.messages.filter((row) => row.role === 'user');
		return window.status === 200 && users.length === 2
			&& users.filter((row) => row.message_id === firstMessageId).length === 1
			&& users.every((row) => typeof row.encrypted_content === 'string' && row.encrypted_content.length > 0);
	}, { timeout: 30_000, message: 'Follow-up must add one canonical encrypted user row' }).toBe(true);
	expect(errors.filter((error) => error.code === 'inference_temporarily_paused'
		|| error.code === 'chat_not_found')).toHaveLength(0);
	await deleteActiveChat(page);
});
