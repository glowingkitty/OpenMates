/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (raw real-terminal recordings are attached per step)
/**
 * Native Rust CLI/TUI essential core flows against the disposable isolated
 * backend with a fresh account. Replies come from committed TEST_MOCK fixtures
 * on the real API/AI worker (no provider calls); everything else is real:
 * browser-approved pair login, encrypted send/stream, cancel, follow-up,
 * saved reads from fresh processes, TUI open/send/stream and logout.
 *
 * The exact checked-out `openmates` binary is built with cargo --release
 * --locked (or taken from OPENMATES_RUST_CLI_BIN). Interactive steps run in a
 * real recorded PTY via scripts/cli_video_capture.py.
 */
export {};
import type { TestInfo } from '@playwright/test';

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, withMockMarker } = require('./signup-flow-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { buildRustCli, createRustHome, recordRust, runRust, rustEnv } = require('./helpers/rust-cli-terminal');
const fs = require('node:fs');

const { email, password, otpKey } = getTestAccount();
const CHAT_ID = /Chat: ([0-9a-f-]{36})/;

type Msg = { role: string; content: string };

function collectMessages(value: unknown, out: Msg[] = []): Msg[] {
	if (Array.isArray(value)) value.forEach((entry) => collectMessages(entry, out));
	else if (value && typeof value === 'object') {
		const record = value as Record<string, unknown>;
		if (typeof record.role === 'string' && typeof record.content === 'string') {
			out.push({ role: record.role, content: record.content });
		} else Object.values(record).forEach((entry) => collectMessages(entry, out));
	}
	return out;
}

function findById(value: unknown, id: string): Record<string, unknown> | null {
	if (Array.isArray(value)) {
		for (const entry of value) {
			const found = findById(entry, id);
			if (found) return found;
		}
	} else if (value && typeof value === 'object') {
		const record = value as Record<string, unknown>;
		if (record.id === id) return record;
		for (const entry of Object.values(record)) {
			const found = findById(entry, id);
			if (found) return found;
		}
	}
	return null;
}

function json(result: { code: number | null; stdout: string; stderr: string }, label: string): any {
	expect(result.code, `${label}\n${result.stderr}\n${result.stdout}`).toBe(0);
	return JSON.parse(result.stdout);
}

async function browserUserId(page: any, apiUrl: string): Promise<string> {
	return page.evaluate(async (endpoint: string) => {
		const sessionId = sessionStorage.getItem('session_id');
		if (!sessionId) throw new Error('Browser session ID is missing');
		const response = await fetch(`${endpoint}/v1/auth/session`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ session_id: sessionId })
		});
		const body = await response.json().catch(() => ({}));
		if (!response.ok || body.success !== true || !body.user?.id) throw new Error(`Browser session rejected: HTTP ${response.status}`);
		return String(body.user.id);
	}, apiUrl);
}

test.describe('Native Rust CLI/TUI core flows', () => {
	skipWithoutCredentials(test, email, password, otpKey);
	let binary = '';

	// eslint-disable-next-line no-empty-pattern -- Playwright requires a destructured fixture argument before testInfo.
	test.beforeAll(async ({}, testInfo: TestInfo) => {
		// Locked release compile of the exact source; never part of flow timings.
		test.setTimeout(2_700_000);
		binary = buildRustCli(testInfo);
	});

	// contract-test: direct surface=cli assertions=cli.runtime.native-rust,auth.pair-login.session-grant,auth.session.isolation,cli.credentials.storage-mode,chats.send.immediate-admission,chats.streaming.progressive-presentation,chats.completion.recovery-takeover,chats.message.identity-idempotent,chats.persistence.client-encrypted,cli.slugs.encrypted-stable,terminal-ui.native-shared-client
	test('pair login, whoami, chats list, send/stream, cancel, follow-up, show, restart, TUI and logout', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(900_000);
		expect(process.env.E2E_USE_MOCKS, 'Committed fixture replies only; never paid inference').toBeTruthy();
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl);
		const home = createRustHome('core');
		const env = rustEnv(home, apiUrl, baseUrl);
		const recordings: Array<{ dispose(): Promise<void> }> = [];
		const record = (args: string[], name: string, options: Record<string, unknown> = {}) => {
			const handle = recordRust(binary, args, env, testInfo, name, options);
			recordings.push(handle);
			return handle;
		};
		const cli = (args: string[], timeoutMs = 60_000) => runRust(binary, env, args, timeoutMs);
		const marked = (text: string, fixture: string, speed?: string) => {
			const value = withMockMarker(text, fixture, speed);
			expect(value).toContain('<<<TEST_MOCK:');
			return value;
		};
		try {
			// --- Unauthenticated state is explicit, never anonymous fallback. ---
			const before = await cli(['whoami', '--json']);
			expect(before.code).not.toBe(0);
			expect(before.stderr).toContain('authentication_required');

			// --- Pair login: Rust CLI in a real PTY, approved by the web app. ---
			await loginToTestAccount(page);
			const userId = await browserUserId(page, apiUrl);
			const login = record(['login'], 'login', { timeoutSeconds: 180 });
			const token = (await login.waitForOutput(/#pair=([A-Za-z0-9]+)/, 30_000))[1];
			await page.goto(`${baseUrl}/#pair=${token}`);
			const allow = page.getByTestId('pair-allow-button');
			await expect(allow).toBeVisible({ timeout: 15_000 });
			await allow.click();
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
			expect(pin).toMatch(/^[A-Z0-9]{6}$/);
			await login.waitForOutput(/Pairing PIN from the browser:/, 30_000);
			login.typeText(pin);
			login.key('Return');
			const loggedIn = await login.waitForExit(90_000);
			expect(loggedIn.code, loggedIn.output).toBe(0);
			expect(loggedIn.output).toContain('Logged in. Credential storage:');
			expect(loggedIn.output).not.toContain(pin);

			// --- Fresh processes reuse the persisted native session. ---
			const whoami = json(await cli(['whoami', '--json']), 'whoami');
			expect(String(whoami.id)).toBe(userId);
			json(await cli(['chats', 'list', '--json']), 'chats list (fresh account)');

			// --- New chat: send and stream the reply in a real terminal. ---
			// The display mention must reach the server as wire syntax.
			const first = 'Capital of Germany?';
			const send = record(['chats', 'new', marked(`@Gemini-3.8-Flash ${first}`, 'chat_flow_capital')], 'send-new-chat');
			const sent = await send.waitForExit(150_000);
			expect(sent.code, sent.output).toBe(0);
			expect(sent.output).toContain('Berlin');
			const chatId = sent.output.match(CHAT_ID)?.[1];
			expect(chatId, sent.output).toBeTruthy();

			// --- Cancel a second send while it streams: exit 130, no blind resend. ---
			const interrupted = 'Start a long explanation for interruption verification.';
			const cancel = record(['chats', 'send', '--chat', chatId!, marked(interrupted, 'chat_interrupt_followup', 'instant')], 'cancel-send', {
				timeoutSeconds: 120,
				steps: [
					{ name: 'partial', wait_for: 'This partial response must survive interruption.', wait_timeout_ms: 30_000, hold_ms: 400 },
					{ name: 'interrupt', key: 'ctrl+c', hold_ms: 200 }
				]
			});
			const cancelled = await cancel.waitForExit(120_000);
			expect(cancelled.code, cancelled.output).toBe(130);
			expect(cancelled.output).toContain('This partial response must survive interruption.');
			expect(cancelled.output).toContain('do not resend it blindly');
			expect(cancelled.output).not.toContain('Berlin');

			// Like the TS CLI, Ctrl+C stops the local command only; the server
			// turn keeps running and persists. Wait for it so the follow-up is a
			// fresh turn instead of being queued behind it.
			await expect
				.poll(
					async () => {
						const read = await cli(['chats', 'show', chatId!, '--json'], 90_000);
						if (read.code !== 0) return 0;
						const replies = collectMessages(JSON.parse(read.stdout)).filter((m) => m.role === 'assistant');
						return (replies.at(-1)?.content.match(/The remaining explanation has not finished yet\./g) ?? []).length;
					},
					{ timeout: 150_000, intervals: [5_000] }
				)
				.toBeGreaterThanOrEqual(30);

			// --- Follow-up in the same chat after the cancelled turn. ---
			const followUp = 'Hello, this is a test';
			const follow = record(['chats', 'send', '--chat', chatId!, marked(followUp, 'test_hello')], 'send-follow-up');
			const followed = await follow.waitForExit(150_000);
			expect(followed.code, followed.output).toBe(0);
			expect(followed.output).toContain('This is a mocked response from the fixture-based test system.');
			expect(followed.output.match(CHAT_ID)?.[1]).toBe(chatId);

			// --- Saved read from a fresh process: each turn exactly once, in order. ---
			const shown = json(await cli(['chats', 'show', chatId!, '--json'], 90_000), 'chats show');
			const messages = collectMessages(shown);
			const users = messages.filter((m) => m.role === 'user').map((m) => m.content);
			for (const text of [first, interrupted, followUp]) {
				expect(users.filter((content) => content.includes(text)), `user turn "${text}" in ${JSON.stringify(users)}`).toHaveLength(1);
			}
			const firstTurn = users.find((c) => c.includes(first))!;
			expect(firstTurn).toContain('@ai-model:gemini-3.8-flash');
			expect(firstTurn).not.toContain('@Gemini-3.8-Flash');
			expect(users.findIndex((c) => c.includes(first))).toBeLessThan(users.findIndex((c) => c.includes(interrupted)));
			expect(users.findIndex((c) => c.includes(interrupted))).toBeLessThan(users.findIndex((c) => c.includes(followUp)));
			const assistant = messages.filter((m) => m.role === 'assistant').map((m) => m.content).join('\n');
			expect(assistant).toContain('Berlin');
			expect(assistant).toContain('This partial response must survive interruption.');
			expect(assistant).toContain('This is a mocked response from the fixture-based test system.');
			const human = await cli(['chats', 'show', chatId!], 90_000);
			expect(human.code, human.stderr).toBe(0);
			expect(human.stdout).toContain('Berlin');

			const listed = json(await cli(['chats', 'list', '--json']), 'chats list');
			const listedChat = findById(listed, chatId!);
			expect(listedChat, JSON.stringify(listed).slice(0, 2000)).toBeTruthy();
			// Mock fixtures publish title metadata on every turn (real preprocessing
			// titles only the first message), so the decrypted title is one of the
			// fixture titles.
			const title = String(listedChat!.title);
			expect(['Capital of Germany', 'Kyoto and Osaka Weekend Plan', 'Test Greeting']).toContain(title);
			const titleMarker = title.slice(0, 16);

			// --- TUI: open the chat list, open the chat, send, watch it stream, quit. ---
			const tuiPrompt = 'Plan a weekend trip please';
			const tui = record([], 'tui', {
				timeoutSeconds: 180,
				steps: [
					{ name: 'landing', wait_for: titleMarker, wait_timeout_ms: 30_000, hold_ms: 600 },
					{ name: 'chats-command', text: '/chats' },
					{ name: 'chat-list', key: 'Return', wait_for: titleMarker, wait_timeout_ms: 20_000, hold_ms: 800 },
					{ name: 'open-chat', key: 'Return', wait_for: 'mocked response', wait_timeout_ms: 20_000, hold_ms: 800 },
					// The cached view paints first; sending waits for the current read.
					{ name: 'canonical', wait_for: 'Ask anything', wait_for_absent: 'Cached chat', wait_timeout_ms: 30_000, hold_ms: 300 },
					{ name: 'draft', text: marked(tuiPrompt, 'chat_flow_quick_tip'), hold_ms: 300 },
					{ name: 'streaming', key: 'Return', wait_for: 'Kyoto and Osaka quick tip test', wait_timeout_ms: 30_000, hold_ms: 300 },
					{ name: 'complete', wait_for: 'balance meals', wait_timeout_ms: 30_000, hold_ms: 1_000 },
					{ name: 'exit-command', text: '/exit' },
					{ name: 'exit', key: 'Return' }
				]
			});
			const tuiResult = await tui.waitForExit(180_000);
			expect(tuiResult.code, tuiResult.output.slice(-3000)).toBe(0);
			// The first chunk was visible before the final paragraph arrived.
			type Checkpoint = { name: string; at_ms: number; transcript_offset: number };
			const checkpoints = new Map<string, Checkpoint>((tuiResult.manifest.input_checkpoints || []).map((c: Checkpoint) => [c.name, c]));
			const checkpoint = (name: string) => {
				const value = checkpoints.get(name);
				if (!value) throw new Error(`Missing TUI checkpoint ${name}`);
				return value;
			};
			const at = (name: string) => checkpoint(name).at_ms;
			expect(at('complete')).toBeGreaterThan(at('streaming'));
			const transcript = fs.readFileSync(`${tui.outputDir}/transcript.txt`);
			const streamingScreen = transcript.subarray(0, checkpoint('streaming').transcript_offset).toString('utf8');
			expect(streamingScreen).toContain('Kyoto and Osaka quick tip test');
			expect(streamingScreen).not.toContain('balance meals');

			// --- Unknown mentions are refused before anything is sent. ---
			const unknown = await cli(['chats', 'send', '--chat', chatId!, '@Nonexistent-Model hello there']);
			expect(unknown.code, unknown.stderr + unknown.stdout).toBe(1);
			expect(unknown.stderr).toContain('Unknown mention @Nonexistent-Model');

			// --- Restart: a new process reads the TUI turn from encrypted history. ---
			const afterTui = collectMessages(json(await cli(['chats', 'show', chatId!, '--json'], 90_000), 'chats show after TUI'));
			expect(afterTui.filter((m) => m.role === 'user' && m.content.includes(tuiPrompt))).toHaveLength(1);
			expect(afterTui.filter((m) => m.role === 'user')).toHaveLength(4);
			expect(afterTui.some((m) => m.content.includes('Nonexistent-Model'))).toBe(false);

			// --- A second new chat with the identical first message gets its own slug. ---
			const again = json(
				await cli(['chats', 'new', marked(`@Gemini-3.8-Flash ${first}`, 'chat_flow_capital'), '--json'], 150_000),
				'chats new with an identical first message'
			);
			const againId = String(again.chatId ?? again.chat_id ?? '');
			expect(againId).toMatch(/^[0-9a-f-]{36}$/);
			expect(againId).not.toBe(chatId);
			expect(String(again.assistant ?? '')).toContain('Berlin');
			expect(afterTui.filter((m) => m.role === 'assistant').map((m) => m.content).join('\n')).toContain('balance meals, transit, and rest.');
			expect(String(json(await cli(['whoami', '--json']), 'whoami after TUI').id)).toBe(userId);

			// --- Logout clears the native session. ---
			const logout = await cli(['logout']);
			expect(logout.code, logout.stderr).toBe(0);
			const after = await cli(['whoami', '--json']);
			expect(after.code).not.toBe(0);
			expect(after.stderr).toContain('authentication_required');
		} finally {
			for (const recording of recordings) await recording.dispose();
			fs.rmSync(home, { recursive: true, force: true });
		}
	});
});
