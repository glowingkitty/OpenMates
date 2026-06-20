/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Anonymous free chat web contract tests.
 *
 * These specs run against app.dev.openmates.org through scripts/run_tests.py.
 * They cover the web-only browser behavior for anonymous free usage before the
 * broader backend anonymous streaming path is fully enabled.
 */

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl, assertNoMissingTranslations } = require('./signup-flow-helpers');

function anonymousActiveServerStatusBody() {
	return {
		is_self_hosted: false,
		payment_enabled: true,
		server_edition: 'development',
		domain: 'app.dev.openmates.org',
		ai_models_configured: true,
		anonymous_free_usage: {
			active: true,
			can_send_text: true,
			reason: null,
			reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
			cta: 'Create an account to keep using OpenMates.'
		}
	};
}

async function mockAnonymousActiveServerStatus(page: any) {
	await page.route('**/v1/settings/server-status', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(anonymousActiveServerStatusBody())
		});
	});
	await page.route('**/v1/anonymous/free-usage/status**', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				active: true,
				can_send_text: true,
				reason: null,
				reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
				cta: 'Create an account to keep using OpenMates.'
			})
		});
	});
}

async function mockAnonymousExhaustedServerStatus(page: any) {
	await page.route('**/v1/settings/server-status', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				...anonymousActiveServerStatusBody(),
				anonymous_free_usage: {
					active: false,
					can_send_text: false,
					reason: 'per_identity_exhausted',
					reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
					cta: 'Create an account to keep using OpenMates.'
				}
			})
		});
	});
	await page.route('**/v1/anonymous/free-usage/status**', async (route: any) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({
				active: false,
				can_send_text: false,
				reason: 'per_identity_exhausted',
				reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
				cta: 'Create an account to keep using OpenMates.'
			})
		});
	});
}

async function mockAnonymousChatStream(page: any, anonymousRequests: Array<Record<string, unknown>>) {
	await page.exposeFunction('recordAnonymousChatStreamRequest', (body: Record<string, unknown>) => {
		anonymousRequests.push(body);
		return anonymousRequests.length;
	});
	await page.addInitScript(() => {
		const originalFetch = window.fetch.bind(window);
		window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			if (url.includes('/v1/anonymous/chat/stream')) {
				const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
				const responseNumber = await (
					window as typeof window & {
						recordAnonymousChatStreamRequest: (body: Record<string, unknown>) => Promise<number>;
					}
				).recordAnonymousChatStreamRequest(body);
				return new Response(
					JSON.stringify({
						status: 'completed',
						messageId: `anonymous-assistant-${responseNumber}`,
						assistant: `Anonymous answer ${responseNumber}`,
						category: 'general_knowledge',
						modelName: 'test-model'
					}),
					{
						status: 200,
						headers: { 'content-type': 'application/json' }
					}
				);
			}
			return originalFetch(input, init);
		};
  });
}

async function mockDelayedAnonymousChatStream(
	page: any,
	anonymousRequests: Array<Record<string, unknown>>,
	responseDelayMs = 6000
) {
	await page.exposeFunction('recordDelayedAnonymousChatStreamRequest', (body: Record<string, unknown>) => {
		anonymousRequests.push(body);
		return anonymousRequests.length;
	});
	await page.addInitScript((delayMs: number) => {
		const originalFetch = window.fetch.bind(window);
		window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			if (url.includes('/v1/anonymous/chat/stream')) {
				const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
				const responseNumber = await (
					window as typeof window & {
						recordDelayedAnonymousChatStreamRequest: (body: Record<string, unknown>) => Promise<number>;
					}
				).recordDelayedAnonymousChatStreamRequest(body);
				await new Promise((resolve) => setTimeout(resolve, delayMs));
				return new Response(
					JSON.stringify({
						status: 'completed',
						messageId: body.client_message_id,
						assistant: `Delayed anonymous answer ${responseNumber}`,
						category: 'general_knowledge',
						modelName: 'test-model'
					}),
					{
						status: 200,
						headers: { 'content-type': 'application/json' }
					}
				);
			}
			return originalFetch(input, init);
		};
	}, responseDelayMs);
}

async function mockProgressiveAnonymousChatStream(page: any, anonymousRequests: Array<Record<string, unknown>>) {
	await page.exposeFunction('recordProgressiveAnonymousChatStreamRequest', (body: Record<string, unknown>) => {
		anonymousRequests.push(body);
		return anonymousRequests.length;
	});
	await page.addInitScript(() => {
		const originalFetch = window.fetch.bind(window);
		window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			if (url.includes('/v1/anonymous/chat/stream')) {
				const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
				const responseNumber = await (
					window as typeof window & {
						recordProgressiveAnonymousChatStreamRequest: (body: Record<string, unknown>) => Promise<number>;
					}
				).recordProgressiveAnonymousChatStreamRequest(body);
				const encoder = new TextEncoder();
				const assistantMessageId = `anonymous-progressive-assistant-${responseNumber}`;
				const taskId = `anonymous-task-${body.client_message_id}`;
				const writeEvent = (controller: ReadableStreamDefaultController<Uint8Array>, payload: Record<string, unknown>) => {
					controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
				};

				return new Response(
					new ReadableStream<Uint8Array>({
						async start(controller) {
							writeEvent(controller, {
								type: 'ai_task_initiated',
								chat_id: body.client_chat_id,
								user_message_id: body.client_message_id,
								ai_task_id: taskId,
								status: 'processing_started'
							});
							await new Promise((resolve) => setTimeout(resolve, 350));
							writeEvent(controller, {
								type: 'ai_typing_started',
								chat_id: body.client_chat_id,
								message_id: assistantMessageId,
								user_message_id: body.client_message_id,
								category: 'general_knowledge',
								model_name: 'test-model',
								provider_name: 'Test Provider',
								server_region: 'EU',
								title: 'Anonymous stream title',
								icon_names: ['ai'],
								task_id: taskId
							});
							await new Promise((resolve) => setTimeout(resolve, 350));
							writeEvent(controller, {
								type: 'ai_message_chunk',
								task_id: taskId,
								chat_id: body.client_chat_id,
								message_id: assistantMessageId,
								user_message_id: body.client_message_id,
								full_content_so_far: 'Partial anonymous stream',
								sequence: 1,
								is_final_chunk: false,
								model_name: 'test-model'
							});
							await new Promise((resolve) => setTimeout(resolve, 2500));
							writeEvent(controller, {
								type: 'ai_message_chunk',
								task_id: taskId,
								chat_id: body.client_chat_id,
								message_id: assistantMessageId,
								user_message_id: body.client_message_id,
								full_content_so_far: 'Partial anonymous stream complete',
								sequence: 2,
								is_final_chunk: true,
								model_name: 'test-model'
							});
							writeEvent(controller, {
								type: 'ai_task_ended',
								chatId: body.client_chat_id,
								taskId: taskId,
								status: 'completed'
							});
							writeEvent(controller, {
								type: 'post_processing_completed',
								chat_id: body.client_chat_id,
								task_id: taskId,
								follow_up_request_suggestions: [
									'Explain anonymous streaming in simpler terms',
									'Give practical examples of anonymous streaming',
									'What should I test next for anonymous chat',
									'Compare anonymous and signed-in streaming flows'
								],
								new_chat_request_suggestions: [],
								chat_summary: 'Anonymous streaming lifecycle completed',
								chat_tags: [],
								harmful_response: 0,
								quick_tip_slugs: []
							});
							controller.close();
						}
					}),
					{
						status: 200,
						headers: { 'content-type': 'text/event-stream' }
					}
				);
			}
			return originalFetch(input, init);
		};
	});
}

async function typeMessageText(page: any, text: string) {
	const editor = page.getByTestId('message-editor');
	const editable = editor.locator('[contenteditable="true"]').first();
	for (let attempt = 0; attempt < 3; attempt += 1) {
		await page.getByTestId('message-field').click();
		await expect(editor).toBeVisible({ timeout: 10000 });
		await expect(editable).toBeVisible({ timeout: 5000 });
		await editable.click();
		await page.waitForFunction(() => {
			const active = document.activeElement;
			return !!active && (active.getAttribute('data-testid') === 'message-editor' || !!active.closest?.('[data-testid="message-editor"]'));
		});
		await page.keyboard.press('Control+A');
		await page.keyboard.press('Backspace');
		await editable.pressSequentially(text);
		try {
			await expect(editor).toContainText(text, { timeout: 2000 });
			return editor;
		} catch (error) {
			if (attempt === 2) throw error;
			await page.waitForTimeout(250);
		}
	}
	return editor;
}

async function getAnonymousIndexedDbState(page: any) {
	return page.evaluate(
		() =>
			new Promise<{
				anonymousChats: Array<Record<string, unknown>>;
				anonymousMessages: Array<Record<string, unknown>>;
			}>((resolve, reject) => {
				const request = indexedDB.open('chats_db');
				request.onerror = () => reject(request.error);
				request.onsuccess = () => {
					const db = request.result;
					if (!db.objectStoreNames.contains('chats') || !db.objectStoreNames.contains('messages')) {
						db.close();
						resolve({ anonymousChats: [], anonymousMessages: [] });
						return;
					}
					const transaction = db.transaction(['chats', 'messages'], 'readonly');
					const chatsRequest = transaction.objectStore('chats').getAll();
					const messagesRequest = transaction.objectStore('messages').getAll();

					transaction.onerror = () => {
						db.close();
						reject(transaction.error);
					};
					transaction.oncomplete = () => {
						const anonymousChats = (chatsRequest.result as Array<Record<string, unknown>>).filter(
							(chat) => chat.is_anonymous === true
						);
						const anonymousChatIds = new Set(anonymousChats.map((chat) => chat.chat_id));
						const anonymousMessages = (messagesRequest.result as Array<Record<string, unknown>>).filter((message) =>
							anonymousChatIds.has(message.chat_id)
						);
						db.close();
						resolve({ anonymousChats, anonymousMessages });
					};
				};
			})
	);
}

test.describe('Anonymous free chat', () => {
	test('guest Learning Mode sends anonymous request context', async ({ page }: { page: any }) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

		const anonymousRequests: Array<Record<string, unknown>> = [];
		await mockAnonymousChatStream(page, anonymousRequests);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.evaluate(() => {
			window.sessionStorage.setItem('openmates.learningMode.enabled', 'true');
			window.sessionStorage.setItem('openmates.learningMode.ageGroup', '10_12');
		});
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();
		await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeVisible({
			timeout: 10000
		});

		await typeMessageText(page, 'Help me understand fractions');
		await expect(page.getByTestId('anonymous-terms-reminder')).toBeVisible({ timeout: 5000 });
		await page.locator('[data-action="send-message"]').click();

		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 1' })).toBeVisible({
			timeout: 10000
		});
		expect(anonymousRequests).toHaveLength(1);
		expect(anonymousRequests[0].learning_mode).toEqual({
			enabled: true,
			age_group: '10_12',
			source: 'anonymous_session'
		});
	});

	test('anonymous text chat shows terms reminder before send and feature notice in chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

		const anonymousRequests: Array<Record<string, unknown>> = [];
		await mockAnonymousChatStream(page, anonymousRequests);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();
		await expect(page.getByTestId('new-chat-cta-fullwidth')).toHaveCount(0, { timeout: 10000 });
		await expect(page.getByTestId('message-editor').locator('[contenteditable="true"]').first()).toBeVisible({
			timeout: 10000
		});

		await typeMessageText(page, 'Hello anonymous text');
		const termsReminder = page.getByTestId('anonymous-terms-reminder');
		await expect(termsReminder).toBeVisible({ timeout: 5000 });
		await expect(termsReminder).toContainText('By sending a message you accept the');
		await expect(termsReminder.getByRole('link', { name: 'Terms of service' })).toHaveAttribute(
			'target',
			'_blank'
		);
		await expect(termsReminder.getByRole('link', { name: 'Terms of service' })).toHaveAttribute(
			'href',
			/\/legal\/terms$/
		);
		await expect(termsReminder.getByRole('link', { name: 'Privacy policy' })).toHaveAttribute(
			'target',
			'_blank'
		);
		await expect(termsReminder.getByRole('link', { name: 'Privacy policy' })).toHaveAttribute(
			'href',
			/\/legal\/privacy$/
		);

		await page.getByTestId('input-dismiss-button').click();
		await expect(page.getByTestId('anonymous-terms-reminder')).toHaveCount(0);
		await expect(page.getByTestId('message-field')).toHaveClass(/draft-preview/);
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
		await page.getByTestId('message-field').click();
		await expect(page.getByTestId('anonymous-terms-reminder')).toBeVisible({ timeout: 5000 });
		await expect(page.locator('[data-action="send-message"]')).toBeVisible({ timeout: 5000 });
		await page.locator('[data-action="send-message"]').click();

		await expect(termsReminder).toHaveCount(0);
		await expect(
			page.getByTestId('message-system').filter({
				hasText: 'You are using free anonymous credits.'
			})
		).toBeVisible({ timeout: 10000 });
		await expect(
			page.getByTestId('message-system').filter({
				hasText: 'By sending a message you accept the terms'
			})
		).toHaveCount(0);
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 1' })).toBeVisible({
			timeout: 10000
		});

		expect(anonymousRequests).toHaveLength(1);
		expect(anonymousRequests[0].plaintext_message).toBe('Hello anonymous text');
		expect(anonymousRequests[0].message_history).toEqual([]);

		await typeMessageText(page, 'Second anonymous text');
		await page.locator('[data-action="send-message"]').click();
		await expect.poll(() => anonymousRequests.length, { timeout: 5000 }).toBe(2);
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 2' })).toBeVisible({
			timeout: 10000
		});

		expect(JSON.stringify(anonymousRequests[1].message_history)).not.toContain(
			'By sending a message you accept the terms'
		);
		expect(JSON.stringify(anonymousRequests[1].message_history)).not.toContain(
			'You are using free anonymous credits.'
		);
		expect(anonymousRequests[1].message_history).toEqual([
			expect.objectContaining({ role: 'user', content: 'Hello anonymous text' }),
			expect.objectContaining({ role: 'assistant', content: 'Anonymous answer 1' })
		]);
		expect(anonymousRequests[1].client_chat_id).toBe(anonymousRequests[0].client_chat_id);

		expect(await page.evaluate(() => localStorage.getItem('openmates_anonymous_chats_v1'))).toBeNull();
		const anonymousState = await getAnonymousIndexedDbState(page);
		expect(anonymousState.anonymousChats.length).toBeGreaterThanOrEqual(1);
		const activeAnonymousMessages = anonymousState.anonymousMessages.filter(
			(message) => message.chat_id === anonymousRequests[0].client_chat_id
		);
		expect(activeAnonymousMessages).toHaveLength(5);
		expect(anonymousState.anonymousChats[0].anonymous_encrypted_chat_key).toBeTruthy();
		expect(anonymousState.anonymousChats[0].encrypted_chat_key).toBeNull();
		expect(anonymousState.anonymousChats[0].title).toBeUndefined();
		const rawAnonymousJson = JSON.stringify(anonymousState);
		expect(rawAnonymousJson).not.toContain('Hello anonymous text');
		expect(rawAnonymousJson).not.toContain('Anonymous answer 1');
		expect(rawAnonymousJson).not.toContain('By sending a message you accept the terms');
		expect(rawAnonymousJson).not.toContain('You are using free anonymous credits.');

		await page.reload({ waitUntil: 'domcontentloaded' });
		const reloadedSecondAnswer = page.getByTestId('message-assistant').filter({ hasText: 'Anonymous answer 2' });
		await page.getByRole('button', { name: 'Scroll to bottom' }).click();
		await expect(reloadedSecondAnswer).toBeVisible({
			timeout: 10000
		});

		await page.evaluate(() => sessionStorage.removeItem('openmates_anonymous_chat_key'));
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect.poll(async () => (await getAnonymousIndexedDbState(page)).anonymousChats.length).toBe(0);
		expect(await page.evaluate(() => localStorage.getItem('openmates_anonymous_chats_v1'))).toBeNull();
		await assertNoMissingTranslations(page);
	});

	test('anonymous text send creates local chat UI before delayed response completes', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

		const anonymousRequests: Array<Record<string, unknown>> = [];
		await mockDelayedAnonymousChatStream(page, anonymousRequests);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();
		await expect(page.getByTestId('new-chat-cta-fullwidth')).toHaveCount(0, { timeout: 10000 });

		await typeMessageText(page, 'Slow anonymous stream should still show my message');
		await page.locator('[data-action="send-message"]').click();

		await expect.poll(() => anonymousRequests.length, { timeout: 5000 }).toBe(1);
		await expect(
			page.getByTestId('message-user').filter({ hasText: 'Slow anonymous stream should still show my message' })
		).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('typing-indicator')).toBeVisible({ timeout: 3000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Delayed anonymous answer 1' })).toHaveCount(0);

		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Delayed anonymous answer 1' })).toBeVisible({
			timeout: 10000
		});
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0, { timeout: 5000 });

		const anonymousState = await getAnonymousIndexedDbState(page);
		const activeAnonymousMessages = anonymousState.anonymousMessages.filter(
			(message) => message.chat_id === anonymousRequests[0].client_chat_id
		);
		expect(activeAnonymousMessages).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ role: 'user' }),
				expect.objectContaining({ role: 'assistant' })
			])
		);
		expect(new Set(activeAnonymousMessages.map((message) => message.message_id)).size).toBe(activeAnonymousMessages.length);
		await assertNoMissingTranslations(page);
	});

	test('anonymous text send streams chunks and updates chat header before completion', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

		const anonymousRequests: Array<Record<string, unknown>> = [];
		await mockProgressiveAnonymousChatStream(page, anonymousRequests);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();
		await expect(page.getByTestId('new-chat-cta-fullwidth')).toHaveCount(0, { timeout: 10000 });

		await typeMessageText(page, 'Stream anonymously like regular chat');
		await page.locator('[data-action="send-message"]').click();

		await expect.poll(() => anonymousRequests.length, { timeout: 5000 }).toBe(1);
		await expect(page.getByTestId('chat-header-banner')).toContainText('Creating new chat', { timeout: 2000 });
		await expect(page.getByTestId('chat-header-title')).toContainText('Anonymous stream title', { timeout: 5000 });
		await expect(page.getByTestId('typing-indicator')).toContainText('George is typing', { timeout: 5000 });
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Partial anonymous stream' })).toBeVisible({
			timeout: 5000
		});
		await expect(
			page.getByTestId('message-assistant').filter({ hasText: 'Partial anonymous stream complete' })
		).toHaveCount(0);

		await expect(
			page.getByTestId('message-assistant').filter({ hasText: 'Partial anonymous stream complete' })
		).toBeVisible({ timeout: 10000 });
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0, { timeout: 5000 });
		await expect(page.getByTestId('chat-header-summary')).toContainText('Anonymous streaming lifecycle completed', {
			timeout: 5000
		});
		await expect(page.getByTestId('follow-up-suggestion-item').first()).toContainText(
			'Explain anonymous streaming in simpler terms',
			{ timeout: 5000 }
		);
		const anonymousState = await getAnonymousIndexedDbState(page);
		const rawAnonymousJson = JSON.stringify(anonymousState);
		expect(rawAnonymousJson).not.toContain('Anonymous streaming lifecycle completed');
		expect(rawAnonymousJson).not.toContain('Explain anonymous streaming in simpler terms');
		expect(rawAnonymousJson).toContain('encrypted_chat_summary');
		expect(rawAnonymousJson).toContain('encrypted_follow_up_request_suggestions');
		await assertNoMissingTranslations(page);
	});

	test('live anonymous text stream updates header and typing before terminal response', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(120000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);
		const anonymousId = `e2e-live-anon-${Date.now()}-${Math.random().toString(16).slice(2)}`;
		await page.addInitScript((id: string) => {
			localStorage.removeItem('openmates:last-auth-method');
			localStorage.setItem('openmates_anonymous_id', id);
		}, anonymousId);

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();
		await expect(page.getByTestId('new-chat-cta-fullwidth')).toHaveCount(0, { timeout: 10000 });

		const prompt = `Capital of Spain? Anonymous lifecycle live check ${Date.now()}`;
		await typeMessageText(page, prompt);
		await page.locator('[data-action="send-message"]').click();

		await expect(page.getByTestId('chat-header-banner')).toContainText('Creating new chat', { timeout: 5000 });
		await expect(page.getByTestId('chat-header-title')).toContainText('Capital of Spain', { timeout: 12000 });
		const typingIndicator = page.getByTestId('typing-indicator');
		const typingSeen = typingIndicator
			.first()
			.waitFor({ state: 'visible', timeout: 12000 })
			.then(async () => {
				await expect(typingIndicator).toContainText('typing', { timeout: 1000 });
				return true;
			})
			.catch(() => false);
		const terminalAssistant = page
			.getByTestId('message-assistant')
			.filter({ hasText: /Madrid|Spain|Create an account to keep using OpenMates/i });
		await expect(terminalAssistant).toBeVisible({
			timeout: 90000
		});
		const terminalText = await terminalAssistant.first().innerText();
		if (!/Create an account to keep using OpenMates/i.test(terminalText)) {
			expect(await typingSeen).toBe(true);
			await expect(typingIndicator).toHaveCount(0, { timeout: 10000 });
			await expect(page.getByTestId('chat-header-summary')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('follow-up-suggestion-item').first()).toBeVisible({ timeout: 30000 });
		}
		await assertNoMissingTranslations(page);
	});

	test('anonymous text send becomes signup CTA when device budget is exhausted', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousExhaustedServerStatus(page);

		const streamRequests: string[] = [];
		page.on('request', (request: any) => {
			if (request.url().includes('/v1/anonymous/chat/stream')) {
				streamRequests.push(`${request.method()} ${request.url()}`);
			}
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();

		await typeMessageText(page, 'Budget should hide send');
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
		await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
		expect(streamRequests).toEqual([]);
		await assertNoMissingTranslations(page);
	});

	test('anonymous stream budget rejection keeps draft and does not create chat', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.route('**/v1/settings/server-status', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(anonymousActiveServerStatusBody())
			});
		});
		await page.route('**/v1/anonymous/free-usage/status**', async (route: any) => {
			await route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					active: true,
					can_send_text: true,
					reason: null,
					reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
					cta: 'Create an account to keep using OpenMates.'
				})
			});
		});

		const streamRequests: string[] = [];
		await page.route('**/v1/anonymous/chat/stream', async (route: any) => {
			const request = route.request();
			streamRequests.push(`${request.method()} ${request.url()}`);
			const body = request.postDataJSON();
			const taskId = 'anonymous-budget-rejected-task';
			const messageId = 'anonymous-budget-rejected-message';
			await route.fulfill({
				status: 200,
				contentType: 'text/event-stream',
				body: [
					{
						type: 'ai_task_initiated',
						chat_id: body.client_chat_id,
						user_message_id: body.client_message_id,
						ai_task_id: taskId,
						status: 'processing_started'
					},
					{
						type: 'ai_typing_started',
						chat_id: body.client_chat_id,
						message_id: messageId,
						user_message_id: body.client_message_id,
						category: 'general_knowledge',
						model_name: null,
						provider_name: null,
						server_region: null,
						title: 'Budget race should stay draft',
						icon_names: ['ai'],
						task_id: taskId
					},
					{
						type: 'ai_message_chunk',
						task_id: taskId,
						chat_id: body.client_chat_id,
						message_id: messageId,
						user_message_id: body.client_message_id,
						full_content_so_far: 'Create an account to keep using OpenMates.',
						sequence: 1,
						is_final_chunk: true,
						model_name: null,
						rejection_reason: 'budget_exhausted'
					},
					{
						type: 'ai_task_ended',
						chatId: body.client_chat_id,
						taskId: taskId,
						status: 'failed'
					}
				]
					.map((payload) => `data: ${JSON.stringify(payload)}\n\n`)
					.join('')
			});
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();

		const prompt = 'Budget race should stay draft';
		const editor = await typeMessageText(page, prompt);
		await expect(page.locator('[data-action="send-message"]')).toBeVisible({ timeout: 5000 });
		await page.locator('[data-action="send-message"]').click();

		await expect(page.getByTestId('notification').filter({
			hasText: 'You used up your free daily credits. Sign up & buy credits to make full use of OpenMates.'
		})).toBeVisible({ timeout: 5000 });
		const exhaustedNotification = page.getByTestId('notification').filter({
			hasText: 'You used up your free daily credits. Sign up & buy credits to make full use of OpenMates.'
		});
		await expect(exhaustedNotification.getByTestId('notification-action')).toContainText('Sign up');
		await exhaustedNotification.getByTestId('notification-action').click();
		await expect(page.getByTestId('login-tabs')).toBeVisible({ timeout: 10000 });
		await expect(editor).toContainText(prompt);
		await expect(page.getByTestId('message-user').filter({ hasText: prompt })).toHaveCount(0);
		await expect(page.getByTestId('message-assistant').filter({ hasText: 'Create an account to keep using OpenMates.' })).toHaveCount(0);
		await expect(page.getByText('Create an account to keep using OpenMates.')).toHaveCount(0);
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
		expect(streamRequests).toHaveLength(1);
		expect(await getAnonymousIndexedDbState(page)).toEqual({ anonymousChats: [], anonymousMessages: [] });
		await assertNoMissingTranslations(page);
	});

	test('previously authenticated devices are not eligible for anonymous text send', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await page.addInitScript(() => {
			localStorage.setItem('openmates:last-auth-method', 'email');
		});
		await mockAnonymousActiveServerStatus(page);

		const streamRequests: string[] = [];
		page.on('request', (request: any) => {
			if (request.url().includes('/v1/anonymous/chat/stream')) {
				streamRequests.push(`${request.method()} ${request.url()}`);
			}
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();

		await typeMessageText(page, 'Previously logged in device should not get free usage');
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
		await expect(page.getByTestId('anonymous-terms-reminder')).toHaveCount(0);
		await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
		await expect(page.locator('[data-action="sign-up-to-send"]')).toContainText('Login');
		expect(streamRequests).toEqual([]);
		await assertNoMissingTranslations(page);
	});

	test('anonymous file attachment is signup-gated without uploading file bytes', async ({
		page
	}: {
		page: any;
	}) => {
		test.setTimeout(60000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousActiveServerStatus(page);

		const uploadRequests: string[] = [];
		page.on('request', (request: any) => {
			const url = request.url();
			if (
				url.includes('/upload') ||
				url.includes('/uploads') ||
				url.includes('/embeds') ||
				url.includes('/anonymous/chat/stream')
			) {
				uploadRequests.push(`${request.method()} ${url}`);
			}
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');

		await page.waitForFunction(() => window.location.hash.includes('demo-for-everyone'), null, {
			timeout: 15000
		});
		await page.getByTestId('new-chat-cta-fullwidth').click();

		await page.getByTestId('message-file-input').setInputFiles({
			name: 'anonymous-empty-upload.png',
			mimeType: 'image/png',
			buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47])
		});
		await expect(page.getByTestId('anonymous-upload-signup-banner')).toBeVisible({ timeout: 5000 });
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
		await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible({ timeout: 5000 });
		await expect.poll(() => uploadRequests).toEqual([]);
		await page.getByTestId('anonymous-upload-signup-remove').click();
		await expect(page.getByTestId('anonymous-upload-signup-banner')).toHaveCount(0);
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);

		const editor = await typeMessageText(page, 'Please summarize this image after I sign up.');

		await page.getByTestId('message-file-input').setInputFiles({
			name: 'anonymous-upload.png',
			mimeType: 'image/png',
			buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47])
		});

		const banner = page.getByTestId('anonymous-upload-signup-banner');
		await expect(banner).toBeVisible({ timeout: 5000 });
		await expect(banner).toContainText('Create an account to upload files');
		await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible({ timeout: 5000 });
		await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
		await expect(editor).toContainText('Please summarize this image after I sign up.');

		await expect.poll(() => uploadRequests).toEqual([]);

		await page.getByTestId('anonymous-upload-signup-remove').click();
		await expect(banner).toHaveCount(0);
		await expect(page.locator('[data-action="send-message"]')).toBeVisible({ timeout: 5000 });
		await assertNoMissingTranslations(page);
	});
});
