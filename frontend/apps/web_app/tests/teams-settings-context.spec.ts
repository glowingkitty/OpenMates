/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Deployed Teams context and transport coverage.
 *
 * Verifies profile-menu context switching replaces Personal chats, scopes
 * phased sync and durable preflight to the selected Team, and sends ordinary
 * Team messages as ciphertext without an AI invocation.
 */
export {};

import type { Page, Response } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const {
	dismissSecurityReminderIfPresent,
	fillMessageEditor,
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

function deriveApiUrl(baseUrl: string): string {
	if (process.env.PLAYWRIGHT_TEST_API_URL) return process.env.PLAYWRIGHT_TEST_API_URL.replace(/\/$/, '');
	const url = new URL(baseUrl);
	if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
	if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return 'http://localhost:8000';
	throw new Error(`Cannot derive API URL from PLAYWRIGHT_TEST_BASE_URL=${baseUrl}.`);
}

function captureProtocol(page: Page, frames: ProtocolFrame[], apiUrl: string): void {
	const expectedApiHost = new URL(apiUrl).host;
	page.on('websocket', (websocket) => {
		if (new URL(websocket.url()).host !== expectedApiHost) return;
		const capture = (direction: ProtocolFrame['direction']) => (frame: { payload?: string | Buffer }) => {
			const raw = String(frame.payload ?? '');
			try {
				const parsed = JSON.parse(raw) as Record<string, any>;
				if (typeof parsed.type !== 'string' || typeof parsed.payload !== 'object' || !parsed.payload) return;
				frames.push({ direction, type: parsed.type, payload: parsed.payload, raw });
			} catch {
				// WebSocket control frames are not JSON protocol messages.
			}
		};
		websocket.on('framesent', capture('sent'));
		websocket.on('framereceived', capture('received'));
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
	await expect.poll(() => {
		match = frames.slice(startIndex).find((frame) =>
			frame.direction === direction && frame.type === type && predicate(frame.payload));
		return Boolean(match);
	}, { timeout: 30000 }).toBe(true);
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

async function visibleChatIds(page: Page): Promise<string[]> {
	return page.getByTestId('chat-item-wrapper').evaluateAll((rows) => rows
		.map((row) => row.getAttribute('data-chat-id'))
		.filter((chatId): chatId is string => Boolean(chatId)));
}

async function expectContinueCardsExcludeChatIds(page: Page, forbiddenChatIds: string[]): Promise<void> {
	const forbidden = new Set(forbiddenChatIds);
	await expect.poll(async () => {
		const visibleIds = await page.locator('[data-testid="recent-chats-scroll-container"] [data-chat-id]').evaluateAll((cards) => cards
			.map((card) => card.getAttribute('data-chat-id'))
			.filter((chatId): chatId is string => Boolean(chatId)));
		return visibleIds.filter((chatId) => forbidden.has(chatId));
	}, { timeout: 15000 }).toEqual([]);
}

async function expectContinueCardsEmpty(page: Page): Promise<void> {
	const cards = page.locator([
		'[data-testid="recent-chats-scroll-container"] [data-testid="continue-priority-card"]',
		'[data-testid="recent-chats-scroll-container"] [data-testid="resume-chat-large-card"]',
		'[data-testid="recent-chats-scroll-container"] [data-testid="resume-chat-card"]',
		'[data-testid="recent-chats-scroll-container"] [data-testid="resume-chat-draft-card"]',
	].join(', '));
	await expect(cards).toHaveCount(0, { timeout: 15000 });
}

async function openProfileMenu(page: Page): Promise<void> {
	await page.getByTestId('profile-container').click();
	await expect(page.getByTestId('settings-menu')).toBeVisible({ timeout: 15000 });
}

test.describe('Teams V1 context isolation', () => {
	// contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,teams.chat.encrypted-until-invoked
	test('isolates Team chats and sends ordinary Team turns as scoped ciphertext', async ({ page }: { page: Page }) => {
		test.setTimeout(180000);
		test.skip(!getTestAccount().email, 'Test account credentials required.');
		await skipIfFeaturesDisabled(test, page, ['platform:teams']);

		const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
		const frames: ProtocolFrame[] = [];
		const uniqueSuffix = `${Date.now()}-${test.info().workerIndex}`;
		const teamName = `E2E context team ${uniqueSuffix}`;
		const ordinaryMessage = 'Private Team note for context isolation';
		let teamId = '';
		captureProtocol(page, frames, apiUrl);

		try {
			await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
			await loginToTestAccount(page);
			await dismissSecurityReminderIfPresent(page);

			await ensureSidebarOpen(page);
			await expect(page.getByTestId('chat-item-wrapper').first()).toBeVisible({ timeout: 30000 });
			const personalChatIds = await visibleChatIds(page);
			expect(personalChatIds.length).toBeGreaterThan(0);
			await ensureSidebarClosed(page);

			await openProfileMenu(page);
			await page.getByTestId('settings-teams-item').click();
			await expect(page.getByTestId('teams-settings-page')).toBeVisible({ timeout: 30000 });

			const createResponsePromise = page.waitForResponse((response) =>
				isApiPath(response, 'POST', '/v1/teams') && response.ok());
			await page.getByTestId('team-name-input').fill(teamName);
			await page.getByTestId('team-description-input').fill(`Context isolation ${uniqueSuffix}`);
			await page.getByTestId('team-create-submit').click();
			const createResponse = await createResponsePromise;
			const createBody = await createResponse.json() as { team?: { team_id?: string } };
			teamId = createBody.team?.team_id ?? '';
			expect(teamId).not.toBe('');

			await page.getByTestId('banner-back-button').click();
			await page.getByTestId('banner-back-button').click();
			await expect(page.getByTestId('team-context-dropdown')).toBeVisible({ timeout: 30000 });
			const teamSwitchFrameIndex = frames.length;
			await page.getByTestId('team-context-dropdown').selectOption(teamId);
			await waitForPhasedSyncCompletion(frames, teamSwitchFrameIndex, teamId);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });
			await expect(page.locator('.active-chat-container')).not.toHaveClass(/dimmed/, { timeout: 15000 });
			await expect(page.getByTestId('profile-active-team-avatar')).toContainText(teamName, { timeout: 15000 });
			await openProfileMenu(page);
			await expect(page.getByTestId('team-context-dropdown')).toHaveValue(teamId, { timeout: 15000 });
			await page.waitForTimeout(6000);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });

			await ensureSidebarOpen(page);
			for (const personalChatId of personalChatIds) {
				await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${personalChatId}"]`)).toHaveCount(0);
			}
			await expectContinueCardsExcludeChatIds(page, personalChatIds);
			await expectContinueCardsEmpty(page);
			await page.waitForTimeout(6000);
			await ensureSidebarClosed(page);
			await startNewChat(page);
			await expect(page.getByTestId('profile-active-team-avatar')).toContainText(teamName, { timeout: 15000 });

			const sendFrameIndex = frames.length;
			const messageInput = page.locator('[data-action="message-input"]').last();
			const editor = messageInput.getByTestId('message-editor');
			await expect(editor).toBeVisible({ timeout: 30000 });
			await fillMessageEditor(page, editor, ordinaryMessage);
			await messageInput.getByTestId('message-field').locator('[data-action="send-message"]').click();

			const preflight = await waitForFrame(
				frames,
				sendFrameIndex,
				'sent',
				'chat_turn_preflight',
				() => true
			).catch(async (error: unknown) => {
				const clientDebug = await page.evaluate(() => ({
					send: (window as Window & { __openmatesLastSendDebug?: Record<string, unknown> })
						.__openmatesLastSendDebug ?? null,
					chatKeyGuard: (window as Window & { __openmatesLastChatKeyGuardDebug?: Record<string, unknown> })
						.__openmatesLastChatKeyGuardDebug ?? null,
				}));
				const observedFrames = frames.slice(sendFrameIndex).map(({ direction, type }) => ({ direction, type }));
				throw new Error(
					`Team preflight not observed. clientDebug=${JSON.stringify(clientDebug)} observedFrames=${JSON.stringify(observedFrames)} original=${String(error)}`
				);
			});
			const sentMessage = await waitForFrame(frames, sendFrameIndex, 'sent', 'chat_message_added', (payload) =>
				payload.team_id === teamId);
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
			const ordinaryTeamMessage = page.getByTestId('message-user').filter({ hasText: ordinaryMessage }).last();
			await expect(ordinaryTeamMessage).toBeVisible({ timeout: 15000 });
			await expect(ordinaryTeamMessage.getByText('Sending...')).not.toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('chat-header-banner')).not.toContainText('Creating new chat', { timeout: 15000 });
			await expect(page.getByTestId('chat-header-banner')).toContainText('New team chat', { timeout: 15000 });
			await page.waitForTimeout(6000);

			const teamChatId = String(sentMessage.payload.chat_id ?? '');
			expect(teamChatId).not.toBe('');

			await openProfileMenu(page);
			const personalSwitchFrameIndex = frames.length;
			await page.getByTestId('team-context-dropdown').selectOption('personal');
			await waitForPhasedSyncCompletion(frames, personalSwitchFrameIndex, null);
			await page.getByTestId('icon-button-close').click();
			await expect(page.getByTestId('settings-menu')).not.toBeVisible({ timeout: 15000 });
			await expect(page.locator('.active-chat-container')).not.toHaveClass(/dimmed/, { timeout: 15000 });
			await expect(page.getByTestId('message-user').filter({ hasText: ordinaryMessage })).toHaveCount(0, { timeout: 15000 });
			// A fresh Personal chat intentionally has no header banner. Assert the
			// Team-specific banner is absent without requiring that banner to exist.
			await expect(page.getByTestId('chat-header-banner')).toHaveCount(0, { timeout: 15000 });
			await expect(page.getByTestId('profile-active-team-avatar')).toHaveCount(0, { timeout: 15000 });

			await ensureSidebarOpen(page);
			const visiblePersonalChat = page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${personalChatIds[0]}"]`);
			await expect(visiblePersonalChat).toBeVisible({ timeout: 30000 });
			await expect(page.locator(`[data-testid="chat-item-wrapper"][data-chat-id="${teamChatId}"]`)).toHaveCount(0);
			// Keep the verified Personal-only list and clean Personal chat visible long enough for proof capture.
			await page.waitForTimeout(6000);
		} finally {
			if (teamId) {
				const cleanupResponse = await page.request.delete(`${apiUrl}/v1/teams/${encodeURIComponent(teamId)}`);
				expect(cleanupResponse.ok(), `Team cleanup failed with ${cleanupResponse.status()}`).toBe(true);
			}
		}
	});
});

async function waitForPhasedSyncCompletion(
	frames: ProtocolFrame[],
	startIndex: number,
	teamId: string | null
): Promise<ProtocolFrame> {
	const request = await waitForFrame(frames, startIndex, 'sent', 'phased_sync_request', (payload) =>
		(payload.team_id ?? null) === teamId && Number.isInteger(payload.context_epoch));
	await waitForFrame(frames, startIndex, 'received', 'phased_sync_complete', (payload) =>
		(payload.team_id ?? null) === teamId
		&& payload.phase === request.payload.phase
		&& payload.context_epoch === request.payload.context_epoch);
	return request;
}
