/* eslint-disable @typescript-eslint/no-require-imports, no-empty-pattern */
// proof-video: not_required reason=visual_smoke_not_needed (raw real-terminal recordings are attached per step)
/**
 * The native Rust terminal UI follows the same unread rules as the web app
 * (feature.chat-unread@1) on the disposable isolated backend:
 * - a finished reply counts once on the server and shows as "●1" on the TUI
 *   Continue card / sidebar row;
 * - opening the chat starts at the newest reply; closing it after reading only
 *   the first lines keeps it unread;
 * - answering (`chats send --chat`) implies the earlier reply was read, so the
 *   follow-up reply makes the counter exactly 1, never 2;
 * - paging until the reply's last line is on screen marks it read for every
 *   device.
 * Replies come from the committed `unread_long_reply` TEST_MOCK fixture; no
 * provider inference.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { buildRustCli, createRustHome, recordRust, runRust, rustEnv } = require('./helpers/rust-cli-terminal');

const { email, password, otpKey } = getTestAccount();
const CHAT_ID = /Chat: ([0-9a-f-]{36})/;
const FIXTURE = 'unread_long_reply';
const REPLY_START = 'Light enters a raindrop';
const LAST_LINE = 'UNREAD_LONG_REPLY_LAST_LINE';
const BADGE = '●1 How Rainbows';

type Run = { code: number | null; stdout: string; stderr: string };

test.describe('Native Rust TUI unread counter', () => {
	skipWithoutCredentials(test, email, password, otpKey);
	let binary = '';

	test.beforeAll(async ({}, testInfo: TestInfo) => {
		test.setTimeout(2_700_000);
		binary = buildRustCli(testInfo);
	});

	// contract-test: direct surface=cli assertions=chat-unread.reply.read-at-last-line,chat-unread.followup.implies-read,chat-unread.surfaces.sidebar-and-continue,chat-unread.persistence.cross-device
	test('keeps a partially read reply unread until its last line is shown', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(900_000);
		expect(process.env.E2E_USE_MOCKS, 'Committed fixture replies only; never paid inference').toBeTruthy();
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl);
		const env = { ...rustEnv(createRustHome('tui-unread'), apiUrl, baseUrl), CI: 'true', OPENMATES_CI_ISOLATED: '1' };
		const recordings: Array<{ dispose(): Promise<void> }> = [];
		const run = (args: string[], timeoutMs = 90_000): Promise<Run> => runRust(binary, env, args, timeoutMs);
		const record = (args: string[], label: string, options: Record<string, unknown> = {}) => {
			const handle = recordRust(binary, args, env, testInfo, label, options);
			recordings.push(handle);
			return handle;
		};
		const unreadCount = async (chatId: string): Promise<number | undefined> => {
			const listed = await run(['chats', 'list', '--json', '--limit', '50']);
			expect(listed.code, listed.stderr).toBe(0);
			const chats = (JSON.parse(listed.stdout).chats || []) as Array<{ id: string; fields?: { unread_count?: number } }>;
			const row = chats.find((chat) => chat.id === chatId);
			lastListedRow = row ? JSON.stringify({ id: row.id, fields: row.fields }) : 'chat not listed';
			return row?.fields?.unread_count;
		};
		let lastListedRow = '';
		const expectUnread = async (chatId: string, expected: number) => {
			try {
				await expect.poll(() => unreadCount(chatId), { timeout: 60_000, intervals: [2_000, 5_000] }).toBe(expected);
			} catch (error) {
				throw new Error(`${(error as Error).message}\nLast listed row: ${lastListedRow}`);
			}
		};
		let chatId = '';
		try {
			await loginToTestAccount(page);
			const login = record(['login'], 'login', { timeoutSeconds: 180 });
			const token = (await login.waitForOutput(/#pair=([A-Za-z0-9]+)/, 30_000))[1];
			await page.goto(`${baseUrl}/#pair=${token}`);
			await page.getByTestId('pair-allow-button').click({ timeout: 15_000 });
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
			await login.waitForOutput(/Pairing PIN from the browser:/, 30_000);
			login.typeText(pin);
			login.key('Return');
			const paired = await login.waitForExit(90_000);
			expect(paired.code, paired.output).toBe(0);

			const sent = await record(['chats', 'new', withMockMarker('Explain rainbows step by step', FIXTURE, 'instant')], 'new').waitForExit(150_000);
			expect(sent.code, sent.output).toBe(0);
			chatId = sent.output.match(CHAT_ID)?.[1] || '';
			expect(chatId, sent.output).toBeTruthy();
			// The server counts the finished reply once.
			await expectUnread(chatId, 1);

			// Open the chat, see only the start of the reply, close it again.
			const partial = record([], 'tui-partial', {
				timeoutSeconds: 180,
				steps: [
					{ name: 'unread-badge', wait_for: BADGE, wait_timeout_ms: 30_000, hold_ms: 1_200 },
					{ name: 'open-chat', key: 'Return', wait_for: REPLY_START, wait_for_absent: LAST_LINE, wait_timeout_ms: 30_000, hold_ms: 1_500 },
					{ name: 'exit-command', text: '/exit' },
					{ name: 'exit', key: 'Return' }
				]
			});
			const partialResult = await partial.waitForExit(180_000);
			expect(partialResult.code, partialResult.output.slice(-3000)).toBe(0);
			await expectUnread(chatId, 1);

			// Answering implies the earlier reply was read: the follow-up counts once.
			const followUp = await record(
				['chats', 'send', '--chat', chatId, withMockMarker('Now explain double rainbows step by step', FIXTURE, 'instant')],
				'follow-up'
			).waitForExit(150_000);
			expect(followUp.code, followUp.output).toBe(0);
			await expectUnread(chatId, 1);

			// Page down until the newest reply's last line is on screen: read.
			const read = record([], 'tui-read', {
				timeoutSeconds: 180,
				steps: [
					{ name: 'unread-badge', wait_for: BADGE, wait_timeout_ms: 30_000, hold_ms: 800 },
					{ name: 'open-chat', key: 'Return', wait_for: REPLY_START, wait_for_absent: LAST_LINE, wait_timeout_ms: 30_000, hold_ms: 800 },
					{ name: 'page-down', key: 'Page_Down', repeat: 16, hold_ms: 300 },
					{ name: 'page-to-end', key: 'Page_Down', repeat: 16, wait_for: LAST_LINE, wait_timeout_ms: 30_000, hold_ms: 1_500 },
					{ name: 'back', key: 'Escape', wait_for: 'How Rainbows', wait_for_absent: BADGE, wait_timeout_ms: 30_000, hold_ms: 1_200 },
					{ name: 'exit-command', text: '/exit' },
					{ name: 'exit', key: 'Return' }
				]
			});
			const readResult = await read.waitForExit(180_000);
			expect(readResult.code, readResult.output.slice(-3000)).toBe(0);
			// Persisted for every device.
			await expectUnread(chatId, 0);
		} finally {
			if (chatId) await run(['chats', 'delete', chatId, '--yes']);
			for (const recording of recordings) await recording.dispose();
		}
	});
});
