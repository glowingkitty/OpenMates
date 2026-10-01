/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { closeFullscreen } = require('./helpers/embed-test-helpers');

const PARENT_ID = 'anonymous-search-parent';
const CHILD_ID = 'anonymous-search-child';

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

test.describe('Anonymous child embeds', () => {
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
