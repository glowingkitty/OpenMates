/* eslint-disable @typescript-eslint/no-require-imports */
/** Signed, provider-free gallery serialization and reference validation. */
export {};

const { test, expect } = require('./console-monitor');
const { CLI_DIST, deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const { loginToTestAccount, startNewChat, sendMessage } = require('./helpers/chat-test-helpers');
const { pairDirectChatCli } = require('./helpers/direct-chat-cli');
const { createWorkflowCliHome, removeWorkflowCliHome, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');
const { getTestAccount, installE2EServerContentOverrideGate } = require('./signup-flow-helpers');
const { installRecorderDeps } = require('./cli-tui-proof-helpers');
const fs = require('node:fs');

const PROMPT = 'Find bio joghurt on REWE. SHOPPING_IMAGES_E2E:gallery <<<TEST_LIVE_MOCK:shopping_images_web>>>';
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
	const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	test.beforeAll(() => {
		installRecorderDeps();
	});

	// contract-test: direct surface=rest_api assertions=app-skills.surface.semantic-parity,shopping-search.relevance.bounded
	test('OpenAPI exposes optional reference images with a maximum of three', async ({ request }: { request: any }) => {
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
	});

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity,shopping-search.products.supplied-gallery
	test('CLI preserves every provider photo through encrypted parent and child embeds', async ({ page }: { page: any }, testInfo: any) => {
		test.skip(!getTestAccount().email, 'Disposable CI account required.');
		const home = createWorkflowCliHome('shopping-images');
		const env = { ...workflowCliEnv(apiUrl, home), LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe' };
		const options = { useApiKey: false, record: false, env };
		let chatId: string | undefined;
		let replayMarkerSubmitted = false;
		page.on('websocket', (socket: any) => socket.on('framesent', (frame: { payload: string | Buffer }) => {
			try {
				const packet = JSON.parse(frame.payload.toString());
				const payload = packet.payload;
				const marker = payload?.inference_request?.test_mock_marker || payload?.test_mock_marker;
				if (marker === '<<<TEST_LIVE_MOCK:shopping_images_web>>>') replayMarkerSubmitted = true;
			} catch {
				// Ignore transport frames that are not application JSON.
			}
		}));
		try {
			await installE2EServerContentOverrideGate(page, 'shopping-images-replay');
			await loginToTestAccount(page, (message: string) => console.log(message));
			expect(await page.evaluate(() => {
				const raw = sessionStorage.getItem('openmates_e2e_log_forwarding');
				if (!raw) return false;
				const gate = JSON.parse(raw);
				return typeof gate.runId === 'string' && typeof gate.token === 'string';
			}), 'Isolated replay override gate is installed before starting the shopping chat').toBe(true);
			await startNewChat(page);
			// The browser helper submits the marker through the existing account-bound
			// signing field. A marker in CLI message text is deliberately unauthorized.
			await sendMessage(page, PROMPT);
			await expect.poll(() => replayMarkerSubmitted, {
				message: 'Shopping replay marker crossed the browser signing field', timeout: 5000
			}).toBe(true);
			// This fixture's answer has no inline embed reference. Verify the saved
			// parent/child graph through the owner's CLI independently of rendering.
			await expect(page.getByTestId('message-assistant').last()).toContainText(
				'The REWE search result is available in the shopping card.', { timeout: 60_000 }
			);
			chatId = page.url().match(/chat-id=([a-zA-Z0-9-]+)/)?.[1]
				|| await page.locator('[data-action="message-input"]').last().getAttribute('data-current-chat-id');
			expect(chatId, 'Signed shopping web chat has a persisted identity').toBeTruthy();
			await pairDirectChatCli(page, apiUrl, home, CLI_DIST);
			await page.close();
			const shown = await runCli(apiUrl, ['chats', 'show', chatId!, '--json'], 45_000, options);
			expectCliSuccess(shown, 'Read persisted shopping chat');
			const messages = parseCliJson(shown).messages;
			expect(messages.some((message: any) => message.role === 'assistant')).toBe(true);
			const pending: string[] = [...new Set<string>(messages.flatMap((message: any) => message.embedIds || message.embed_ids || []))];
			expect(pending.length, 'Saved assistant message references its skill embed').toBeGreaterThan(0);
			const visited = new Set<string>();
			let productId: string | undefined;
			let parentSeen = false;
			while (pending.length) {
				const id = pending.shift()!;
				if (visited.has(id)) continue;
				visited.add(id);
				expect(visited.size, 'The result embed graph stays bounded').toBeLessThanOrEqual(10);
				const read = await runCli(apiUrl, ['embeds', 'show', id, '--chat', chatId!, '--json'], 45_000, options);
				expectCliSuccess(read, 'Decrypt shopping parent/child');
				const embed = parseCliJson(read);
				const content = typeof embed.content === 'string' ? JSON.parse(embed.content) : embed.content;
				expect(content).toBeTruthy();
				const childIds = content.embed_ids || [];
				pending.push(...(Array.isArray(childIds) ? childIds : String(childIds).split('|')).filter(Boolean));
				if (childIds.length) parentSeen = true;
				if (content.product_id === '8304439') productId = id;
			}
			expect(parentSeen, 'The persisted search parent references its product child').toBe(true);
			expect(productId, 'The real provider parser product survives client decryption').toBeTruthy();
			// Record the actual decrypted product read, so terminal proof includes
			// every gallery URL rather than just the chat's embed identifiers.
			const recorded = await runCli(apiUrl, ['embeds', 'show', productId!, '--chat', chatId!, '--json'], 45_000, {
				...options, record: true,
				env: { ...env, OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: 'skill-shopping-images-gallery' }
			});
			if (recorded.recording && fs.existsSync(recorded.recording.videoPath)) {
				await testInfo.attach('shopping-gallery-cli-terminal', { path: recorded.recording.videoPath, contentType: 'video/mp4' });
				await testInfo.attach('shopping-gallery-cli-transcript', { path: recorded.recording.transcriptPath, contentType: 'text/plain' });
			}
			expectCliSuccess(recorded, 'Read the persisted shopping product gallery');
			expect(recorded.recording && fs.existsSync(recorded.recording.videoPath), 'Shopping gallery CLI terminal capture exists').toBe(true);
			const savedProduct = parseCliJson(recorded);
			const product = typeof savedProduct.content === 'string' ? JSON.parse(savedProduct.content) : savedProduct.content;
			expect(product.image_url).toBe(GALLERY[0]);
			// Embed TOON stores scalar lists with the shared pipe encoding.
			const photos = Array.isArray(product.image_urls) ? product.image_urls : String(product.image_urls || '').split('|');
			expect(photos).toEqual(GALLERY);
			expect(product.visual_match, 'No reference supplied: do not claim visual verification').toBeUndefined();
		} finally {
			if (chatId) await runCli(apiUrl, ['chats', 'delete', chatId, '--yes'], 20_000, options);
			removeWorkflowCliHome(home);
		}
	});

	// contract-test: direct surface=cli assertions=app-skills.surface.semantic-parity,shopping-search.references.authorized,shopping-search.relevance.bounded
	test('CLI rejects four references and an unowned reference before provider search', async () => {
		test.skip(!process.env.OPENMATES_TEST_ACCOUNT_API_KEY, 'Disposable CI API key required.');
		for (const count of [4, 1]) {
			const referenceImages = Array.from({ length: count }, (_, index) => `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`);
			const result = await runCli(apiUrl, ['apps', 'shopping', 'search_products', '--input', JSON.stringify({
				requests: [{ query: 'bio joghurt', provider: 'REWE', reference_images: referenceImages }]
			}), '--json'], 45_000, {
				env: { OPENMATES_CLI_RECORD_E2E: '1', OPENMATES_E2E_SPEC: `skill-shopping-images-invalid-${count}`,
					LIBGL_ALWAYS_SOFTWARE: 'true', GALLIUM_DRIVER: 'llvmpipe' }
			});
			const output = `${result.stdout}\n${result.stderr}`;
			expect(result.recording && fs.existsSync(result.recording.videoPath), `Reference validation CLI terminal capture: ${output}`).toBe(true);
			expect(output).toMatch(count === 4 ? /List should have at most 3 items after validation, not 4/i : /Reference image is unavailable to this caller/i);
			expect(output).not.toContain('img.rewe-static.de');
		}
	});
});
