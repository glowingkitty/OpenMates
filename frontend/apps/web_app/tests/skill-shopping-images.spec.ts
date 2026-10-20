/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free gallery serialization and reference validation. */
export {};

const { test, expect } = require('./console-monitor');
const {
	CLI_DIST,
	deriveApiUrl,
	runCli,
	parseCliJson,
	expectCliSuccess
} = require('./helpers/cli-test-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { pairDirectChatCli } = require('./helpers/direct-chat-cli');
const {
	createWorkflowCliHome,
	removeWorkflowCliHome,
	workflowCliEnv
} = require('./helpers/workflow-cli-e2e-helpers');
const { getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const fs = require('node:fs');

const PROMPT =
	'@ai-model:gemini-3.8-flash:google Find bio joghurt on REWE. SHOPPING_IMAGES_E2E:gallery <<<TEST_LIVE_MOCK:shopping_images_web>>>';
const REFERENCE_ERROR_PROMPT =
	'@ai-model:gemini-3.8-flash:google Find bio joghurt on REWE using my reference image. SHOPPING_IMAGES_E2E:reference-error <<<TEST_LIVE_MOCK:shopping_images_web>>>';
const REFERENCE_ERROR_MESSAGE =
	'A reference image could not be accessed. Use its exact reference from this chat or upload it again.';
const REFERENCE_ERROR_RESPONSE =
	'The reference image could not be accessed. Please upload it again or use its exact reference from this chat. The shopping search did not run.';
const GALLERY = [
	'https://img.rewe-static.de/8304439/31937745_digital-image.png',
	'https://img.rewe-static.de/synthetic-gallery/reverse.png',
	'https://img.rewe-static.de/synthetic-gallery/ingredients.png'
];

function resolveSchema(openapi: any, schema: any): any {
	return schema?.$ref ? openapi.components.schemas[schema.$ref.split('/').pop()] : schema;
}

test.describe('Shopping product galleries and reference images', () => {
	test.setTimeout(300_000);
	const apiUrl =
		process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	test.beforeAll(() => {
		installRecorderDeps();
	});

	// contract-test: direct surface=rest_api assertions=app-skills.surface.semantic-parity,shopping-search.relevance.bounded
	test('OpenAPI exposes optional reference images with a maximum of three', async ({
		request
	}: {
		request: any;
	}) => {
		const response = await request.get(`${apiUrl}/openapi.json`);
		expect(response.ok()).toBe(true);
		const openapi = await response.json();
		const operation = openapi.paths['/v1/apps/shopping/skills/search_products'].post;
		const body = resolveSchema(openapi, operation.requestBody.content['application/json'].schema);
		const item = resolveSchema(openapi, resolveSchema(openapi, body.properties.requests).items);
		const field = item.properties.reference_images;
		const array = field.anyOf?.find((option: any) => option.type === 'array') || field;
		expect(array.type).toBe('array');
		expect(array.items.type).toBe('string');
		expect(array.maxItems).toBe(3);
		expect(item.required || []).not.toContain('reference_images');
		expect(
			item.properties.max_results.maximum,
			'Forty discovery candidates preserve the public final cap'
		).toBe(20);
	});

	// contract-test: direct surface=gui.web assertions=shopping-search.relevance.bounded,app-skills.search-relevance.safe-finalization
	test('forty relevance candidates preserve a late match and the requested final limit', async ({
		page
	}: {
		page: any;
	}) => {
		test.skip(!getTestAccount().email, 'Disposable CI account required.');
		await installE2EServerContentOverrideGate(page, 'shopping-forty-replay');
		await loginToTestAccount(page);
		await startNewChat(page);
		try {
			await sendMessage(
				page,
				'Find the late matching grocery product on REWE; return at most five products. SHOPPING_IMAGES_E2E:forty <<<TEST_LIVE_MOCK:shopping_images_web>>>'
			);
			await expect(page.getByTestId('message-assistant').last()).toContainText(
				'The late matching product from forty candidates is first; the shopping card contains five products.',
				{ timeout: 60_000 }
			);
			await expect(page.getByTestId('message-assistant').last()).not.toContainText('REGRESSION:');
		} finally {
			await deleteActiveChat(page);
		}
	});

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity,shopping-search.products.supplied-gallery
	test('CLI preserves every provider photo through encrypted parent and child embeds', async ({
		page
	}: { page: any }, testInfo: any) => {
		test.skip(!getTestAccount().email, 'Disposable CI account required.');
		const home = createWorkflowCliHome('shopping-images');
		const env = {
			...workflowCliEnv(apiUrl, home),
			LIBGL_ALWAYS_SOFTWARE: 'true',
			GALLIUM_DRIVER: 'llvmpipe'
		};
		const options = { useApiKey: false, record: false, env };
		let chatId: string | undefined;
		let replayMarkerSubmitted = false;
		page.on('websocket', (socket: any) =>
			socket.on('framesent', (frame: { payload: string | Buffer }) => {
				try {
					const packet = JSON.parse(frame.payload.toString());
					const payload = packet.payload;
					const marker = payload?.inference_request?.test_mock_marker || payload?.test_mock_marker;
					if (marker === '<<<TEST_LIVE_MOCK:shopping_images_web>>>') replayMarkerSubmitted = true;
				} catch {
					// Ignore transport frames that are not application JSON.
				}
			})
		);
		try {
			await installE2EServerContentOverrideGate(page, 'shopping-images-replay');
			await loginToTestAccount(page, (message: string) => console.log(message));
			expect(
				await page.evaluate(() => {
					const raw = sessionStorage.getItem('openmates_e2e_log_forwarding');
					if (!raw) return false;
					const gate = JSON.parse(raw);
					return typeof gate.runId === 'string' && typeof gate.token === 'string';
				}),
				'Isolated replay override gate is installed before starting the shopping chat'
			).toBe(true);
			await startNewChat(page);
			// The browser helper submits the marker through the existing account-bound
			// signing field. A marker in CLI message text is deliberately unauthorized.
			await sendMessage(page, PROMPT);
			await expect
				.poll(() => replayMarkerSubmitted, {
					message: 'Shopping replay marker crossed the browser signing field',
					timeout: 5000
				})
				.toBe(true);
			// This fixture's answer has no inline embed reference. Verify the saved
			// parent/child graph through the owner's CLI independently of rendering.
			await expect(page.getByTestId('message-assistant').last()).toContainText(
				'The REWE search result is available in the shopping card. Exact composition was not supplied.',
				{ timeout: 60_000 }
			);
			await expect(page.getByTestId('message-assistant').last()).not.toContainText(
				/REGRESSION:|100%|missing (?:product )?images|could not (?:access|load) (?:the )?product images/i
			);
			chatId =
				page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ||
				(await page
					.locator('[data-action="message-input"]')
					.last()
					.getAttribute('data-current-chat-id'));
			expect(chatId, 'Signed shopping web chat has a persisted identity').toBeTruthy();
			await pairDirectChatCli(page, apiUrl, home, CLI_DIST);
			await page.close();
			const shown = await runCli(apiUrl, ['chats', 'show', chatId!, '--json'], 45_000, options);
			expectCliSuccess(shown, 'Read persisted shopping chat');
			const messages = parseCliJson(shown).messages;
			const assistants = messages.filter((message: any) => message.role === 'assistant');
			expect(assistants.length).toBeGreaterThan(0);
			for (const assistant of assistants) expect(assistant.modelName).toBe('Gemini 3.8 Flash');
			const pending: string[] = [
				...new Set<string>(
					messages.flatMap((message: any) => message.embedIds || message.embed_ids || [])
				)
			];
			expect(pending.length, 'Saved assistant message references its skill embed').toBeGreaterThan(
				0
			);
			const visited = new Set<string>();
			let productId: string | undefined;
			let parentSeen = false;
			while (pending.length) {
				const id = pending.shift()!;
				if (visited.has(id)) continue;
				visited.add(id);
				expect(visited.size, 'The result embed graph stays bounded').toBeLessThanOrEqual(10);
				const read = await runCli(
					apiUrl,
					['embeds', 'show', id, '--chat', chatId!, '--json'],
					45_000,
					options
				);
				expectCliSuccess(read, 'Decrypt shopping parent/child');
				const embed = parseCliJson(read);
				const content =
					typeof embed.content === 'string' ? JSON.parse(embed.content) : embed.content;
				expect(content).toBeTruthy();
				const childIds = content.embed_ids || [];
				pending.push(
					...(Array.isArray(childIds) ? childIds : String(childIds).split('|')).filter(Boolean)
				);
				if (childIds.length) {
					parentSeen = true;
					expect(content.grounding_notice).toContain('only when explicitly supplied');
					expect(content.grounding_notice).toContain('0–4');
				}
				if (content.product_id === '8304439') productId = id;
			}
			expect(parentSeen, 'The persisted search parent references its product child').toBe(true);
			expect(productId, 'The real provider parser product survives client decryption').toBeTruthy();
			// Record the actual decrypted product read, so terminal proof includes
			// every gallery URL rather than just the chat's embed identifiers.
			const recorded = await runCli(
				apiUrl,
				['embeds', 'show', productId!, '--chat', chatId!, '--json'],
				45_000,
				{
					...options,
					record: true,
					env: {
						...env,
						OPENMATES_CLI_RECORD_E2E: '1',
						OPENMATES_E2E_SPEC: 'skill-shopping-images-gallery'
					}
				}
			);
			if (recorded.recording && fs.existsSync(recorded.recording.videoPath)) {
				await testInfo.attach('shopping-gallery-cli-terminal', {
					path: recorded.recording.videoPath,
					contentType: 'video/mp4'
				});
				await testInfo.attach('shopping-gallery-cli-transcript', {
					path: recorded.recording.transcriptPath,
					contentType: 'text/plain'
				});
			}
			expectCliSuccess(recorded, 'Read the persisted shopping product gallery');
			expect(
				recorded.recording && fs.existsSync(recorded.recording.videoPath),
				'Shopping gallery CLI terminal capture exists'
			).toBe(true);
			const savedProduct = parseCliJson(recorded);
			const product =
				typeof savedProduct.content === 'string'
					? JSON.parse(savedProduct.content)
					: savedProduct.content;
			expect(product.image_url).toBe(GALLERY[0]);
			// Embed TOON stores scalar lists with the shared pipe encoding.
			const photos = Array.isArray(product.image_urls)
				? product.image_urls
				: String(product.image_urls || '').split('|');
			expect(photos).toEqual(GALLERY);
			expect(
				product.visual_match,
				'No reference supplied: do not claim visual verification'
			).toBeUndefined();
		} finally {
			if (chatId) await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 20_000, options);
			removeWorkflowCliHome(home);
		}
	});

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity,shopping-search.references.authorized,shopping-search.relevance.bounded
	test('CLI rejects four references and an unowned reference before provider search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'Disposable CI API key required.');
		for (const count of [4, 1]) {
			const referenceImages = Array.from(
				{ length: count },
				(_, index) => `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`
			);
			const result = await runCli(
				apiUrl,
				[
					'apps',
					'shopping',
					'search_products',
					'--input',
					JSON.stringify({
						requests: [
							{ query: 'bio joghurt', provider: 'REWE', reference_images: referenceImages }
						]
					}),
					'--json'
				],
				45_000,
				{
					env: {
						OPENMATES_CLI_RECORD_E2E: '1',
						OPENMATES_E2E_SPEC: `skill-shopping-images-invalid-${count}`,
						LIBGL_ALWAYS_SOFTWARE: 'true',
						GALLIUM_DRIVER: 'llvmpipe'
					}
				}
			);
			const output = `${result.stdout}\n${result.stderr}`;
			expect(
				result.recording && fs.existsSync(result.recording.videoPath),
				`Reference validation CLI terminal capture: ${output}`
			).toBe(true);
			expect(output).toMatch(
				count === 4
					? /List should have at most 3 items after validation, not 4/i
					: /Reference image is unavailable to this caller/i
			);
			expect(output).not.toContain('img.rewe-static.de');
		}
	});

	// contract-test: direct surface=gui.web assertions=app-skills.surface.semantic-parity,shopping-search.references.authorized,shopping-search.relevance.truthful-fallback
	test('an inaccessible reference stays a failed search and reaches the assistant truthfully', async ({
		page
	}: { page: any }, testInfo: any) => {
		test.skip(!getTestAccount().email, 'Disposable CI account required.');
		const { createRequire } = require('node:module');
		const { pathToFileURL } = require('node:url');
		const { decode } = await import(
			pathToFileURL(createRequire(CLI_DIST).resolve('@toon-format/toon')).href
		);
		const home = createWorkflowCliHome('shopping-reference-error');
		const env = {
			...workflowCliEnv(apiUrl, home),
			LIBGL_ALWAYS_SOFTWARE: 'true',
			GALLIUM_DRIVER: 'llvmpipe'
		};
		const options = { useApiKey: false, record: false, env };
		let chatId: string | undefined;
		let markerSubmitted = false;
		let failedReferenceDelivered = false;
		let finishedShoppingDelivered = false;
		page.on('websocket', (socket: any) => {
			socket.on('framesent', (frame: { payload: string | Buffer }) => {
				try {
					const packet = JSON.parse(frame.payload.toString());
					const marker =
						packet.payload?.inference_request?.test_mock_marker || packet.payload?.test_mock_marker;
					if (marker === '<<<TEST_LIVE_MOCK:shopping_images_web>>>') markerSubmitted = true;
				} catch {
					/* Ignore transport frames that are not application JSON. */
				}
			});
			socket.on('framereceived', (frame: { payload: string | Buffer }) => {
				try {
					const packet = JSON.parse(frame.payload.toString());
					if (packet.type !== 'send_embed_data') return;
					const payload = packet.payload?.payload || packet.payload;
					if (typeof payload?.content !== 'string') return;
					let content;
					try {
						content = JSON.parse(payload.content);
					} catch {
						content = decode(payload.content);
					}
					if (content.app_id !== 'shopping' || content.skill_id !== 'search_products') return;
					if (payload.status === 'finished') finishedShoppingDelivered = true;
					if (
						payload.status === 'error' &&
						content.status === 'error' &&
						content.error === REFERENCE_ERROR_MESSAGE
					) {
						failedReferenceDelivered = true;
					}
				} catch {
					/* Other app/socket traffic is outside this scenario. */
				}
			});
		});
		try {
			await installE2EServerContentOverrideGate(page, 'shopping-reference-error');
			await loginToTestAccount(page);
			await startNewChat(page);
			await sendMessage(page, REFERENCE_ERROR_PROMPT);
			await expect.poll(() => markerSubmitted, { timeout: 5000 }).toBe(true);
			const assistant = page.getByTestId('message-assistant').last();
			// The upstream fixture emits this only after reading the real tool's
			// request_errors and inaccessible-reference explanation, never from the prompt.
			await expect(assistant).toContainText(REFERENCE_ERROR_RESPONSE, { timeout: 60_000 });
			await expect
				.poll(() => failedReferenceDelivered, {
					message: 'The failed reference updates the real shopping placeholder to error',
					timeout: 10_000
				})
				.toBe(true);
			expect(
				finishedShoppingDelivered,
				'A reference failure must not become a finished zero-product result'
			).toBe(false);
			await expect(
				page.locator(
					'[data-testid="embed-preview"][data-app-id="shopping"][data-status="finished"]'
				)
			).toHaveCount(0);
			await expect(assistant.getByTestId('embed-error-banner')).toBeVisible();
			await expect(assistant).not.toContainText(
				/no matching products|no products found|REGRESSION:/i
			);
			chatId =
				page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1] ||
				(await page
					.locator('[data-action="message-input"]')
					.last()
					.getAttribute('data-current-chat-id'));
			expect(chatId).toBeTruthy();
			await pairDirectChatCli(page, apiUrl, home, CLI_DIST);
			await page.close();
			const saved = await runCli(apiUrl, ['chats', 'show', chatId!, '--json'], 45_000, {
				...options,
				record: true,
				env: {
					...env,
					OPENMATES_CLI_RECORD_E2E: '1',
					OPENMATES_E2E_SPEC: 'skill-shopping-images-reference-error'
				}
			});
			if (saved.recording && fs.existsSync(saved.recording.videoPath)) {
				await testInfo.attach('shopping-reference-error-cli-terminal', {
					path: saved.recording.videoPath,
					contentType: 'video/mp4'
				});
			}
			expectCliSuccess(saved, 'Read the persisted truthful reference failure');
			expect(saved.recording && fs.existsSync(saved.recording.videoPath)).toBe(true);
			const messages = parseCliJson(saved).messages;
			const assistants = messages.filter((message: any) => message.role === 'assistant');
			expect(assistants.length).toBeGreaterThan(0);
			for (const assistant of assistants) expect(assistant.modelName).toBe('Gemini 3.8 Flash');
			const answers = assistants.map((message: any) => message.content).join('\n');
			expect(answers).toContain(REFERENCE_ERROR_RESPONSE);
			expect(answers).not.toMatch(/no matching products|no products found|REGRESSION:/i);
			// Error embeds are intentionally transient; the assistant explanation persists.
		} finally {
			if (chatId) await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 20_000, options);
			removeWorkflowCliHome(home);
		}
	});
});
