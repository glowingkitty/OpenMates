/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Deployed Teams context and transport coverage.
 *
 * Verifies profile-menu context switching replaces Personal chats, scopes
 * phased sync and durable preflight to the selected Team, and sends ordinary
 * Team messages as ciphertext without an AI invocation.
 */
export {};

import type { Page, Request, Response } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
	dismissSecurityReminderIfPresent,
	fillMessageEditor,
	focusMessageEditor,
	loginToTestAccount,
	startNewChat
} = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

type ProtocolFrame = {
	direction: 'sent' | 'received';
	type: string;
	payload: Record<string, any>;
	raw: string;
};

function sanitizeStartupError(value: string): string {
	return value
		.split('\n', 1)[0]
		.slice(0, 1000)
		.replace(/\b(?:https?|wss?):\/\/[^\s"'<>]+/gi, '<url>')
		.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '<email>')
		.replace(/\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*/gi, '<authorization>')
		.replace(/\b(?:access[_-]?token|refresh[_-]?token|session|password|api[_-]?key|secret|code)\s*[:=]\s*["']?[^,\s"'&]+/gi, '<credential>')
		.replace(/[?#][A-Za-z0-9_%-][^\s"'<>]*/g, '<url-parameters>')
		.replace(/\b[A-Za-z0-9_-]{32,}\b/g, '<opaque-value>');
}

function deriveApiUrl(baseUrl: string): string {
	if (process.env.PLAYWRIGHT_TEST_API_URL)
		return process.env.PLAYWRIGHT_TEST_API_URL.replace(/\/$/, '');
	const url = new URL(baseUrl);
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
	throw new Error(`Cannot derive API URL from PLAYWRIGHT_TEST_BASE_URL=${baseUrl}.`);
}

function captureProtocol(page: Page, frames: ProtocolFrame[], apiUrl: string): void {
	const expectedApiHost = new URL(apiUrl).host;
	page.on('websocket', (websocket) => {
		if (new URL(websocket.url()).host !== expectedApiHost) return;
		const capture =
			(direction: ProtocolFrame['direction']) => (frame: { payload?: string | Buffer }) => {
				const raw = String(frame.payload ?? '');
				try {
					const parsed = JSON.parse(raw) as Record<string, any>;
					if (
						typeof parsed.type !== 'string' ||
						typeof parsed.payload !== 'object' ||
						!parsed.payload
					)
						return;
					frames.push({ direction, type: parsed.type, payload: parsed.payload, raw });
				} catch {
					// WebSocket control frames are not JSON protocol messages.
				}
			};
		websocket.on('framesent', capture('sent'));
		websocket.on('framereceived', capture('received'));
	});
}

async function installOneTeamPreflightAckDrop(page: Page): Promise<void> {
	await page.addInitScript(() => {
		const NativeWebSocket = window.WebSocket;
		const state = { armedTeamId: null as string | null, turnId: null as string | null, dropped: 0 };
		(
			window as Window & {
				__teamPreflightAckDrop?: {
					arm: (teamId: string) => void;
					snapshot: () => { turnId: string | null; dropped: number };
				};
			}
		).__teamPreflightAckDrop = {
			arm(teamId: string) {
				state.armedTeamId = teamId;
				state.turnId = null;
			},
			snapshot: () => ({ turnId: state.turnId, dropped: state.dropped })
		};

		function TestWebSocket(this: WebSocket, ...args: ConstructorParameters<typeof WebSocket>) {
			const socket = new NativeWebSocket(...args);
			const nativeSend = socket.send.bind(socket);
			socket.send = (data: string | ArrayBufferLike | Blob | ArrayBufferView) => {
				if (typeof data === 'string' && state.armedTeamId && !state.turnId) {
					try {
						const frame = JSON.parse(data);
						if (
							frame?.type === 'chat_turn_preflight' &&
							frame.payload?.team_id === state.armedTeamId
						) {
							state.turnId = frame.payload.turn_id;
						}
					} catch {
						// Other WebSocket traffic is outside this fixture.
					}
				}
				return nativeSend(data);
			};
			socket.addEventListener('message', (event: MessageEvent) => {
				if (!state.armedTeamId || !state.turnId || state.dropped > 0) return;
				try {
					const frame = JSON.parse(String(event.data));
					if (
						frame?.type === 'chat_turn_preflight_ack' &&
						frame.payload?.turn_id === state.turnId
					) {
						state.dropped += 1;
						state.armedTeamId = null;
						event.stopImmediatePropagation();
					}
				} catch {
					// Other WebSocket traffic is outside this fixture.
				}
			});
			return socket;
		}
		Object.setPrototypeOf(TestWebSocket, NativeWebSocket);
		TestWebSocket.prototype = NativeWebSocket.prototype;
		window.WebSocket = TestWebSocket as typeof WebSocket;
	});
}

async function waitForFrame(
	frames: ProtocolFrame[],
	startIndex: number,
	direction: ProtocolFrame['direction'],
	type: string,
	predicate: (payload: Record<string, any>) => boolean
): Promise<ProtocolFrame> {
	let match: ProtocolFrame | undefined;
	await expect
		.poll(
			() => {
				match = frames
					.slice(startIndex)
					.find(
						(frame) =>
							frame.direction === direction && frame.type === type && predicate(frame.payload)
					);
				return Boolean(match);
			},
			{ timeout: 30000 }
		)
		.toBe(true);
	return match!;
}

function isApiPath(response: Response, method: string, pathname: string): boolean {
	if (response.request().method() !== method) return false;
	try {
		return new URL(response.url()).pathname === pathname;
	} catch {
		return false;
	}
}

async function ensureSidebarOpen(page: Page): Promise<void> {
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (await sidebar.isVisible().catch(() => false)) return;
	await page.getByTestId('sidebar-toggle').click();
	await expect(sidebar).toBeVisible({ timeout: 15000 });
}

async function ensureSidebarClosed(page: Page): Promise<void> {
	const sidebar = page.getByTestId('activity-history-wrapper');
	if (!(await sidebar.isVisible().catch(() => false))) return;
	await sidebar.getByRole('button', { name: /close/i }).click();
	await expect(sidebar).not.toBeVisible({ timeout: 15000 });
}

async function expectContinueCardsExcludeChatIds(
	page: Page,
	forbiddenChatIds: string[]
): Promise<void> {
	const forbidden = new Set(forbiddenChatIds);
	await expect
		.poll(
			async () => {
				const visibleIds = await page
					.locator('[data-testid="recent-chats-scroll-container"] [data-chat-id]')
					.evaluateAll((cards) =>
						cards
							.map((card) => card.getAttribute('data-chat-id'))
							.filter((chatId): chatId is string => Boolean(chatId))
					);
				return visibleIds.filter((chatId) => forbidden.has(chatId));
			},
			{ timeout: 15000 }
		)
		.toEqual([]);
}

async function expectContinueCardsEmpty(page: Page): Promise<void> {
	const cards = page.locator(
		[
			'[data-testid="recent-chats-scroll-container"] [data-testid="continue-priority-card"]',
			'[data-testid="recent-chats-scroll-container"] [data-testid="resume-chat-large-card"]',
			'[data-testid="recent-chats-scroll-container"] [data-testid="resume-chat-card"]',
			'[data-testid="recent-chats-scroll-container"] [data-testid="resume-chat-draft-card"]'
		].join(', ')
	);
	await expect(cards).toHaveCount(0, { timeout: 15000 });
}

async function openProfileMenu(page: Page): Promise<void> {
	await page.getByTestId('profile-container').click();
	await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 15000 });
}

async function expectProfileTeamBadge(page: Page, teamName: string): Promise<void> {
	const profile = page.getByTestId('profile-container');
	const badge = page.getByTestId('profile-active-team-avatar');
	await expect(badge).toBeVisible({ timeout: 15000 });
	await expect(badge).toHaveAttribute('aria-label', `Active team: ${teamName}`);
	await expect(badge).toHaveText('');
	expect(
		await badge.evaluate((element) => {
			const radius = getComputedStyle(element).borderTopLeftRadius;
			return radius.endsWith('%')
				? Number.parseFloat(radius) >= 50
				: Number.parseFloat(radius) >= element.getBoundingClientRect().width / 2;
		})
	).toBe(true);
	const [profileBox, badgeBox] = await Promise.all([profile.boundingBox(), badge.boundingBox()]);
	expect(profileBox).not.toBeNull();
	expect(badgeBox).not.toBeNull();
	expect(Math.abs(badgeBox!.width - badgeBox!.height)).toBeLessThanOrEqual(1);
	expect(badgeBox!.width / profileBox!.width).toBeGreaterThan(0.4);
	expect(badgeBox!.width / profileBox!.width).toBeLessThan(0.55);
	expect(Math.abs(badgeBox!.x - profileBox!.x)).toBeLessThanOrEqual(6);
	expect(badgeBox!.y).toBeGreaterThan(profileBox!.y + profileBox!.height / 2);
	expect(badgeBox!.y + badgeBox!.height).toBeGreaterThan(profileBox!.y + profileBox!.height);
}

async function expectChatTeamIdentity(page: Page): Promise<void> {
	const avatar = page.getByTestId('chats-workspace-team-avatar');
	const icon = page.getByTestId('guest-workspace-icon');
	await expect(avatar).toBeVisible({ timeout: 15000 });
	await expect(icon).toBeVisible();
	await expect(avatar).toHaveCSS('opacity', '0.3');
	const [avatarBox, iconBox] = await Promise.all([avatar.boundingBox(), icon.boundingBox()]);
	expect(avatarBox).not.toBeNull();
	expect(iconBox).not.toBeNull();
	expect(Math.abs(avatarBox!.width - iconBox!.width)).toBeLessThanOrEqual(1);
	expect(Math.abs(avatarBox!.height - iconBox!.height)).toBeLessThanOrEqual(1);
	expect(avatarBox!.x + avatarBox!.width).toBeLessThan(iconBox!.x);
	expect(
		Math.abs(avatarBox!.y + avatarBox!.height / 2 - iconBox!.y - iconBox!.height / 2)
	).toBeLessThanOrEqual(1);
}

test.describe('Teams V1 context isolation', () => {
	// contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,teams.chat.encrypted-until-invoked,notifications.surface.semantic-parity
	test('isolates Team chats and sends ordinary Team turns as scoped ciphertext', async ({
		page
	}: {
		page: Page;
	}) => {
		test.setTimeout(300000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		const apiUrl = deriveApiUrl(
			process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org'
		);
		const frames: ProtocolFrame[] = [];
		const uniqueSuffix = `${Date.now()}-${test.info().workerIndex}`;
		const teamName = `E2E context team ${uniqueSuffix}`;
		const ordinaryMessage = 'Private Team note for context isolation';
		const lostAckMessage = 'Private Team note for preflight retry';
		const personalDraftText = `Personal context fixture ${uniqueSuffix}`;
		let teamId = '';
		let flowError: unknown;
		let cleanupError: unknown;
		const startupErrors: Array<{ kind: 'pageerror' | 'console'; name: string; message: string }> = [];
		let startupCaptureActive = true;
		const onPageError = (error: Error) => {
			if (!startupCaptureActive || startupErrors.length >= 20) return;
			startupErrors.push({
				kind: 'pageerror',
				name: /^[A-Za-z]{1,32}Error$/.test(error.name) ? error.name : 'Error',
				message: sanitizeStartupError(error.message)
			});
		};
		const onConsole = (message: { type: () => string; text: () => string }) => {
			if (!startupCaptureActive || message.type() !== 'error' || startupErrors.length >= 20) return;
			startupErrors.push({ kind: 'console', name: 'ConsoleError', message: sanitizeStartupError(message.text()) });
		};
		const stopStartupCapture = () => {
			startupCaptureActive = false;
			page.off('pageerror', onPageError);
			page.off('console', onConsole);
		};
		page.on('pageerror', onPageError);
		page.on('console', onConsole);
		captureProtocol(page, frames, apiUrl);
		await installOneTeamPreflightAckDrop(page);

		try {
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);
			stopStartupCapture();
			await dismissSecurityReminderIfPresent(page);

			await startNewChat(page);
			const personalDraftFrameIndex = frames.length;
			const personalEditor = page
				.locator('[data-action="message-input"]')
				.last()
				.getByTestId('message-editor');
			await expect(personalEditor).toBeVisible({ timeout: 30000 });
			await fillMessageEditor(page, personalEditor, personalDraftText);
			await ensureSidebarOpen(page);
			const personalDraftRow = page
				.getByTestId('chat-item-wrapper')
				.filter({ hasText: personalDraftText });
			await expect(personalDraftRow).toBeVisible({ timeout: 30000 });
			const personalDraftChatId = await personalDraftRow.getAttribute('data-chat-id');
			expect(personalDraftChatId).toBeTruthy();
			expect(personalDraftChatId).not.toMatch(/^example-/);
			await waitForFrame(
				frames,
				personalDraftFrameIndex,
				'received',
				'draft_update_receipt',
				(payload) => payload.chat_id === personalDraftChatId && payload.success === true
			);
			const personalChatIds = [personalDraftChatId!];
			await ensureSidebarClosed(page);

			await openProfileMenu(page);
			await page.getByTestId('settings-teams-item').click();
			await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });

			const createResponsePromise = page.waitForResponse(
				(response) => isApiPath(response, 'POST', '/v1/teams') && response.ok()
			);
			await page.getByTestId('team-create-open').click();
			await page.getByTestId('team-name-input').fill(teamName);
			await page.getByTestId('team-create-continue').click();
			await page.getByTestId('team-create-submit').click();
			const createResponse = await createResponsePromise;
			const createBody = (await createResponse.json()) as { team?: { team_id?: string } };
			teamId = createBody.team?.team_id ?? '';
			expect(teamId).not.toBe('');

			await page.getByTestId('banner-back-button').click();
			await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams');
			await expect(page.getByTestId('team-settings-team-row').filter({ hasText: teamName })).toBeVisible();
			await expect(page.getByTestId('team-create-open')).toBeVisible();

			// Reload the list with an existing membership. A cold settings mount must
			// fetch its encrypted Team record and finish rendering the creation CTA.
			let teamListFetches = 0;
			const countTeamListFetch = (request: Request) => {
				if (request.method() === 'GET' && new URL(request.url()).pathname === '/v1/teams') {
					teamListFetches += 1;
				}
			};
			page.on('request', countTeamListFetch);
			try {
				const teamListResponse = page.waitForResponse(
					(response) => isApiPath(response, 'GET', '/v1/teams') && response.ok(),
					{ timeout: 30000 }
				);
				await page.reload({ waitUntil: 'domcontentloaded' });
				const teamListBody = (await (await teamListResponse).json()) as {
					teams?: Array<{ team_id?: string; encrypted_name?: string }>;
				};
				expect(Array.isArray(teamListBody.teams)).toBe(true);
				const listedTeamIds = teamListBody.teams!.map((team) => team.team_id);
				expect(listedTeamIds.every((id) => typeof id === "string" && id.length > 0)).toBe(true);
				expect(new Set(listedTeamIds).size, "Team settings need one keyed row per Team").toBe(listedTeamIds.length);
				expect(teamListBody.teams?.find((team) => team.team_id === teamId)?.encrypted_name).toBeTruthy();
				expect(JSON.stringify(teamListBody)).not.toContain(teamName);
				await expect(page.getByTestId('settings-menu')).toHaveAttribute('data-active-view', 'teams', {
					timeout: 30000
				});
				await expect(page.getByTestId('team-settings-team-row').filter({ hasText: teamName })).toBeVisible({
					timeout: 30000
				});
				await expect(page.getByTestId('team-create-open')).toBeVisible({ timeout: 30000 });
				expect(teamListFetches).toBeGreaterThan(0);
				expect(teamListFetches).toBeLessThanOrEqual(2);
			} finally {
				page.off('request', countTeamListFetch);
			}

			await page.getByTestId('banner-back-button').click();
			await expect(page.getByTestId('team-context-dropdown')).toBeVisible({ timeout: 30000 });
			const teamSwitchFrameIndex = frames.length;
			await page.getByTestId('team-context-dropdown').click();
			await page.getByTestId(`team-context-option-${teamId}`).click();
			await waitForPhasedSyncCompletion(frames, teamSwitchFrameIndex, teamId);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });
			await expect(page.locator('.active-chat-container')).not.toHaveClass(/dimmed/, {
				timeout: 15000
			});
			await expectProfileTeamBadge(page, teamName);
			await openProfileMenu(page);
			await page.getByTestId('team-context-dropdown').click();
			await expect(
				page.getByTestId('team-context-menu').getByRole('menuitemradio', { name: teamName })
			).toHaveAttribute('aria-checked', 'true');
			await page.keyboard.press('Escape');
			await page.waitForTimeout(6000);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });

			await ensureSidebarOpen(page);
			for (const personalChatId of personalChatIds) {
				await expect(
					page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${personalChatId}"]`)
				).toHaveCount(0);
			}
			await expectContinueCardsExcludeChatIds(page, personalChatIds);
			await expectContinueCardsEmpty(page);
			await page.waitForTimeout(6000);
			await ensureSidebarClosed(page);
			await startNewChat(page);
			// Desktop New chat focuses the composer, which hides the welcome avatar.
			const dismissComposer = page.getByTestId('input-dismiss-button');
			if (await dismissComposer.isVisible()) {
				await dismissComposer.click();
			}
			await expect(dismissComposer).not.toBeVisible();
			await expect(page.getByTestId('chat-side')).toBeVisible();
			await expectProfileTeamBadge(page, teamName);
			await expectChatTeamIdentity(page);
			if (process.env.PLAYWRIGHT_VIDEO_WIDTH && process.env.PLAYWRIGHT_VIDEO_HEIGHT) {
				await page.waitForTimeout(1200);
			}

			const sendFrameIndex = frames.length;
			const messageInput = page.locator('[data-action="message-input"]').last();
			const editor = messageInput.getByTestId('message-editor');
			await expect(editor).toBeVisible({ timeout: 30000 });
			await fillMessageEditor(page, editor, ordinaryMessage);
			await messageInput
				.getByTestId('message-field')
				.locator('[data-action="send-message"]')
				.click();

			const preflight = await waitForFrame(
				frames,
				sendFrameIndex,
				'sent',
				'chat_turn_preflight',
				() => true
			).catch(async (error: unknown) => {
				const clientDebug = await page.evaluate(() => ({
					send:
						(window as Window & { __openmatesLastSendDebug?: Record<string, unknown> })
							.__openmatesLastSendDebug ?? null,
					chatKeyGuard:
						(window as Window & { __openmatesLastChatKeyGuardDebug?: Record<string, unknown> })
							.__openmatesLastChatKeyGuardDebug ?? null
				}));
				const observedFrames = frames
					.slice(sendFrameIndex)
					.map(({ direction, type }) => ({ direction, type }));
				throw new Error(
					`Team preflight not observed. clientDebug=${JSON.stringify(clientDebug)} observedFrames=${JSON.stringify(observedFrames)} original=${String(error)}`
				);
			});
			const sentMessage = await waitForFrame(
				frames,
				sendFrameIndex,
				'sent',
				'chat_message_added',
				(payload) => payload.team_id === teamId
			);
			const previewCapability = await waitForFrame(
				frames,
				sendFrameIndex,
				'sent',
				'team_notification_preview_capabilities',
				(payload) => payload.team_id === teamId
			);
			expect(previewCapability.raw).not.toContain(ordinaryMessage);
			expect(frames.indexOf(previewCapability)).toBeLessThan(frames.indexOf(preflight));
			// This newly created Team has no other consenting member. No plaintext
			// preview may be uploaded for the ordinary message.
			expect(
				frames
					.slice(sendFrameIndex)
					.filter(
						(frame) =>
							frame.direction === 'sent' && frame.type === 'team_notification_preview_stage'
					)
			).toEqual([]);
			expect(preflight.payload.team_id).toBe(teamId);
			expect(preflight.payload.inference_request?.team_id).toBe(teamId);
			expect(preflight.payload.inference_request?.message?.encrypted_content).toBeTruthy();
			expect(preflight.payload.inference_request?.message?.content).toBeUndefined();
			expect(preflight.payload.inference_request?.team_ai_invocation).toBeUndefined();
			expect(sentMessage.payload.message?.encrypted_content).toBeTruthy();
			expect(sentMessage.payload.message?.content).toBeUndefined();
			expect(sentMessage.payload.team_ai_invocation).toBeUndefined();
			expect(preflight.raw).not.toContain(ordinaryMessage);
			expect(sentMessage.raw).not.toContain(ordinaryMessage);
			const ordinaryMessageId = String(sentMessage.payload.message?.message_id ?? '');
			expect(ordinaryMessageId).not.toBe('');
			await waitForFrame(
				frames,
				sendFrameIndex,
				'received',
				'chat_message_confirmed',
				(payload) => payload.chat_id === sentMessage.payload.chat_id && payload.message_id === ordinaryMessageId
			).catch(async (error: unknown) => {
				await test.info().attach('ordinary-team-frame-ids', {
					body: JSON.stringify({
						expected_chat_id: sentMessage.payload.chat_id,
						expected_message_id: ordinaryMessageId,
						frames: frames.slice(sendFrameIndex).map(({ direction, type, payload }) => ({
							direction,
							type,
							chat_id: payload.chat_id,
							message_id: payload.message_id,
							turn_id: payload.turn_id,
							code: payload.code
						}))
					}, null, 2),
					contentType: 'application/json'
				});
				throw error;
			});
			const ordinaryTeamMessage = page
				.getByTestId('message-user')
				.filter({ hasText: ordinaryMessage })
				.last();
			await expect(ordinaryTeamMessage).toBeVisible({ timeout: 15000 });
			await expect(ordinaryTeamMessage.getByText('Sending...')).not.toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('chat-header-banner')).not.toContainText('Creating new chat', {
				timeout: 15000
			});
			await expect(page.getByTestId('chat-header-banner')).toContainText('New team chat', {
				timeout: 15000
			});
			// The literal mention is extracted into an encrypted code embed. It must
			// remain an ordinary Team turn even with no AI provider configured.
			const fencedMention = 'Literal code sample:\n```text\n@OpenMates summarize\n```';
			const fencedSendFrameIndex = frames.length;
			await focusMessageEditor(editor);
			await page.keyboard.insertText(fencedMention);
			await expect(editor).toContainText('Literal code sample:');
			const codeEmbed = editor.locator(
				'[data-testid="embed-full-width-wrapper"][data-embed-type="code-code"]'
			);
			await expect(codeEmbed).toContainText('@OpenMates summarize');
			await messageInput
				.getByTestId('message-field')
				.locator('[data-action="send-message"]')
				.click();
			const fencedPreflight = await waitForFrame(
				frames,
				fencedSendFrameIndex,
				'sent',
				'chat_turn_preflight',
				(payload) => payload.team_id === teamId
			);
			const fencedSend = await waitForFrame(
				frames,
				fencedSendFrameIndex,
				'sent',
				'chat_message_added',
				(payload) => payload.team_id === teamId
			);
			expect(fencedPreflight.payload.team_ai_invocation).toBeUndefined();
			expect(fencedPreflight.payload.inference_request?.team_ai_invocation).toBeUndefined();
			expect(fencedSend.payload.team_ai_invocation).toBeUndefined();
			expect(fencedPreflight.raw).not.toContain(fencedMention);
			expect(fencedSend.raw).not.toContain(fencedMention);
			const fencedMessageId = String(fencedPreflight.payload.message_id ?? '');
			expect(fencedMessageId).not.toBe('');
			await waitForFrame(
				frames,
				fencedSendFrameIndex,
				'received',
				'chat_message_confirmed',
				(payload) =>
					payload.chat_id === fencedSend.payload.chat_id && payload.message_id === fencedMessageId
			);
			// Confirmation follows the server's atomic encrypted-embed write. The
			// code reference must now be readable by this Team member using only
			// ciphertext and a scoped key wrapper.
			const fencedEmbeds = fencedSend.payload.encrypted_embeds as
				| Array<{ embed_id: string; encrypted_content: string }>
				| undefined;
			expect(fencedEmbeds).toHaveLength(1);
			const fencedEmbedId = fencedEmbeds![0].embed_id;
			expect(fencedEmbeds![0].encrypted_content).toBeTruthy();
			expect(JSON.stringify(fencedEmbeds)).not.toContain(fencedMention);
			const persistedEmbed = await page
				.context()
				.request.get(
					`${apiUrl}/v1/embeds/chats/${encodeURIComponent(String(fencedSend.payload.chat_id))}/embeds/${encodeURIComponent(fencedEmbedId)}?team_id=${encodeURIComponent(teamId)}`
				);
			expect(
				persistedEmbed.ok(),
				`Confirmed code embed was not readable (${persistedEmbed.status()}): ${await persistedEmbed.text()}`
			).toBe(true);
			const persistedEmbedBody = await persistedEmbed.json();
			expect(persistedEmbedBody.embed.embed_id).toBe(fencedEmbedId);
			expect(persistedEmbedBody.embed.encrypted_content).toBeTruthy();
			expect(persistedEmbedBody.embed_keys.length).toBeGreaterThan(0);
			expect(JSON.stringify(persistedEmbedBody)).not.toContain(fencedMention);
			// The composer keeps its send guard until draft cleanup finishes. Its
			// delete receipt follows the fenced WebSocket dispatch, unlike the
			// preview capability exchange, which precedes the preflight.
			await waitForFrame(
				frames,
				fencedSendFrameIndex,
				'sent',
				'delete_draft',
				(payload) => payload.chatId === fencedSend.payload.chat_id
			);
			await waitForFrame(
				frames,
				fencedSendFrameIndex,
				'received',
				'draft_delete_receipt',
				(payload) => payload.chat_id === fencedSend.payload.chat_id && payload.success === true
			);
			const fencedTeamMessage = page
				.getByTestId('message-user')
				.filter({ hasText: 'Literal code sample:' })
				.last();
			await expect(fencedTeamMessage).toBeVisible({ timeout: 30000 });
			await expect(fencedTeamMessage.getByText('Sending...')).not.toBeVisible({ timeout: 30000 });
			await expect(messageInput.getByTestId('stop-processing-button')).not.toBeVisible({
				timeout: 30000
			});
			await expect(editor).toHaveText('', { timeout: 30000 });
			await expect(editor.locator('[data-testid="embed-full-width-wrapper"]')).toHaveCount(0, {
				timeout: 30000
			});
			const embedProtocolDiagnostics = frames
				.slice(fencedSendFrameIndex)
				.filter((frame) => frame.type === 'request_embed' || frame.type === 'error')
				.map((frame) => ({
					direction: frame.direction,
					type: frame.type,
					status: frame.payload.status ?? null,
					errorCode: frame.payload.code ?? null,
					errorMessage: frame.type === 'error' ? (frame.payload.message ?? null) : null,
					refKind:
						typeof frame.payload.embed_id === 'string'
							? frame.payload.embed_id.startsWith('preview:')
								? 'preview'
								: 'canonical'
							: null,
					matchesCodeEmbed: frame.payload.embed_id === fencedEmbedId,
					chatMatches: frame.payload.chat_id === fencedSend.payload.chat_id,
					teamMatches: frame.payload.team_id === teamId
				}));
			expect(
				embedProtocolDiagnostics.filter(
					(event) =>
						event.direction === 'received' &&
						event.type === 'error' &&
						event.errorMessage === 'Embed not found'
				),
				`A code embed request failed after the fenced Team turn: ${JSON.stringify(embedProtocolDiagnostics)}`
			).toEqual([]);

			// A committed ordinary Team turn must survive losing its first preflight
			// acknowledgement. The browser may replay the exact packet or recover
			// the committed row through authoritative phased sync on reconnect.
			await page.evaluate((activeTeamId) => {
				const gate = (
					window as Window & { __teamPreflightAckDrop?: { arm: (teamId: string) => void } }
				).__teamPreflightAckDrop;
				if (!gate) throw new Error('Team preflight ACK drop fixture was not installed');
				gate.arm(activeTeamId);
			}, teamId);
			const lostAckFrameIndex = frames.length;
			await fillMessageEditor(page, editor, lostAckMessage);
			await messageInput
				.getByTestId('message-field')
				.locator('[data-action="send-message"]')
				.click();
			const lostAckPreflight = await waitForFrame(
				frames,
				lostAckFrameIndex,
				'sent',
				'chat_turn_preflight',
				(payload) => payload.team_id === teamId
			);
			const lostAckMessageId = String(lostAckPreflight.payload.message_id ?? '');
			expect(lostAckMessageId).not.toBe('');
			expect(lostAckPreflight.payload.inference_request?.team_ai_invocation).toBeUndefined();
			expect(lostAckPreflight.payload.encrypted_user_message?.encrypted_content).toBeTruthy();
			expect(lostAckPreflight.raw).not.toContain(lostAckMessage);
			const droppedAckFrame = await waitForFrame(
				frames,
				lostAckFrameIndex,
				'received',
				'chat_turn_preflight_ack',
				(payload) => payload.turn_id === lostAckPreflight.payload.turn_id
			);
			await expect
				.poll(
					() =>
						page.evaluate(() =>
							(
								window as Window & {
									__teamPreflightAckDrop?: {
										snapshot: () => { turnId: string | null; dropped: number };
									};
								}
							).__teamPreflightAckDrop?.snapshot()
						),
					{ timeout: 15000 }
				)
				.toEqual({
					turnId: lostAckPreflight.payload.turn_id,
					dropped: 1
				});
			await expect
				.poll(
					() => {
						const recoveredFrames = frames.slice(frames.indexOf(droppedAckFrame) + 1);
						if (
							recoveredFrames.filter(
								(frame) =>
									frame.direction === 'sent' &&
									frame.type === 'chat_turn_preflight' &&
									frame.payload.message_id === lostAckMessageId
							).length > 1
						)
							return 'retry';
						return recoveredFrames.some(
							(frame) =>
								frame.direction === 'received' &&
								frame.type === 'phased_sync_complete' &&
								frame.payload.team_id === teamId
						)
							? 'sync'
							: 'pending';
					},
					{ timeout: 120000 }
				)
				.not.toBe('pending');
			const preflightAttempts = frames
				.slice(lostAckFrameIndex)
				.filter(
					(frame) =>
						frame.direction === 'sent' &&
						frame.type === 'chat_turn_preflight' &&
						frame.payload.team_id === teamId
				);
			// WebSocket transport injects a fresh top-level tracing span on every
			// dispatch. Compare every other JSON field, including nested committed
			// trace, ciphertext, turn, scope, and inference request, byte for byte.
			const preflightWithoutTransportTrace = (frame: ProtocolFrame): string => {
				const payload = { ...frame.payload };
				delete payload._traceparent;
				return JSON.stringify({ type: frame.type, payload });
			};
			const committedPreflight = preflightWithoutTransportTrace(lostAckPreflight);
			expect(
				preflightAttempts.every(
					(frame) => preflightWithoutTransportTrace(frame) === committedPreflight
				)
			).toBe(true);
			const teamChatId = String(sentMessage.payload.chat_id ?? '');
			expect(teamChatId).not.toBe('');
			// The Team turn must be persisted under Team ownership, rather than
			// merely carrying a Team badge in the UI. Personal reads of this same
			// newly created chat are forbidden even for its human creator.
			const personalReadOfTeamChat = await page.request.get(
				`${apiUrl}/v1/chats/${encodeURIComponent(teamChatId)}/messages/window?limit=1`
			);
			expect(personalReadOfTeamChat.status()).toBe(404);
			expect(lostAckPreflight.payload.chat_id).toBe(teamChatId);
			await expect
				.poll(
					async () => {
						const response = await page.request.get(
							`${apiUrl}/v1/chats/${encodeURIComponent(teamChatId)}/messages/window?team_id=${encodeURIComponent(teamId)}&limit=100`
						);
						if (!response.ok()) return -1;
						const body = (await response.json()) as {
							messages?: Array<{ message_id?: string; client_message_id?: string }>;
						};
						return (body.messages ?? []).filter(
							(message) => (message.client_message_id ?? message.message_id) === lostAckMessageId
						).length;
					},
					{ timeout: 30000 }
				)
				.toBe(1);
			const lostAckTeamMessage = page
				.getByTestId('message-user')
				.filter({ hasText: lostAckMessage })
				.last();
			await expect(lostAckTeamMessage).toBeVisible({ timeout: 30000 });
			await expect(lostAckTeamMessage.getByText('Sending...')).not.toBeVisible({ timeout: 30000 });
			expect(
				frames
					.slice(lostAckFrameIndex)
					.filter(
						(frame) =>
							frame.direction === 'sent' &&
							frame.type === 'chat_message_added' &&
							frame.payload.message?.message_id === lostAckMessageId &&
							frame.payload.team_ai_invocation !== undefined
					)
			).toEqual([]);
			await page.waitForTimeout(6000);

			expect(fencedSend.payload.chat_id).toBe(teamChatId);
			await ensureSidebarOpen(page);
			const visibleTeamChat = page.locator(
				`[data-testid="chat-item-wrapper"][data-chat-id="${teamChatId}"]`
			);
			await expect(visibleTeamChat).toBeVisible({ timeout: 30000 });
			await expect(visibleTeamChat).toContainText('New team chat', { timeout: 15000 });
			await expect(visibleTeamChat).not.toContainText('Processing...', { timeout: 30000 });
			// Desktop history narrows the still-visible chat, so assert its floating
			// controls cannot overlap the message. Phone history is a full-screen
			// overlay; the covered chat geometry is intentionally out of view there.
			if ((page.viewportSize()?.width ?? 0) > 730) {
				// The responsive header places Details in More alongside Reminders.
				// Check that action in the open menu, then measure the closed toolbar.
				const moreButton = page.getByTestId('chat-top-actions').locator('button.more-trigger');
				await expect(moreButton).toBeVisible({ timeout: 15000 });
				await moreButton.click();
				await expect(moreButton).toHaveAttribute('aria-expanded', 'true');
				await expect(page.getByTestId('chat-details-button')).toBeVisible({ timeout: 15000 });
				await moreButton.click();
				await expect(moreButton).toHaveAttribute('aria-expanded', 'false');
				const userBubble = ordinaryTeamMessage.getByTestId('user-message-content');
				await expect(userBubble).toBeVisible();
				const [bubbleBox, controlBox] = await Promise.all([
					userBubble.boundingBox(),
					moreButton.boundingBox()
				]);
				expect(bubbleBox).not.toBeNull();
				expect(controlBox).not.toBeNull();
				const overlapsControl =
					bubbleBox!.x < controlBox!.x + controlBox!.width &&
					bubbleBox!.x + bubbleBox!.width > controlBox!.x &&
					bubbleBox!.y < controlBox!.y + controlBox!.height &&
					bubbleBox!.y + bubbleBox!.height > controlBox!.y;
				expect(overlapsControl).toBe(false);
			}
			for (const personalChatId of personalChatIds) {
				await expect(
					page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${personalChatId}"]`)
				).toHaveCount(0);
			}
			// Hold the uniquely titled Team row before switching contexts so the
			// visual proof cannot confuse it with an unrelated Personal "Untitled chat".
			await page.waitForTimeout(6000);
			await ensureSidebarClosed(page);

			await openProfileMenu(page);
			const personalSwitchFrameIndex = frames.length;
			await page.getByTestId('team-context-dropdown').click();
			await page.getByTestId('team-context-personal').click();
			await waitForPhasedSyncCompletion(frames, personalSwitchFrameIndex, null);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });
			await expect(page.locator('.active-chat-container')).not.toHaveClass(/dimmed/, {
				timeout: 15000
			});
			await expect(
				page.getByTestId('message-user').filter({ hasText: ordinaryMessage })
			).toHaveCount(0, { timeout: 15000 });
			// A fresh Personal chat intentionally has no header banner. Assert the
			// Team-specific banner is absent without requiring that banner to exist.
			await expect(page.getByTestId('chat-header-banner')).toHaveCount(0, { timeout: 15000 });
			await expect(page.getByTestId('profile-active-team-avatar')).toHaveCount(0, {
				timeout: 15000
			});

			await ensureSidebarOpen(page);
			const visiblePersonalChat = page.locator(
				`[data-testid="chat-item-wrapper"][data-chat-id="${personalChatIds[0]}"]`
			);
			await expect(visiblePersonalChat).toBeVisible({ timeout: 30000 });
			await expect(visiblePersonalChat).toContainText(personalDraftText);
			await expect(
				page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${teamChatId}"]`)
			).toHaveCount(0);
			// Keep the verified Personal-only list and clean Personal chat visible long enough for proof capture.
			await page.waitForTimeout(6000);

			const teamWindowResponsePromise = page.waitForResponse((response) => {
				if (!isApiPath(response, 'GET', `/v1/chats/${teamChatId}/messages/window`)) return false;
				const params = new URL(response.url()).searchParams;
				return params.get('team_id') === teamId && params.get('limit') === '1';
			});
			const teamLinkFrameIndex = frames.length;
			await page.goto(
				getE2EDebugUrl(
					`/#chat-id=${encodeURIComponent(teamChatId)}&team-id=${encodeURIComponent(teamId)}`
				),
				{ waitUntil: 'domcontentloaded' }
			);
			const teamWindowResponse = await teamWindowResponsePromise;
			expect(teamWindowResponse.ok(), 'Team link chat access check must succeed').toBe(true);
			await waitForPhasedSyncCompletion(frames, teamLinkFrameIndex, teamId);
			await expectProfileTeamBadge(page, teamName);
			await expect(page.getByTestId('active-chat-container')).toHaveAttribute(
				'data-current-chat-id',
				teamChatId,
				{ timeout: 30000 }
			);
			await expect(
				page.getByTestId('message-user').filter({ hasText: ordinaryMessage })
			).toBeVisible({ timeout: 30000 });
			await expect(
				page.getByTestId('message-user').filter({ hasText: lostAckMessage })
			).toBeVisible({ timeout: 30000 });
		} catch (error) {
			flowError = error;
		} finally {
			stopStartupCapture();
			try {
				await test.info().attach('sanitized-prelogin-browser-errors', {
					body: JSON.stringify({ errors: startupErrors }),
					contentType: 'application/json'
				});
			} catch (error) {
				cleanupError = error;
			}
			if (teamId) {
				try {
					const cleanupResponse = await page.request.delete(
						`${apiUrl}/v1/teams/${encodeURIComponent(teamId)}`
					);
					expect(cleanupResponse.ok(), `Team cleanup failed with ${cleanupResponse.status()}`).toBe(
						true
					);
				} catch (error) {
					cleanupError = cleanupError
						? new AggregateError([cleanupError, error], 'Diagnostic attachment and Team cleanup failed')
						: error;
				}
			}
		}
		if (flowError && cleanupError) {
			throw new AggregateError(
				[flowError, cleanupError],
				`Teams context flow failed before cleanup: ${String(flowError)}; cleanup also failed: ${String(cleanupError)}`
			);
		}
		if (flowError) throw flowError;
		if (cleanupError) throw cleanupError;
	});
});

async function waitForPhasedSyncCompletion(
	frames: ProtocolFrame[],
	startIndex: number,
	teamId: string | null
): Promise<ProtocolFrame> {
	const request = await waitForFrame(
		frames,
		startIndex,
		'sent',
		'phased_sync_request',
		(payload) => (payload.team_id ?? null) === teamId && Number.isInteger(payload.context_epoch)
	);
	await waitForFrame(
		frames,
		startIndex,
		'received',
		'phased_sync_complete',
		(payload) =>
			(payload.team_id ?? null) === teamId &&
			payload.phase === request.payload.phase &&
			payload.context_epoch === request.payload.context_epoch
	);
	return request;
}
