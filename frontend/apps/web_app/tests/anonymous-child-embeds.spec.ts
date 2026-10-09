/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { openFullscreen, closeFullscreen } = require('./helpers/embed-test-helpers');

const PARENT_ID = 'anonymous-search-parent';
const CHILD_ID = 'anonymous-search-child';
const CODE_ID = '87993758-d1e7-4dc7-8f9b-30d53b3c38bd';
const GERMAN_TITLE = 'Proxmox-VM per Bash verwalten';
const GERMAN_SUMMARY = 'Bash-Skript zum sicheren Starten einer Proxmox-VM mit VM_NAME.';
const GERMAN_SUGGESTION = 'Wie prüfe ich den Status der Proxmox-VM?';

async function mockAnonymousAccess(page: any): Promise<void> {
	const availability = {
		active: true,
		can_send_text: true,
		reason: null,
		reset_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
		cta: 'Create an account to keep using OpenMates.'
	};
	await page.route('**/v1/settings/server-status', (route: any) => route.fulfill({
		status: 200,
		contentType: 'application/json',
		body: JSON.stringify({
			is_self_hosted: false,
			payment_enabled: true,
			server_edition: 'development',
			domain: 'app.dev.openmates.org',
			ai_models_configured: true,
			anonymous_free_usage: availability
		})
	}));
	await page.route('**/v1/anonymous/free-usage/status**', (route: any) => route.fulfill({
		status: 200,
		contentType: 'application/json',
		body: JSON.stringify(availability)
	}));
}

async function mockAnonymousEmbedStream(page: any, failAfterTool = false): Promise<void> {
	await page.addInitScript((limited: boolean) => {
		const originalFetch = window.fetch.bind(window);
		window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			if (!url.includes('/v1/anonymous/chat/stream')) return originalFetch(input, init);
			const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, string>;
			const encoder = new TextEncoder();
			const taskId = `anonymous-task-${body.client_message_id}`;
			const assistantId = 'anonymous-embed-assistant';
			const stream = new ReadableStream<Uint8Array>({
				start(controller) {
					const emit = (payload: Record<string, unknown>) => {
						controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
					};
					emit({ type: 'ai_task_initiated', chat_id: body.client_chat_id, user_message_id: body.client_message_id, ai_task_id: taskId, status: 'processing_started' });
					emit({
						type: 'ai_typing_started', chat_id: body.client_chat_id, message_id: assistantId,
						user_message_id: body.client_message_id, category: 'general_knowledge',
						model_name: 'test-model', provider_name: 'Test Provider', server_region: 'EU', task_id: taskId
					});
					emit({
						type: 'send_embed_data',
						payload: {
							embed_id: 'anonymous-search-parent', type: 'app_skill_use', app_id: 'web', skill_id: 'search',
							content: 'app_id: web\nskill_id: search\nquery: official OpenMates\nresult_count: 1\nembed_ref: anonymous-search\nstatus: finished',
							text_preview: 'Web search for official OpenMates', status: 'finished', embed_ids: ['anonymous-search-child']
						}
					});
					emit({
						type: 'send_embed_data',
						payload: {
							embed_id: 'anonymous-search-child', parent_embed_id: 'anonymous-search-parent',
							type: 'web-website', app_id: 'web', skill_id: 'search',
							content: 'app_id: web\nskill_id: search\ntitle: OpenMates\nurl: https://openmates.org\ndescription: OpenMates home page\nembed_ref: anonymous-source\nstatus: finished',
							text_preview: 'OpenMates home page', status: 'finished'
						}
					});
					if (limited) {
						emit({
							type: 'ai_message_chunk', chat_id: body.client_chat_id, message_id: assistantId,
							user_message_id: body.client_message_id, task_id: taskId, sequence: 1,
							is_final_chunk: false,
							full_content_so_far: 'I found the [OpenMates source](embed:anonymous-source).',
							model_name: 'test-model'
						});
					}
					emit({
						type: 'ai_message_chunk', chat_id: body.client_chat_id, message_id: assistantId,
						user_message_id: body.client_message_id, task_id: taskId, sequence: limited ? 2 : 1, is_final_chunk: true,
						full_content_so_far: limited
							? 'I found the [OpenMates source](embed:anonymous-source).\n\nCreate an account to keep using OpenMates.'
							: 'I found the [OpenMates source](embed:anonymous-source).',
						model_name: 'test-model',
						...(limited ? { rejection_reason: 'anonymous_usage_limit' } : {})
					});
					emit({ type: 'ai_task_ended', chatId: body.client_chat_id, taskId, status: limited ? 'failed' : 'completed' });
					controller.close();
				}
			});
			return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } });
		};
	}, failAfterTool);
}

async function mockGermanCodeStream(page: any, requests: Array<Record<string, unknown>>): Promise<void> {
	await page.exposeFunction('recordGermanAnonymousRequest', (body: Record<string, unknown>) => {
		requests.push(body);
		return requests.length;
	});
	await page.addInitScript((fixture: { codeId: string; title: string; summary: string; suggestion: string }) => {
		const originalFetch = window.fetch.bind(window);
		window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			if (!url.includes('/v1/anonymous/chat/stream')) return originalFetch(input, init);
			const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, string>;
			const responseNumber = await (window as typeof window & {
				recordGermanAnonymousRequest: (body: Record<string, unknown>) => Promise<number>;
			}).recordGermanAnonymousRequest(body);
			const encoder = new TextEncoder();
			const taskId = `anonymous-task-${body.client_message_id}`;
			const assistantId = `anonymous-german-assistant-${responseNumber}`;
			const stream = new ReadableStream<Uint8Array>({
				start(controller) {
					const emit = (payload: Record<string, unknown>) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
					emit({ type: 'ai_task_initiated', chat_id: body.client_chat_id, user_message_id: body.client_message_id, ai_task_id: taskId, status: 'processing_started' });
					emit({ type: 'ai_typing_started', chat_id: body.client_chat_id, message_id: assistantId,
						user_message_id: body.client_message_id, task_id: taskId, category: 'software_development',
						model_name: 'test-model', provider_name: 'Test Provider', server_region: 'EU',
						title: fixture.title, icon_names: ['code'] });
					if (responseNumber === 1) emit({ type: 'send_embed_data', payload: {
						embed_id: fixture.codeId, type: 'code', app_id: 'code', skill_id: 'code',
						content: 'type: code\napp_id: code\nskill_id: code\nlanguage: bash\ncode: "echo ${VM_NAME}"\nfilename: vm-start.sh\nembed_ref: anonymous-vm-code\nstatus: finished\nline_count: 1',
						text_preview: 'vm-start.sh', status: 'finished'
					} });
					emit({ type: 'ai_message_chunk', chat_id: body.client_chat_id, message_id: assistantId,
						user_message_id: body.client_message_id, task_id: taskId, sequence: 1, is_final_chunk: true,
						full_content_so_far: responseNumber === 1
							? `Hier ist das Bash-Skript für deine Proxmox-VM:\n\n\`\`\`json\n${JSON.stringify({ type: 'code', embed_id: fixture.codeId })}\n\`\`\``
							: 'Das Skript verwendet VM_NAME als Namen der Proxmox-VM.', model_name: 'test-model' });
					emit({ type: 'ai_task_ended', chatId: body.client_chat_id, taskId, status: 'completed' });
					emit({ type: 'post_processing_completed', chat_id: body.client_chat_id, task_id: taskId,
						follow_up_request_suggestions: [fixture.suggestion], new_chat_request_suggestions: [],
						chat_summary: fixture.summary, chat_tags: [], harmful_response: 0, quick_tip_slugs: [] });
					controller.close();
				}
			});
			return new Response(stream, { status: 200, headers: { 'content-type': 'text/event-stream' } });
		};
	}, { codeId: CODE_ID, title: GERMAN_TITLE, summary: GERMAN_SUMMARY, suggestion: GERMAN_SUGGESTION });
}

async function storedEmbedIds(page: any): Promise<string[]> {
	return page.evaluate((ids: string[]) => new Promise<string[]>((resolve, reject) => {
		const request = indexedDB.open('chats_db');
		request.onerror = () => reject(request.error);
		request.onsuccess = () => {
			const db = request.result;
			const transaction = db.transaction('embeds', 'readonly');
			const requests = ids.map((id) => transaction.objectStore('embeds').get(`embed:${id}`));
			transaction.onerror = () => { db.close(); reject(transaction.error); };
			transaction.oncomplete = () => {
				const stored = requests.filter((entry) => !!entry.result?.encrypted_content)
					.map((entry) => entry.result.embed_id as string);
				db.close();
				resolve(stored);
			};
		};
	}), [PARENT_ID, CHILD_ID]);
}

async function storedAnonymousChat(page: any): Promise<Record<string, unknown> | null> {
	return page.evaluate(() => new Promise<Record<string, unknown> | null>((resolve, reject) => {
		const request = indexedDB.open('chats_db');
		request.onerror = () => reject(request.error);
		request.onsuccess = () => {
			const db = request.result;
			const transaction = db.transaction('chats', 'readonly');
			const chatsRequest = transaction.objectStore('chats').getAll();
			transaction.onerror = () => { db.close(); reject(transaction.error); };
			transaction.oncomplete = () => {
				const chat = (chatsRequest.result as Array<Record<string, unknown>>).find((item) => item.is_anonymous === true) ?? null;
				db.close();
				resolve(chat);
			};
		};
	}));
}

async function assertGuestTabCannotOpenChat(page: any, chatId: string): Promise<void> {
	await mockAnonymousAccess(page);
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await expect.poll(() => page.evaluate(() => sessionStorage.getItem('openmates_anonymous_chat_key'))).toBeNull();
	// IndexedDB belongs to the origin; the encrypted row must survive another tab's visit.
	await expect.poll(async () => (await storedAnonymousChat(page))?.chat_id).toBe(chatId);
	await expect(page.locator(`[data-testid="resume-chat-large-card"][data-chat-id="${chatId}"], [data-testid="resume-chat-card"][data-chat-id="${chatId}"]`)).toHaveCount(0);
	if (!(await page.getByTestId('activity-history-wrapper').isVisible().catch(() => false))) {
		await page.getByTestId('sidebar-toggle').click();
	}
	await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`)).toHaveCount(0);
	await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');
	await expect(page.getByTestId('message-user').filter({ hasText: 'Schreibe ein Bash-Skript' })).toHaveCount(0);
	await expect(page.getByTestId('message-assistant').filter({ hasText: 'Bash-Skript für deine Proxmox-VM' })).toHaveCount(0);
	await expect.poll(() => page.evaluate(() => sessionStorage.getItem('openmates_anonymous_chat_key'))).toBeNull();
	await expect.poll(async () => (await storedAnonymousChat(page))?.chat_id).toBe(chatId);
}

test.describe('Anonymous child embeds', () => {
	// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity,billing.anonymous.local-only-content
	test('keeps German code in its tab while other tabs cannot open the encrypted chat', async ({ page }: { page: any }) => {
		test.setTimeout(120_000);
		await page.setViewportSize({ width: 1440, height: 900 });
		await mockAnonymousAccess(page);
		const anonymousRequests: Array<Record<string, unknown>> = [];
		await mockGermanCodeStream(page, anonymousRequests);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await expect(editor).toBeVisible({ timeout: 10_000 });
		await editor.click();
		await editor.pressSequentially('Schreibe ein Bash-Skript zum Starten einer Proxmox-VM mit VM_NAME.');
		await page.locator('[data-action="send-message"]').click();

		const answer = page.getByTestId('message-assistant').last();
		await expect(answer).toHaveAttribute('data-streaming', 'false', { timeout: 30_000 });
		await expect(answer).toHaveAttribute('data-message-id', 'anonymous-german-assistant-1');
		const code = answer.locator(`[data-testid="embed-preview"][data-app-id="code"][data-status="finished"][data-embed-id="${CODE_ID}"]`);
		await expect(code).toBeVisible({ timeout: 15_000 });
		const fullscreen = await openFullscreen(page, code);
		await expect(fullscreen).toContainText('VM_NAME', { timeout: 10_000 });
		await closeFullscreen(page, fullscreen);
		await expect(page.getByTestId('chat-header-title')).toContainText(GERMAN_TITLE);
		await expect(page.getByTestId('chat-header-summary')).toContainText(GERMAN_SUMMARY);
		await expect(page.getByTestId('follow-up-suggestion-item').first()).toContainText(GERMAN_SUGGESTION);
		await expect(page.getByTestId('anonymous-feature-notice')).toHaveText(
			'Signup now to unlock all features and to keep your chats and access them across your devices.'
		);
		await expect(page.getByTestId('anonymous-signup-link')).toHaveAttribute('href', '/#signup/basics');
		const saved = await storedAnonymousChat(page);
		expect(saved?.chat_id).toBeTruthy();
		expect(saved?.encrypted_title).toBeTruthy();
		expect(saved?.encrypted_chat_summary).toBeTruthy();
		expect(saved?.encrypted_follow_up_request_suggestions).toBeTruthy();
		expect(JSON.stringify(saved)).not.toContain(GERMAN_SUMMARY);
		expect(JSON.stringify(saved)).not.toContain(GERMAN_SUGGESTION);
		const chatId = String(saved?.chat_id);
		await expect.poll(() => page.evaluate(() => !!sessionStorage.getItem('openmates_anonymous_chat_key'))).toBe(true);

		// Exercise generic IndexedDB startup without the session-only orphan-detection bypass.
		await page.evaluate(() => sessionStorage.removeItem('openmates_skip_orphan_detection'));
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 15_000 });
		await expect(page.getByTestId('chat-header-title')).toContainText(GERMAN_TITLE);
		await expect(page.getByTestId('chat-header-summary')).toContainText(GERMAN_SUMMARY);
		await expect(page.getByTestId('follow-up-suggestion-item').first()).toContainText(GERMAN_SUGGESTION);
		await expect(page.getByTestId('message-assistant').last().locator(`[data-testid="embed-preview"][data-embed-id="${CODE_ID}"]`)).toBeVisible();
		const followUpEditor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await followUpEditor.click();
		await followUpEditor.pressSequentially('Was macht die Variable VM_NAME in diesem Skript?');
		await page.locator('[data-action="send-message"]').click();
		await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 30_000 });
		await expect(page.getByTestId('message-assistant').last()).toContainText('VM_NAME');
		await expect(page.getByTestId('message-assistant').last()).toHaveAttribute('data-message-id', 'anonymous-german-assistant-2');
		expect(anonymousRequests).toHaveLength(2);
		expect(anonymousRequests[1].current_chat_title).toBe(GERMAN_TITLE);
		expect(anonymousRequests[1].current_chat_summary).toBe(GERMAN_SUMMARY);
		const history = anonymousRequests[1].message_history as Array<{ role: string; content: string }>;
		const priorAssistant = history.find((message) => message.role === 'assistant');
		expect(priorAssistant?.content, 'The next turn needs the actual saved script, not only its JSON embed placeholder')
			.toContain('echo ${VM_NAME}');
		await expect(page.getByTestId('chat-header-title')).toContainText(GERMAN_TITLE);
		await page.getByTestId('new-chat-button').first().click();
		const resumeCard = page.locator(`[data-testid="resume-chat-large-card"][data-chat-id="${chatId}"], [data-testid="resume-chat-card"][data-chat-id="${chatId}"]`).first();
		await expect(resumeCard).toBeVisible({ timeout: 15_000 });
		await expect(resumeCard).toContainText(GERMAN_TITLE);
		if (!(await page.getByTestId('activity-history-wrapper').isVisible().catch(() => false))) {
			await page.getByTestId('sidebar-toggle').click();
		}
		const sidebarChat = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${chatId}"]`);
		await expect(sidebarChat).toBeVisible({ timeout: 15_000 });
		await expect(sidebarChat).toContainText(GERMAN_TITLE);

		const secondTab = await page.context().newPage();
		await assertGuestTabCannotOpenChat(secondTab, chatId);
		await page.goto(getE2EDebugUrl(`/#chat-id=${encodeURIComponent(chatId)}`), { waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 15_000 });
		await expect(page.getByTestId('chat-header-title')).toContainText(GERMAN_TITLE);
		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant')).toHaveCount(2, { timeout: 15_000 });
		await expect(page.getByTestId('message-assistant').first().locator(`[data-testid="embed-preview"][data-embed-id="${CODE_ID}"]`)).toBeVisible();
		await expect(page.getByTestId('chat-header-summary')).toContainText(GERMAN_SUMMARY);
		await page.close();

		const freshTab = await page.context().newPage();
		await assertGuestTabCannotOpenChat(freshTab, chatId);
	});

	// contract-test: direct surface=gui.web assertions=chats.streaming.ordered-final,chats.persistence.client-encrypted,billing.anonymous.local-only-content
	test('keeps completed search results when the final anonymous answer reaches its usage limit', async ({ page }: { page: any }) => {
		test.setTimeout(90_000);
		await mockAnonymousAccess(page);
		await mockAnonymousEmbedStream(page, true);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await expect(editor).toBeVisible({ timeout: 10_000 });
		await editor.click();
		await editor.pressSequentially('Search official docs');
		await page.locator('[data-action="send-message"]').click();

		const answer = page.getByTestId('message-assistant').last();
		await expect(answer).toContainText('Create an account to keep using OpenMates.', { timeout: 30_000 });
		await expect(answer).not.toContainText('The AI service encountered an error');
		await expect(answer.getByRole('link', { name: 'OpenMates source' })).toBeVisible();
		await expect(page.getByTestId('typing-indicator')).toHaveCount(0);
		await expect.poll(() => storedEmbedIds(page), { timeout: 15_000 }).toEqual([PARENT_ID, CHILD_ID]);
		await page.reload({ waitUntil: 'domcontentloaded' });
		const reloadedAnswer = page.getByTestId('message-assistant').last();
		await expect(reloadedAnswer).toContainText('Create an account to keep using OpenMates.', { timeout: 15_000 });
		await expect(reloadedAnswer.getByRole('link', { name: 'OpenMates source' })).toBeVisible();
		await expect.poll(() => storedEmbedIds(page), { timeout: 15_000 }).toEqual([PARENT_ID, CHILD_ID]);
	});

	// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
	test('offers a refresh when an older tab cannot load an embed fullscreen chunk', async ({ page }: { page: any }) => {
		test.setTimeout(90_000);
		await mockAnonymousAccess(page);
		await mockAnonymousEmbedStream(page);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await expect(editor).toBeVisible({ timeout: 10_000 });
		await editor.click();
		await editor.pressSequentially('Search for OpenMates');
		await page.locator('[data-action="send-message"]').click();
		const answer = page.getByTestId('message-assistant').last();
		await expect(answer).toHaveAttribute('data-streaming', 'false', { timeout: 30_000 });
		let chunkFailures = 0;
		let blockedUrl = '';
		await page.route('**/*.js*', (route: any) => {
			if (chunkFailures > 0 || route.request().resourceType() !== 'script') return route.continue();
			chunkFailures += 1;
			blockedUrl = route.request().url();
			return route.abort();
		});
		await answer.getByRole('link', { name: 'OpenMates source' }).click();
		await expect(page.getByTestId('embed-fullscreen-chunk-error'), `Blocked script: ${blockedUrl}`).toBeVisible({ timeout: 10_000 });
		await expect(page.getByTestId('embed-fullscreen-refresh')).toBeVisible();
		expect(chunkFailures).toBeGreaterThan(0);
	});

	// contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
	test('stores parent and child, resolves the child ref, and reloads without an account', async ({ page }: { page: any }) => {
		test.setTimeout(90_000);
		await page.setViewportSize({ width: 390, height: 844 });
		await mockAnonymousAccess(page);
		await mockAnonymousEmbedStream(page);
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.waitForLoadState('networkidle');
		const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
		await expect(editor).toBeVisible({ timeout: 10_000 });
		await editor.click();
		await editor.pressSequentially('Search for OpenMates');
		await page.locator('[data-action="send-message"]').click();

		const answer = page.getByTestId('message-assistant').last();
		await expect(answer).toHaveAttribute('data-streaming', 'false', { timeout: 30_000 });
		await expect(page.getByTestId('message-assistant')).toHaveCount(1);
		await expect(answer).toHaveAttribute('data-message-id', 'anonymous-embed-assistant');
		await expect.poll(() => storedEmbedIds(page), { timeout: 15_000 }).toEqual([PARENT_ID, CHILD_ID]);
		const source = answer.getByRole('link', { name: 'OpenMates source' });
		await expect(source).toBeVisible();
		await source.click();
		const fullscreen = page.getByTestId('embed-fullscreen-overlay');
		await expect(fullscreen).toContainText('OpenMates', { timeout: 10_000 });
		await closeFullscreen(page, fullscreen);

		await page.reload({ waitUntil: 'domcontentloaded' });
		await expect(page.getByTestId('message-assistant')).toHaveCount(1, { timeout: 15_000 });
		await expect.poll(() => storedEmbedIds(page), { timeout: 15_000 }).toEqual([PARENT_ID, CHILD_ID]);
		const reloadedAnswer = page.getByTestId('message-assistant').last();
		await expect(reloadedAnswer).toHaveAttribute('data-message-id', 'anonymous-embed-assistant');
		const reloadedSource = reloadedAnswer.getByRole('link', { name: 'OpenMates source' });
		await expect(reloadedSource).toBeVisible({ timeout: 15_000 });
		await reloadedSource.click();
		await expect(page.getByTestId('embed-fullscreen-overlay')).toContainText('OpenMates', { timeout: 10_000 });
	});
});
