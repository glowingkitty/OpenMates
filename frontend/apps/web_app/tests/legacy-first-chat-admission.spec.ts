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

// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent,operational-monitoring.chat-failures.email-trigger
test('epoch-zero first chat survives reload and a follow-up with Projects disabled', async ({ page }: { page: any }, testInfo: any) => {
	test.setTimeout(180_000);
	const projectRequests: string[] = [];
	const admissionFrames: Array<Record<string, any>> = [];
	const acknowledgements: Array<Record<string, any>> = [];
	const errors: Array<Record<string, any>> = [];
	const viewed: Array<Record<string, any>> = [];
	const initiated: Array<Record<string, any>> = [];
	const ready: Array<Record<string, any>> = [];
	const wireByTurn = new Map<string, Array<string | Buffer>>();
	let repeatTurn: ((turnId: string) => void) | undefined;
	// Force a real recovery scan while the first ordinary send has returned
	// from frame dispatch but is still awaiting its exact admission/context ACKs.
	let releaseAdmission: (() => void) | undefined;
	let overlapRecoveryCompleted = false;
	page.on('console', (message: any) => {
		if (releaseAdmission && /Completed indexed pending retry for 1 message/.test(message.text())) {
			overlapRecoveryCompleted = true;
		}
	});
	let injectedOverlap = false;
	await page.routeWebSocket('**/v1/ws**', (socket: any) => {
		const server = socket.connectToServer();
		server.onMessage((message: string | Buffer) => {
			try {
				const frame = JSON.parse(String(message));
				if (frame.type === 'chat_turn_preflight_ack') acknowledgements.push(frame.payload ?? {});
				if (frame.type === 'error') errors.push(frame.payload ?? {});
				if (frame.type === 'ai_task_initiated') initiated.push(frame.payload ?? {});
				if (frame.type === 'ai_message_ready') ready.push(frame.payload ?? {});
			} catch { /* Control frame. */ }
			socket.send(message);
		});
		socket.onMessage((message: string | Buffer) => {
			let frame: any;
			try { frame = JSON.parse(String(message)); } catch { /* Control frame. */ }
			// Playwright's routed sockets bypass page WebSocket frame events.
			// Observe the real client frame here, including the held admission.
			if (frame?.type === 'chat_turn_admit') admissionFrames.push(frame.payload ?? {});
			if (frame?.type === 'chat_message_viewed') viewed.push(frame.payload ?? {});
			if (frame?.type === 'chat_turn_admit') wireByTurn.set(frame.payload.turn_id, []);
			if (frame?.payload?.turn_id && ['chat_turn_admit', 'chat_turn_context_ready'].includes(frame.type)) {
				wireByTurn.get(frame.payload.turn_id)?.push(message);
			}
			repeatTurn = (turnId: string) => {
				const wire = wireByTurn.get(turnId);
				expect(wire?.length, 'Replay the original admission and context frames').toBeGreaterThan(0);
				for (const original of wire!) server.send(original);
			};
			if (!injectedOverlap && frame?.type === 'chat_turn_admit') {
				injectedOverlap = true;
				releaseAdmission = () => server.send(message);
				socket.send(JSON.stringify({ type: 'phased_sync_complete', payload: {
					phase: 'complete', timestamp: Date.now() / 1000,
				} }));
				return;
			}
			server.send(message);
		});
	});
	await page.route('**/v1/features/availability', async (route: any) => {
		const response = await route.fetch();
		if (!response.ok()) throw new Error(`Feature availability failed (${response.status()}).`);
		const data = await response.json();
		await route.fulfill({ response, json: { ...data,
			disabled: [...new Set([...(data.disabled ?? []), 'platform:projects'])] } });
	});
	await page.route('**/v1/projects**', (route: any) => {
		projectRequests.push(route.request().url());
		return route.fulfill({ status: 404, json: { detail: 'FEATURE_DISABLED' } });
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

	const sending = sendMessage(page, withMockMarker('Capital of Germany?', 'chat_flow_capital', 'instant'));
	void sending.catch(() => undefined); // The helper waits for the ACK held below.
	try {
		await expect.poll(() => overlapRecoveryCompleted, {
			timeout: 8_000, message: 'Recovery must inspect the pending journal before admission ACK',
		}).toBe(true);
		expect(admissionFrames, 'Recovery must share the ordinary in-flight admission').toHaveLength(1);
	} finally {
		releaseAdmission?.();
	}
	await sending;
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
	await page.bringToFront();
	await expect.poll(() => viewed.filter(frame => frame.chat_id === chatId).length,
		{ timeout: 15_000, message: 'Visible synced messages must emit read receipts' }).toBeGreaterThan(0);
	await page.evaluate(() => new Promise<void>(resolve => {
		let frames = 60;
		const next = () => --frames <= 0 ? resolve() : requestAnimationFrame(next);
		requestAnimationFrame(next);
	}));
	const initialViewed = viewed.filter(frame => frame.chat_id === chatId).map(frame => frame.message_id);
	expect(initialViewed.length, 'Animation frames must not queue duplicate read receipts ahead of send preparation')
		.toBe(new Set(initialViewed).size);
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
	// Replay the completed follow-up's real admission/context wire. Unlike an
	// epoch-zero first turn, this includes the client's frozen prior history.
	await expect.poll(async () => (await canonicalWindow()).messages.filter((row) => row.role === 'assistant').length,
		{ timeout: 30_000, message: 'Both assistant responses must be canonical before the exact resend' }).toBe(2);
	const second = admissionFrames[1];
	const originalTask = initiated.find((frame) => frame.user_message_id === second.message_id)?.ai_task_id;
	expect(originalTask).toBeTruthy();
	expect(repeatTurn).toBeDefined();
	const readyBeforeRetry = ready.length;
	repeatTurn!(second.turn_id);
	await expect.poll(() => ready.slice(readyBeforeRetry).some((frame) => frame.message_id === originalTask),
		{ timeout: 30_000, message: 'Exact completed resend must reconcile the original response' }).toBe(true);
	expect(initiated.filter((frame) => frame.user_message_id === second.message_id),
		'A completed resend must not restart the processing indicator').toHaveLength(1);
	expect((await canonicalWindow()).messages.filter((row) => row.role === 'assistant')).toHaveLength(2);
	expect(errors.filter((frame) => frame.user_message_id === second.message_id || frame.message_id === second.message_id)).toHaveLength(0);
	await testInfo.attach('admission-identities', { contentType: 'application/json', body: JSON.stringify({
		admissions: admissionFrames.map(({ chat_id, turn_id, message_id, expected_messages_v }) =>
			({ chat_id, turn_id, message_id, expected_messages_v })),
		acknowledgements: acknowledgements.map(({ turn_id, state, committed_messages_v }) =>
			({ turn_id, state, committed_messages_v })),
		errors: errors.map(({ code, chat_id, turn_id, message_id, user_message_id }) =>
			({ code, chat_id, turn_id, message_id, user_message_id })),
	}) });
	expect(errors.filter((error) => error.code === 'inference_temporarily_paused'
		|| error.code === 'chat_not_found')).toHaveLength(0);
	expect(admissionFrames, 'One admission per user turn across recovery and reload').toHaveLength(2);
	expect(projectRequests).toEqual([]);
	await deleteActiveChat(page);
});
