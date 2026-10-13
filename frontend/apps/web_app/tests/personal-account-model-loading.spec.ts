/* eslint-disable @typescript-eslint/no-require-imports */
/*
 * Authenticated account-health regression for reported issue 4NPP9.
 * Persists an exact model, reloads the same chat, and verifies account-scoped
 * restoration completes without a retry notification or permanently loading
 * model selector. This reproduces the delayed restore race from issue XW4UW.
 * proof-video: not_required reason=account_health
 */

export {};

const { test, expect, attachConsoleListeners, attachNetworkListeners } = require('./console-monitor');
const { createSignupLogger, createStepScreenshotter, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, waitForChatReady, startNewChat, deleteActiveChat } = require('./helpers/chat-test-helpers');

const TEST_CREDENTIALS = {
	email: process.env.OPENMATES_TEST_ACCOUNT_EMAIL || '',
	password: process.env.OPENMATES_TEST_ACCOUNT_PASSWORD || '',
	otpKey: process.env.OPENMATES_TEST_ACCOUNT_OTP_KEY || ''
};

// contract-test: supporting surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,message-input.send.ownership
test('authenticated account loads its chat model selector without retry errors', async ({ page }) => {
	test.setTimeout(180000);
	expect(TEST_CREDENTIALS.email).not.toBe('');
	expect(TEST_CREDENTIALS.password).not.toBe('');
	expect(TEST_CREDENTIALS.otpKey).not.toBe('');

	const logCheckpoint = createSignupLogger('PERSONAL_ACCOUNT_MODEL_LOADING');
	const takeStepScreenshot = createStepScreenshotter(logCheckpoint, {
		filenamePrefix: 'personal-account-model-loading'
	});
	attachConsoleListeners(page, logCheckpoint);
	attachNetworkListeners(page, logCheckpoint);
	const preferenceFrames: Array<{ type: string; code?: string }> = [];
	page.on('websocket', (websocket: any) => {
		websocket.on('framereceived', (frame: { payload?: string | Buffer }) => {
			try {
				const message = JSON.parse(String(frame.payload ?? ''));
				if (['chat_model_preference_updated', 'chat_model_preference_conflict', 'error'].includes(message.type)) {
					preferenceFrames.push({ type: message.type, code: typeof message.payload?.code === 'string' ? message.payload.code : undefined });
				}
			} catch {
				// WebSocket control frames are not JSON protocol messages.
			}
		});
	});

	await page.addInitScript(() => {
		(window as any).__issue4NPP9Notifications = [];
		document.addEventListener('DOMContentLoaded', () => {
			const recordNotifications = (): void => {
				for (const element of document.querySelectorAll('[data-testid="notification"]')) {
					const text = element.textContent?.trim();
					if (text && !(window as any).__issue4NPP9Notifications.includes(text)) {
						(window as any).__issue4NPP9Notifications.push(text);
					}
				}
			};
			new MutationObserver(recordNotifications).observe(document.body, { childList: true, subtree: true });
			recordNotifications();
		});
	});
	const initialSyncCompleted = page.waitForEvent('console', {
		predicate: (message: any) => message.text().includes('phased_sync_complete'),
		timeout: 60000
	});

	await loginToTestAccount(page, logCheckpoint, takeStepScreenshot, {
		credentials: TEST_CREDENTIALS,
		waitForEditor: false
	});
	await initialSyncCompleted;

	const activeChat = page.getByTestId('active-chat-container');
	const composer = activeChat.getByTestId('message-field').last();
	const editor = composer.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 60000 });
	await editor.click();
	await page.keyboard.type(withMockMarker('Create an owned chat for model preference restoration.', 'chat_flow_capital'));
	const sendButton = page.locator('[data-action="send-message"]');
	await expect(sendButton).toBeEnabled({ timeout: 15000 });
	await sendButton.click();
	await expect(activeChat).toHaveAttribute('data-current-chat-id', /.+/, { timeout: 60000 });

	await editor.click();

	const selector = composer.getByTestId('composer-model-selector');
	await expect(selector).toBeVisible({ timeout: 30000 });
	await expect(selector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	await expect(composer.getByTestId('composer-model-selector-label')).not.toHaveText('Loading...');
	// The first send may finish while the selector restores. Enter the focused
	// composer state before interacting with its controls, as a user would.
	await editor.click();
	await expect(composer).toHaveAttribute('data-focused', 'true');
	await expect(selector).toBeVisible();
	const notificationsBeforeSelection = await page.evaluate(() => (window as any).__issue4NPP9Notifications as string[]);
	expect(notificationsBeforeSelection).not.toContain("Could not load this chat's model setting. Auto is being used.");

	await selector.click();
	const selectorMenu = composer.getByTestId('composer-model-selector-menu');
	await expect(selectorMenu).toBeVisible();
	await selectorMenu.getByTestId('composer-model-provider-openai').click();
	const modelRows = selectorMenu.getByTestId('composer-model-row');
	let targetToggle: any = null;
	for (let index = 0; index < await modelRows.count(); index += 1) {
		const candidate = modelRows.nth(index).getByTestId('composer-model-toggle');
		if (!await candidate.getByRole('checkbox').isChecked()) {
			targetToggle = candidate;
			break;
		}
	}
	expect(targetToggle).not.toBeNull();
	const selectionFrameStart = preferenceFrames.length;
	await targetToggle.click();
	await expect.poll(() => {
		const frames = preferenceFrames.slice(selectionFrameStart);
		if (frames.some((frame) => frame.type === 'chat_model_preference_updated')) return 'updated';
		const error = frames.find((frame) => frame.type === 'error');
		return error ? `error:${error.code ?? 'unknown'}` : 'pending';
	}, { timeout: 30000 }).toBe('updated');
	await expect(selector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	const selectedLabel = composer.getByTestId('composer-model-selector-label');
	await expect(selectedLabel).not.toHaveText('Auto select');
	const persistedModelLabel = await selectedLabel.textContent();
	expect(persistedModelLabel).toBeTruthy();

	const persistedChatId = await activeChat.getAttribute('data-current-chat-id');
	expect(persistedChatId).toBeTruthy();
	await page.addInitScript(() => {
		const trace: Array<Record<string, unknown>> = [];
		(window as any).__savedComposerInputTrace = trace;
		const ids = new WeakMap<Element, number>();
		let nextId = 1;
		let lastDom = '';
		const describe = (element: Element | null): string => {
			if (!element) return 'none';
			if (element.matches('.ProseMirror')) return 'prosemirror';
			if (element.matches('[data-testid="message-editor"]')) return 'editor-wrapper';
			return element.getAttribute('data-testid') || element.tagName.toLowerCase();
		};
		const snapshot = (kind: string, detail?: string) => {
			const editors = [...document.querySelectorAll('[data-testid="active-chat-container"] [data-testid="message-editor"]')];
			const editorState = editors.map((element) => {
				if (!ids.has(element)) ids.set(element, nextId++);
				return { id: ids.get(element), length: element.textContent?.length ?? 0,
					prefix: element.textContent?.slice(0, 40) ?? '', pm: !!element.querySelector('.ProseMirror') };
			});
			trace.push({ t: Math.round(performance.now()), kind, detail,
				active: describe(document.activeElement), chat: document.querySelector('[data-testid="active-chat-container"]')?.getAttribute('data-current-chat-id'),
				editors: editorState });
			// Keep the first edit/focus transition even when later typing fills the tail.
			if (trace.length > 600) trace.splice(180, trace.length - 600);
		};
		for (const kind of ['pointerdown', 'focusin', 'focusout', 'keydown', 'beforeinput', 'input']) {
			document.addEventListener(kind, (event) => {
				const detail = event instanceof KeyboardEvent ? event.key :
					event instanceof InputEvent ? event.inputType : describe(event.target instanceof Element ? event.target : null);
				snapshot(kind, detail);
			}, true);
		}
		document.addEventListener('DOMContentLoaded', () => {
			new MutationObserver(() => {
				const current = [...document.querySelectorAll('[data-testid="active-chat-container"] [data-testid="message-editor"]')]
					.map((element) => `${element.textContent?.length ?? 0}:${element.textContent?.slice(0, 40) ?? ''}`).join('|');
				if (current !== lastDom) { lastDom = current; snapshot('dom'); }
			}).observe(document.body, { childList: true, characterData: true, subtree: true });
		});
	});
	await page.reload({ waitUntil: 'domcontentloaded' });
	await expect(activeChat).toHaveAttribute('data-current-chat-id', persistedChatId!, { timeout: 60000 });

	const restoredComposer = activeChat.getByTestId('message-field').last();
	await expect(restoredComposer.getByTestId('message-editor')).toBeVisible({ timeout: 60000 });
	await restoredComposer.getByTestId('message-editor').click();
	const restoredPrompt = withMockMarker('Send immediately after the saved chat reloads.', 'chat_flow_capital');
	await page.keyboard.type(restoredPrompt);
	try {
		await expect(restoredComposer.getByTestId('message-editor')).toHaveText(restoredPrompt);
	} catch (error) {
		console.log('[SAVED_COMPOSER_INPUT_TRACE]', JSON.stringify(await page.evaluate(() => ({
			events: (window as any).__savedComposerInputTrace,
			messageInput: (window as any).__openmatesMessageInputDraftDiagnostics,
			draftRestore: (window as any).__openmatesDraftRestoreDiagnostics,
		}))));
		throw error;
	}
	const restoredSend = restoredComposer.getByTestId('composer-send-button');
	await expect(restoredSend).toBeEnabled();
	await restoredSend.click();
	await expect(activeChat.getByTestId('message-user').last()).toContainText('Send immediately after the saved chat reloads.');
	await expect(restoredComposer.getByTestId('message-editor')).not.toContainText('Send immediately after the saved chat reloads.');
	await restoredComposer.getByTestId('message-editor').click();
	await expect(restoredComposer).toHaveAttribute('data-focused', 'true');
	const restoredSelector = restoredComposer.getByTestId('composer-model-selector');
	await expect(restoredSelector).toBeVisible({ timeout: 30000 });
	await expect(restoredSelector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	const restoredLabel = restoredComposer.getByTestId('composer-model-selector-label');
	await expect(restoredLabel).toHaveText(persistedModelLabel!);
	await takeStepScreenshot(page, 'model-selector-restored');

	const notifications = await page.evaluate(() => (window as any).__issue4NPP9Notifications as string[]);
	expect(notifications.filter((message) => message.trim().toLowerCase() === 'try again')).toEqual([]);
	expect(notifications.some((message) => message.includes('Model selection is still loading'))).toBe(false);

	await restoredSelector.click();
	const cleanupFrameStart = preferenceFrames.length;
	const restoredSelectorMenu = restoredComposer.getByTestId('composer-model-selector-menu');
	await restoredSelectorMenu.getByTestId('composer-model-back').click();
	await restoredSelectorMenu.getByTestId('composer-model-auto').click();
	await expect.poll(() => preferenceFrames.slice(cleanupFrameStart).some((frame) => frame.type === 'chat_model_preference_updated'), { timeout: 30000 }).toBe(true);
	await expect(restoredSelector).toHaveAttribute('data-loading', 'false', { timeout: 30000 });
	await expect(restoredLabel).toHaveText('Auto select');
});

// contract-test: direct surface=gui.web assertions=chats.send.immediate-admission,message-input.send.ownership,chats.persistence.client-encrypted
test('failed post-admission Project discovery reports the exact turn without starting a Mate', async ({ page }) => {
	test.setTimeout(180000);
	expect(TEST_CREDENTIALS.email).not.toBe('');
	expect(TEST_CREDENTIALS.password).not.toBe('');
	expect(TEST_CREDENTIALS.otpKey).not.toBe('');
	const frames: Array<{ direction: 'sent' | 'received'; type: string; payload: Record<string, any> }> = [];
	let releaseAdmission!: () => void;
	const admissionDispatched = new Promise<void>((resolve) => { releaseAdmission = resolve; });
	page.on('websocket', (socket: any) => {
		if (!new URL(socket.url()).pathname.endsWith('/v1/ws')) return;
		for (const [event, direction] of [['framesent', 'sent'], ['framereceived', 'received']] as const) {
			socket.on(event, (frame: { payload?: string | Buffer }) => {
				try {
					const envelope = JSON.parse(String(frame.payload ?? ''));
					if (['chat_turn_admit', 'chat_turn_preflight_ack', 'chat_turn_context_ready',
						'chat_turn_context_failed', 'chat_turn_context_failed_ack', 'ai_typing_started',
						'ai_typing_ended', 'ai_task_error', 'error'].includes(envelope.type)) {
						frames.push({ direction, type: envelope.type, payload: envelope.payload ?? {} });
						if (direction === 'sent' && envelope.type === 'chat_turn_admit') releaseAdmission();
					}
				} catch { /* WebSocket control frame. */ }
			});
		}
	});
	await loginToTestAccount(page);
	await waitForChatReady(page);
	await startNewChat(page);
	await waitForChatReady(page);
	const activeChat = page.getByTestId('active-chat-container');
	const composer = activeChat.getByTestId('message-field').last();
	const editor = composer.getByTestId('message-editor');
	await expect(editor).toBeVisible();
	await expect(activeChat.getByTestId('message-user')).toHaveCount(0);
	const privateFailure = 'PRIVATE_PROJECT_DIRECTORY_RESPONSE_MUST_STAY_LOCAL';
	let projectDirectoryRequests = 0;
	await page.route('**/v1/projects**', async (route: any) => {
		if (new URL(route.request().url()).pathname !== '/v1/projects') {
			await route.continue();
			return;
		}
		projectDirectoryRequests += 1;
		await admissionDispatched;
		await route.fulfill({ status: 503, contentType: 'application/json',
			body: JSON.stringify({ detail: privateFailure }) });
	});
	const prompt = 'Check Project directory availability before answering this chat.';
	await editor.click();
	await page.keyboard.type(prompt);
	await expect(editor).toHaveText(prompt);
	await composer.getByTestId('composer-send-button').click();
	await expect.poll(() => frames.find((frame) => frame.direction === 'sent'
		&& frame.type === 'chat_turn_admit')?.payload ?? null, { timeout: 30000 }).not.toBeNull();
	await expect(activeChat.getByTestId('message-user').last()).toContainText(prompt, { timeout: 30000 });
	await expect(editor).toHaveText('');
	await expect.poll(() => frames.find((frame) => frame.direction === 'received'
		&& frame.type === 'chat_turn_context_failed_ack')?.payload?.status ?? null,
	{ timeout: 30000 }).toBe('accepted');
	const admitted = frames.find((frame) => frame.direction === 'sent' && frame.type === 'chat_turn_admit')!.payload;
	const preflightAck = frames.find((frame) => frame.direction === 'received'
		&& frame.type === 'chat_turn_preflight_ack' && frame.payload.turn_id === admitted.turn_id)?.payload;
	const failure = frames.find((frame) => frame.direction === 'sent' && frame.type === 'chat_turn_context_failed')?.payload;
	const failureAck = frames.find((frame) => frame.direction === 'received'
		&& frame.type === 'chat_turn_context_failed_ack')?.payload;
	const identity = { chat_id: admitted.chat_id, turn_id: admitted.turn_id,
		message_id: admitted.message_id, request_id: admitted.inference_request?.client_context_request_id };
	expect(projectDirectoryRequests).toBeGreaterThan(0);
	expect(admitted.inference_request?.client_context_pending).toBe(true);
	expect(preflightAck?.committed_messages_v).toBe(1);
	expect(admitted.encrypted_user_message?.encrypted_content).toBeTruthy();
	expect(failure).toEqual({ ...identity, reason: 'context_preparation_failed' });
	expect(failureAck).toEqual({ ...identity, status: 'accepted' });
	expect(JSON.stringify(failure)).not.toContain(privateFailure);
	expect(frames.findIndex((frame) => frame.direction === 'sent' && frame.type === 'chat_turn_admit'))
		.toBeLessThan(frames.findIndex((frame) => frame.direction === 'sent' && frame.type === 'chat_turn_context_failed'));
	expect(frames.some((frame) => frame.direction === 'sent' && frame.type === 'chat_turn_context_ready')).toBe(false);
	expect(frames.some((frame) => frame.direction === 'received' && frame.type === 'ai_typing_started')).toBe(false);
	await expect.poll(() => frames.find((frame) => frame.direction === 'received'
		&& frame.type === 'ai_typing_ended' && frame.payload.chat_id === admitted.chat_id
		&& frame.payload.user_message_id === admitted.message_id
		&& frame.payload.terminal_failure_code === 'client_context_unavailable')?.payload ?? null,
	{ timeout: 30000 }).not.toBeNull();
	const terminal = frames.find((frame) => frame.direction === 'received'
		&& frame.type === 'ai_typing_ended' && frame.payload.chat_id === admitted.chat_id
		&& frame.payload.user_message_id === admitted.message_id
		&& frame.payload.terminal_failure_code === 'client_context_unavailable')!.payload;
	expect(terminal.task_id).toBeTruthy();
	expect(terminal.message_id).toBe(terminal.task_id);
	await expect(activeChat.getByTestId('pending-assistant-response')).toHaveCount(0);
	await expect(activeChat.getByTestId('chat-processing-indicator')).toHaveCount(0);
	await expect(composer.getByTestId('stop-processing-button')).toHaveCount(0);
	await expect(activeChat.getByTestId('message-assistant')).toHaveCount(0);
	await expect(page.locator('body')).not.toContainText(privateFailure);
	await page.unroute('**/v1/projects**');
	await page.reload();
	await waitForChatReady(page);
	const restoredUser = page.getByTestId('active-chat-container').getByTestId('message-user').last();
	await expect(restoredUser).toContainText(prompt, { timeout: 30000 });
	await expect(restoredUser).toHaveAttribute('data-message-id', admitted.message_id);
	await expect(page.getByTestId('active-chat-container').getByTestId('message-assistant')).toHaveCount(0);
	await deleteActiveChat(page);
});
