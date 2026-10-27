/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Unified 4-phase E2E test for web/search skill.
 *
 * Phase 1: Embed preview renders at /dev/preview/embeds/web
 * Phase 2: CLI direct skill command (openmates apps web search --json)
 * Phase 3: CLI chat send triggers skill (openmates chats new "..." --json)
 * Phase 4: Web UI chat triggers skill with embed rendering + fullscreen
 *
 * All chat phases use withLiveMockMarker — the full pipeline always runs,
 * only external API calls (LLM + HTTP) are cached.
 *
 * Architecture context: docs/architecture/embeds.md
 */
import type { Page, TestInfo, WebSocket as PlaywrightWebSocket } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
export {};

const { test, expect } = require('./console-monitor');
const {
	createSignupLogger,
	archiveExistingScreenshots,
	createStepScreenshotter,
	getTestAccount,
	withLiveMockMarker,
	installE2EServerContentOverrideGate
} = require('./signup-flow-helpers');
const {
	loginToTestAccount,
	startNewChat,
	sendMessage,
	waitForAssistantMessage,
	deleteActiveChat
} = require('./helpers/chat-test-helpers');
const { deriveApiUrl, runCli, parseCliJson, expectCliSuccess } = require('./helpers/cli-test-helpers');
const { openCompletedAssistantActivity } = require('./helpers/chat-scroll');
const {
	verifyEmbedPreviewPage,
	waitForEmbedFinished,
	openFullscreen,
	verifySearchGrid,
	closeFullscreen
} = require('./helpers/embed-test-helpers');

const WEB_SEARCH_FIXTURE_QUERY = 'openmates_e2e_web_fixture_ai';
const SEARCH_ACTIVITY_OPTIONS = { timeout: 90_000 };

/** Observe only correlation metadata for the two legacy replay cases. */
function observeWebSearch(page: Page, testInfo: TestInfo, group: string) {
	const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
	const flags = new Set<string>();
	const events: Record<string, string | boolean>[] = [];
	let chatId: string | null = null;
	const messageIdMatches = (value: unknown): value is string => typeof value === 'string' && !!chatId
		&& (uuid.test(value) || (value.startsWith(`${chatId.slice(-10)}-`) && uuid.test(value.slice(11))));
	const sockets = new Map<PlaywrightWebSocket, () => void>();
	const snapshot = () => ({ schema: 1, title: testInfo.title, retry: testInfo.retry, group,
		chat_id: chatId, flags: [...flags].sort(), events });
	const receive = (direction: 'sent' | 'received', frame: { payload: string | Buffer }) => {
		if (!chatId) return;
		if (Buffer.byteLength(frame.payload) > 64 * 1024) {
			flags.add('frame_limit');
			return;
		}
		try {
			const text = frame.payload.toString();
			let quoted = false, escaped = false, depth = 0, containers = 0, separators = 0;
			for (const character of text) {
				if (quoted) {
					if (escaped) escaped = false;
					else if (character === '\\') escaped = true;
					else if (character === '"') quoted = false;
				} else if (character === '"') quoted = true;
				else if (character === '{' || character === '[') { depth++; containers++; }
				else if (character === '}' || character === ']') depth--;
				else if (character === ',' || character === ':') separators++;
				if (depth > 12 || containers > 96 || separators > 256) { flags.add('frame_structure_limit'); return; }
			}
			const message = JSON.parse(text);
			const p = message?.payload;
			if (!p || p.chat_id !== chatId) return;
			const event: Record<string, string | boolean> = {
				utc: new Date().toISOString(), direction, event: message.type, chat_id: chatId
			};
			if (direction === 'sent' && ['chat_turn_preflight', 'chat_turn_admit', 'chat_message_added'].includes(message.type)) {
				const nested = message.type !== 'chat_message_added';
				const id = nested ? p.message_id ?? p.inference_request?.message?.message_id : p.message?.message_id;
				if (!messageIdMatches(id)) { flags.add('invalid_message_id'); return; }
				if (nested && [p.message_id, p.inference_request?.message?.message_id,
					p.encrypted_user_message?.client_message_id].some(alias => alias !== undefined && alias !== id)) {
					flags.add('message_alias_mismatch'); return;
				}
				event.message_id = id;
				if (nested && p.turn_id !== undefined) {
					if (typeof p.turn_id !== 'string' || !uuid.test(p.turn_id)) { flags.add('invalid_turn_id'); return; }
					event.turn_id = p.turn_id;
				}
				const marker = nested ? p.inference_request?.test_mock_marker : p.test_mock_marker;
				event.marker_present = typeof marker === 'string' && marker.length > 0;
				event.expected_group_match = marker === `<<<TEST_LIVE_MOCK:${group}>>>`;
			} else if (direction === 'received' && message.type === 'ai_task_initiated') {
				if (!messageIdMatches(p.user_message_id)) { flags.add('invalid_message_id'); return; }
				if (typeof p.ai_task_id !== 'string' || !uuid.test(p.ai_task_id)) { flags.add('invalid_task_id'); return; }
				event.message_id = p.user_message_id;
				event.task_id = p.ai_task_id;
			} else return;
			if (events.length >= 64 || Buffer.byteLength(JSON.stringify({ ...snapshot(), events: [...events, event] })) > 15 * 1024) {
				flags.add('event_or_byte_limit');
				return;
			}
			events.push(event);
		} catch { /* Malformed/unrelated transport input is never retained. */ }
	};
	const opened = (socket: PlaywrightWebSocket) => {
		if (sockets.size >= 8) { flags.add('socket_limit'); return; }
		const sent = (frame: { payload: string | Buffer }) => receive('sent', frame);
		const received = (frame: { payload: string | Buffer }) => receive('received', frame);
		const detach = () => {
			socket.off('framesent', sent);
			socket.off('framereceived', received);
			socket.off('close', detach);
			sockets.delete(socket);
		};
		sockets.set(socket, detach);
		socket.on('framesent', sent);
		socket.on('framereceived', received);
		socket.on('close', detach);
	};
	page.on('websocket', opened);
	return {
		async arm() {
			const binding = await page.locator('[data-action="message-input"]').evaluateAll(
				(nodes) => nodes.at(-1)?.getAttribute('data-current-chat-id') ?? null
			).catch(() => null);
			if (binding && uuid.test(binding)) chatId = binding;
			else flags.add('binding_missing');
		},
		async attach() {
			if (chatId) {
				try {
					const state = await page.evaluate(() => ({
						users: Math.min(document.querySelectorAll('[data-testid="message-user"]').length, 1000),
						assistants: Math.min(document.querySelectorAll('[data-testid="message-assistant"]').length, 1000),
						streaming: [...document.querySelectorAll('[data-testid="message-assistant"]')].slice(-2)
							.map(node => node.getAttribute('data-streaming') === 'true'),
						groupPresent: !!document.querySelector('[data-testid="assistant-activity-group"]'),
						groupExpanded: document.querySelector('[data-testid="assistant-activity-toggle"]')?.getAttribute('aria-expanded') === 'true'
					}));
					const stopVisible = await page.getByTestId('stop-processing-button').isVisible();
					await testInfo.attach('web-search-failure-state', { body: JSON.stringify({ ...state, stopVisible }), contentType: 'application/json' });
				} catch { flags.add('state_capture_failed'); }
				try {
					await testInfo.attach('web-search-before-cleanup', { body: await page.screenshot(), contentType: 'image/png' });
				} catch { flags.add('image_capture_failed'); }
			}
			const path = testInfo.outputPath('web-search-correlation.json');
			await writeFile(path, JSON.stringify(snapshot()), { flag: 'wx', mode: 0o600 });
			await testInfo.attach('web-search-correlation', { path, contentType: 'application/json' });
		},
		dispose() {
			page.off('websocket', opened);
			for (const detach of [...sockets.values()]) detach();
		}
	};
}

function isBraveQuotaFailure(result: { stderr: string }): boolean {
	return /Brave Search API error: 429/.test(result.stderr) && /QUOTA_LIMITED/.test(result.stderr);
}

test.describe('App: Web / Skill: search', () => {
	test.setTimeout(120_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	// ── Phase 1: Embed preview renders ─────────────────────────────────────
	// contract-test: supporting surface=gui.web assertions=web-search.surface-parity
	test('Phase 1: embed preview renders at /dev/preview/embeds/web', async ({ page }) => {
		const log = (msg: string) => console.log(`[P1] ${msg}`);
		await verifyEmbedPreviewPage(page, 'web', log);
	});

	// ── Phase 2: CLI direct skill command ──────────────────────────────────
	// contract-test: direct surface=cli assertions=web-search.request.validated,web-search.results.bounded,web-search.surface-parity,app-skills.search-relevance.safe-finalization
	test('Phase 2: CLI apps web search returns results', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const result = await runCli(
			apiUrl,
			[
				'apps', 'web', 'search',
				'--input', JSON.stringify({ requests: [{ query: WEB_SEARCH_FIXTURE_QUERY, count: 2 }] }),
				'--json'
			],
			30_000
		);
		test.skip(
			isBraveQuotaFailure(result),
			'Brave Search provider quota exhausted; direct provider contract cannot run in this environment.'
		);
		expectCliSuccess(result);
		const parsed = parseCliJson(result);
		const results = parsed.data?.results?.[0]?.results || [];
		expect(results.length).toBeLessThanOrEqual(2);
		expect(result.stdout.length).toBeGreaterThan(10);
		expect(result.stderr).not.toMatch(/error|failed|exception/i);
		console.log(`[P2] web/search returned ${result.stdout.length} chars`);
	});

	// ── Phase 3: CLI chat send triggers skill ──────────────────────────────
	// contract-test: supporting surface=cli assertions=web-search.surface-parity
	test('Phase 3: CLI chats new triggers web search', async () => {
		test.skip(
			!process.env.OPENMATES_TEST_ACCOUNT_API_KEY,
			'OPENMATES_TEST_ACCOUNT_API_KEY required.'
		);

		const message = withLiveMockMarker(`Search the web for ${WEB_SEARCH_FIXTURE_QUERY}`, 'web_search_cli');
		const result = await runCli(apiUrl, ['chats', 'new', message, '--json'], 60_000);
		expectCliSuccess(result);

		const parsed = parseCliJson(result);
		expect(parsed).toBeTruthy();
		const assistant = String(parsed.assistant || '');
		expect(
			assistant.trim().length,
			'tool continuation should return a final assistant answer'
		).toBeGreaterThan(20);
		expect(assistant).not.toMatch(
			/unexpected `tool_use_id`|all providers failed|something went wrong|empty_post_tool_response|main processing failed/i
		);
		console.log(`[P3] CLI chat response length: ${result.stdout.length}`);

		// Cleanup: extract chat ID and delete
		if (parsed.chat_id) {
			await runCli(apiUrl, ['chats', 'delete', parsed.chat_id, '--yes'], 15_000);
		}
	});

	// S7HHQ: classifier omission must not turn explicit research into a code card.
	// The signed replay returns zero app/skill scores and rejects main requests
	// without both baseline search tools. Execution, embeds and persistence are real.
	// contract-test: direct surface=gui.web assertions=web-search.surface-parity,app-skills.execution.registered-validated
	test('Baseline web and image searches survive an empty app shortlist', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(180_000);
		test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
			|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		const log = createSignupLogger('WEB_RESEARCH_ROUTING');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'web-research-routing' });
		await installE2EServerContentOverrideGate(page, 'web-research-routing');
		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);
		try {
			await sendMessage(page,
				'Kannst du bitte online recherchieren und die Quellen vergleichen? MERCURY_ROUTING_E2E:web_research <<<TEST_LIVE_MOCK:mercury_auto_low>>>',
				log, screenshot, 'web-research');
			const assistant = await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
			await expect(assistant).toContainText('Die Websuche wurde ausgeführt.', { timeout: 60_000 });
			await openCompletedAssistantActivity(assistant.getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);
			const embed = await waitForEmbedFinished(page, 'web', 'search');
			await expect(embed).toContainText(WEB_SEARCH_FIXTURE_QUERY);
			await expect(assistant).not.toContainText('requests:');
			await screenshot(page, 'web-research-search-executed');
			const fullscreen = await openFullscreen(page, embed);
			await expect(fullscreen).toContainText('OpenMates E2E Web Fixture');
			await closeFullscreen(page, fullscreen);
			await page.reload({ waitUntil: 'domcontentloaded' });
			await openCompletedAssistantActivity(page.getByTestId('message-assistant').last().getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);
			const persisted = await waitForEmbedFinished(page, 'web', 'search');
			await expect(persisted).toContainText(WEB_SEARCH_FIXTURE_QUERY);
			await expect(page.getByTestId('message-assistant').last()).toContainText('Die Websuche wurde ausgeführt.');
			await screenshot(page, 'web-research-persisted');
		} finally {
			if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'web-research-cleanup');
		}
	});

	// ── Phase 5: Zero-hit query must NOT show "App skill processing error" ──
	// Regression guard for Linear OPE-405 / prod issue 0d73ab38.
	// When one sub-query in a parallel multi-search legitimately returns 0 Brave
	// results, the assistant answer must still render cleanly without the red
	// embed-error banner, and the zero-hit embed must finalize to status=finished
	// (not status=error). Fix is in backend/apps/ai/processing/main_processor.py.
	// contract-test: direct surface=gui.web assertions=web-search.no-results.explicit,web-search.surface-parity
	test('Phase 5: Zero-result query does not show error banner', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-web-search-zero-results');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		const diagnostic = observeWebSearch(page, testInfo, 'web_search_zero_results');
		try {
			await installE2EServerContentOverrideGate(page, 'web-search-zero-results');
			await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
			await startNewChat(page, logCheckpoint);

			// Deterministically zero-hit query: the impossible-exact-phrase combined with
			// an unusual language fragment never matches anything on Brave. Verified
			// directly against the Brave API as part of OPE-405.
			const message = withLiveMockMarker(
				'Search the web for "xyznonexistentproduct123456" lokale API MQTT — just try to find results',
				'web_search_zero_results'
			);
			await diagnostic.arm();
			await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'web-search-zero');
			await openCompletedAssistantActivity(page.getByTestId('message-assistant').last().getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);

			// The embed must finalize to status=finished (NOT status=error).
			logCheckpoint('Waiting for web search embed to finalize (finished or error)...');
			const anyEmbed = page.locator(
				'[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]'
			).first();
			await expect(anyEmbed).toBeVisible({ timeout: 90_000 });

			// Poll until status is no longer "processing"
			await expect(async () => {
				const status = await anyEmbed.getAttribute('data-status');
				expect(['finished', 'error']).toContain(status);
			}).toPass({ timeout: 90_000 });

			const finalStatus = await anyEmbed.getAttribute('data-status');
			logCheckpoint(`Zero-result embed final status: ${finalStatus}`);

			// PRIMARY ASSERTIONS (the bug)
			expect(
				finalStatus,
				`Zero-result web search embed must finalize to "finished", not "error". ` +
				`Got: ${finalStatus}. This is the OPE-405 regression — backend is mis-classifying ` +
				`empty Brave results as a skill failure.`
			).toBe('finished');

			// The red error banner must NOT appear on the assistant message.
			const errorBanner = page.getByTestId('embed-error-banner');
			await expect(
				errorBanner,
				'Red "App skill processing error" banner must not appear when the only ' +
				'failure is a legitimate zero-hit search.'
			).not.toBeVisible();

			// Zero-result embed must render a clear generic "No results found" message.
			// The query is already shown above this line in the card, so repeating it
			// creates redundant wrapping pressure in narrow assistant messages.
			const noResultsPreviewMessage = anyEmbed.getByTestId('search-no-results-message');
			await expect(
				noResultsPreviewMessage,
				'Zero-result web search embed must show a "No results found" message in the preview.'
			).toBeVisible({ timeout: 15_000 });
			const previewText = (await noResultsPreviewMessage.textContent()) || '';
			expect(
				previewText.toLowerCase(),
				`No-results preview text must mention "no results" (got: "${previewText}")`
			).toContain('no results');
			expect(
				previewText,
				`No-results preview must not repeat the query string (got: "${previewText}")`
			).not.toContain('xyznonexistentproduct123456');
			expect(
				previewText,
				`No-results preview should be generic (got: "${previewText}")`
			).toMatch(/^\s*No results found\s*$/i);
			logCheckpoint(`Preview no-results message: "${previewText}"`);

			// Open the fullscreen and verify the same message renders there too.
			const fullscreenOverlay = await openFullscreen(page, anyEmbed);
			logCheckpoint('Fullscreen opened for zero-result embed.');
			const fullscreenNoResults = fullscreenOverlay.getByTestId('search-no-results-message');
			await expect(
				fullscreenNoResults,
				'Fullscreen must also render the no-results message when the search returned 0 hits.'
			).toBeVisible({ timeout: 10_000 });
			const fullscreenText = (await fullscreenNoResults.textContent()) || '';
			expect(fullscreenText).not.toContain('xyznonexistentproduct123456');
			expect(fullscreenText).toMatch(/^\s*No results found\s*$/i);
			await takeStepScreenshot(page, 'zero-results-fullscreen');
			await closeFullscreen(page, fullscreenOverlay);
			logCheckpoint('Fullscreen closed.');

			// Assistant response text must be non-empty — the LLM answer should render
			// regardless of the zero-hit sub-query.
			const assistantMessage = page.getByTestId('message-assistant').last();
			await expect(assistantMessage).toBeVisible({ timeout: 30_000 });
			await takeStepScreenshot(page, 'zero-results-embed-final');

			logCheckpoint('Phase 5 passed: zero-hit query rendered without error banner.');
			await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'web-search-zero');
		} catch (error) {
			await diagnostic.attach().catch(() => {});
			throw error;
		} finally {
			diagnostic.dispose();
		}
	});

	// ── Phase 4: Web UI chat triggers skill ────────────────────────────────
	// contract-test: direct surface=gui.web assertions=web-search.surface-parity
	test('Phase 4: Web chat triggers web search with embed', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.slow();
		test.setTimeout(300_000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');

		const logCheckpoint = createSignupLogger('skill-web-search');
		await archiveExistingScreenshots(logCheckpoint);
		const takeStepScreenshot = createStepScreenshotter(logCheckpoint);

		const diagnostic = observeWebSearch(page, testInfo, 'web_search_web');
		try {
			await installE2EServerContentOverrideGate(page, 'web-search-web');
			await loginToTestAccount(page, logCheckpoint, takeStepScreenshot);
			await startNewChat(page, logCheckpoint);

			const message = withLiveMockMarker(
				`Search the web for ${WEB_SEARCH_FIXTURE_QUERY}`,
				'web_search_web'
			);
			await diagnostic.arm();
			await sendMessage(page, message, logCheckpoint, takeStepScreenshot, 'web-search');
			await openCompletedAssistantActivity(page.getByTestId('message-assistant').last().getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);

			logCheckpoint('Waiting for web search embed to finish...');
			const embed = await waitForEmbedFinished(page, 'web', 'search');
			logCheckpoint('Web search embed finished.');
			await expect(embed, 'Finished web search card must keep the visible query.').toContainText(WEB_SEARCH_FIXTURE_QUERY);
			const assistantMessage = page.getByTestId('message-assistant').last();
			await expect(assistantMessage).not.toContainText('app_skill_use');
			await expect(assistantMessage).not.toContainText('embed_ref');
			await takeStepScreenshot(page, 'web-search-embed-finished');

			const fullscreenOverlay = await openFullscreen(page, embed);
			logCheckpoint('Fullscreen opened.');

			const resultsGrid = fullscreenOverlay.getByTestId('search-template-grid');
			const noResultsMessage = fullscreenOverlay.getByTestId('search-no-results-message');
			await expect(async () => {
				const hasGrid = await resultsGrid.isVisible().catch(() => false);
				const hasNoResults = await noResultsMessage.isVisible().catch(() => false);
				expect(hasGrid || hasNoResults).toBe(true);
			}).toPass({ timeout: 60_000 });

			if (await resultsGrid.isVisible().catch(() => false)) {
				const resultCards = await verifySearchGrid(fullscreenOverlay);
				const count = await resultCards.count();
				logCheckpoint(`Found ${count} search result(s) in fullscreen grid.`);
			} else {
				const noResultsText = (await noResultsMessage.textContent()) || '';
				logCheckpoint(`Web search returned no results in fullscreen: ${noResultsText}`);
			}

			await closeFullscreen(page, fullscreenOverlay);
			logCheckpoint('Fullscreen closed.');

			await page.reload({ waitUntil: 'domcontentloaded' });
			await openCompletedAssistantActivity(page.getByTestId('message-assistant').last().getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);
			const reloadedEmbed = await waitForEmbedFinished(page, 'web', 'search');
			await expect(reloadedEmbed, 'Reloaded web search card must keep the visible query.').toContainText(WEB_SEARCH_FIXTURE_QUERY);
			const reloadedAssistantMessage = page.getByTestId('message-assistant').last();
			await expect(reloadedAssistantMessage).not.toContainText('app_skill_use');
			await expect(reloadedAssistantMessage).not.toContainText('embed_ref');
			logCheckpoint('Reload preserved finished web search card without raw protocol text.');

			await deleteActiveChat(page, logCheckpoint, takeStepScreenshot, 'web-search');
		} catch (error) {
			await diagnostic.attach().catch(() => {});
			throw error;
		} finally {
			diagnostic.dispose();
		}
	});
});


test.describe('Web search credential throttling', () => {
	test.setTimeout(180_000);
	// contract-test: direct surface=gui.web assertions=web-search.provider-error.visible,web-search.surface-parity
	test('Concurrent searches recover throttling and persist a completed answer', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.skip(process.env.CI !== 'true' || process.env.CI_TEST_MODE !== 'e2e'
			|| process.env.OPENMATES_CI_ISOLATED !== '1', 'Requires the isolated provider-free product stack.');
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		const log = createSignupLogger('WEB_SEARCH_THROTTLE');
		const screenshot = createStepScreenshotter(log, { filenamePrefix: 'web-search-throttle' });
		await installE2EServerContentOverrideGate(page, 'web-search-throttle');
		await loginToTestAccount(page, log, screenshot);
		await startNewChat(page, log);
		try {
			await sendMessage(page,
				'Compare four web sources. MERCURY_ROUTING_E2E:web_throttle <<<TEST_LIVE_MOCK:mercury_auto_low>>>',
				log, screenshot, 'parallel-searches');
			const assistant = await waitForAssistantMessage(page, { which: 'last', logCheckpoint: log });
			await expect(assistant).toContainText('All four web searches completed successfully.', { timeout: 90_000 });
			await openCompletedAssistantActivity(assistant.getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);
			const cards = page.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]');
			await expect(cards).toHaveCount(4);
			for (let index = 0; index < 4; index++) {
				await expect(cards.nth(index)).toHaveAttribute('data-status', 'finished');
				await expect(cards.nth(index)).toContainText('throttle');
			}
			await expect(page.getByTestId('embed-error-banner')).toHaveCount(0);
			await screenshot(page, 'all-searches-finished');
			await page.reload({ waitUntil: 'domcontentloaded' });
			await openCompletedAssistantActivity(page.getByTestId('message-assistant').last().getByTestId('assistant-activity-group'), testInfo, SEARCH_ACTIVITY_OPTIONS);
			await expect(cards).toHaveCount(4, { timeout: 30_000 });
			await expect(page.getByTestId('message-assistant').last()).toContainText('All four web searches completed successfully.');
			for (let index = 0; index < 4; index++) {
				await expect(cards.nth(index)).toHaveAttribute('data-status', 'finished');
			}
			await expect(page.getByTestId('embed-error-banner')).toHaveCount(0);
			await screenshot(page, 'completed-answer-persisted');
		} catch (error) {
			const documents = await page.getByTestId('message-assistant').evaluateAll(
				(nodes: HTMLElement[]) => nodes.map(node => node.outerHTML)
			).catch(() => []);
			await testInfo.attach('throttle-failure-assistant-dom', { body: JSON.stringify(documents), contentType: 'application/json' });
			await testInfo.attach('throttle-failure-before-cleanup', { body: await page.screenshot(), contentType: 'image/png' });
			throw error;
		} finally {
			if (/chat-id=/.test(page.url())) await deleteActiveChat(page, log, screenshot, 'throttle-cleanup');
		}
	});
});
