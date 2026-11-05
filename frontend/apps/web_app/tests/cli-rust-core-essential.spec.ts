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
const { deriveApiUrl, runCli } = require('./helpers/cli-test-helpers');
const { createWorkflowCliHome, removeWorkflowCliHome, spawnCliLogin, workflowCliEnv } = require('./helpers/workflow-cli-e2e-helpers');
const { buildRustCli, createRustHome, recordRust, runRust, rustEnv } = require('./helpers/rust-cli-terminal');
const fs = require('node:fs');

const { email, password, otpKey } = getTestAccount();
const CHAT_ID = /Chat: ([0-9a-f-]{36})/;

type Msg = { role: string; content: string; id?: string };

function collectMessages(value: unknown, out: Msg[] = []): Msg[] {
	if (Array.isArray(value)) value.forEach((entry) => collectMessages(entry, out));
	else if (value && typeof value === 'object') {
		const record = value as Record<string, unknown>;
		if (typeof record.role === 'string' && typeof record.content === 'string') {
			out.push({ role: record.role, content: record.content, id: typeof record.id === 'string' ? record.id : undefined });
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
					// The cached view paints first; sending waits for the current read. An
					// opened chat shows the follow-up composer placeholder.
					{ name: 'canonical', wait_for: 'Ask a follow-up', wait_for_absent: 'Cached chat', wait_timeout_ms: 30_000, hold_ms: 300 },
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

			// --- Saved-chat history edits and chat media (npm parity). ---
			// files: decrypted embed file references; the fixture chats have none.
			const files = json(await cli(['chats', 'files', chatId!, '--json'], 90_000), 'chats files');
			expect(files.chat_id).toBe(chatId);
			expect(files.source).toBe('chat');
			expect(Array.isArray(files.files) && files.count === files.files.length).toBe(true);
			// open: signed-in position 1 resolves the most recent chat to a web URL.
			const opened = json(await cli(['chats', 'open', '1', '--json']), 'chats open');
			expect(String(opened.url)).toContain('/#chat-id=');
			expect(opened.position).toBe(1);
			// fork: copy the first exchange plus the interrupted user turn into a
			// new client-encrypted chat.
			const cut = afterTui.find((m) => m.role === 'user' && m.content.includes(interrupted));
			expect(cut?.id, JSON.stringify(afterTui.map((m) => [m.role, m.id]))).toBeTruthy();
			const fork = record(['chats', 'fork', chatId!, '--from-message', cut!.id!, '--title', 'Fork proof'], 'chats-fork');
			const forked = await fork.waitForExit(90_000);
			expect(forked.code, forked.output).toBe(0);
			const forkMatch = forked.output.match(/Forked chat ([0-9a-f-]{36}) \((\d+) messages copied\)/);
			expect(forkMatch, forked.output).toBeTruthy();
			const forkId = forkMatch![1];
			expect(forkId).not.toBe(chatId);
			expect(Number(forkMatch![2])).toBe(3);
			const forkMessages = collectMessages(json(await cli(['chats', 'show', forkId, '--json'], 90_000), 'show fork'));
			expect(forkMessages.map((m) => m.role)).toEqual(['user', 'assistant', 'user']);
			expect(forkMessages[1].content).toContain('Berlin');
			expect(forkMessages[2].content).toContain(interrupted);
			// retry (no --yes) is a dry run that plans to delete the trailing user turn.
			const retryPlan = json(await cli(['chats', 'retry', forkId, '--json'], 90_000), 'chats retry dry run');
			expect(retryPlan.dry_run).toBe(true);
			expect(retryPlan.planned_deleted_message_count).toBe(1);
			// rewind without --yes is a dry run that changes nothing.
			const dry = record(['chats', 'rewind', forkId, '--to-message', forkMessages[1].id!], 'chats-rewind-dry-run');
			const dried = await dry.waitForExit(90_000);
			expect(dried.code, dried.output).toBe(0);
			expect(dried.output).toContain(`Dry run chat ${forkId}`);
			expect(dried.output).toContain('Would delete 1 message.');
			expect(dried.output).toContain('Run again with --yes to apply this rewind.');
			expect(collectMessages(json(await cli(['chats', 'show', forkId, '--json'], 90_000), 'fork after dry run'))).toHaveLength(3);
			// --- Paired timing: native Rust vs the npm CLI on the same chat. ---
			// The npm arm pairs its own session; each command gets one untimed
			// warmup per arm, then the median of three alternating samples.
			const npmHome = createWorkflowCliHome('rust-parity-npm');
			try {
				const npmLogin = spawnCliLogin(apiUrl, npmHome);
				const npmToken = await npmLogin.waitForToken();
				await page.goto(`${baseUrl}/#pair=${npmToken}`);
				await page.getByTestId('pair-allow-button').click({ timeout: 15_000 });
				const npmPinDisplay = page.getByTestId('pair-pin-display');
				await expect(npmPinDisplay).toBeVisible({ timeout: 15_000 });
				await npmLogin.waitForPinPrompt();
				npmLogin.sendPin(((await npmPinDisplay.textContent()) || '').replace(/\s/g, '').trim());
				expect((await npmLogin.waitForExit()).code).toBe(0);
				const npmEnv = workflowCliEnv(apiUrl, npmHome);
				const timeRust = async (args: string[]) => {
					const started = performance.now();
					const result = await cli(args, 120_000);
					expect(result.code, `rust ${args.join(' ')}\n${result.stderr}`).toBe(0);
					return performance.now() - started;
				};
				const timeNpm = async (args: string[]) => {
					const result = await runCli(apiUrl, args, 120_000, { useApiKey: false, record: false, env: npmEnv });
					expect(result.code, `npm ${args.join(' ')}\n${result.stderr}`).toBe(0);
					return result.durationMs as number;
				};
				const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
				const timings: Record<string, { rust_ms: number; npm_ms: number }> = {};
				for (const [label, args] of [
					['chats files', ['chats', 'files', forkId, '--json']],
					['chats open', ['chats', 'open', '1', '--json']],
					['chats retry (dry run)', ['chats', 'retry', forkId, '--json']],
					['chats rewind (dry run)', ['chats', 'rewind', forkId, '--to-message', forkMessages[1].id!, '--json']]
				] as Array<[string, string[]]>) {
					await timeRust(args);
					await timeNpm(args);
					const rust: number[] = [];
					const npm: number[] = [];
					for (let sample = 0; sample < 3; sample++) {
						rust.push(await timeRust(args));
						npm.push(await timeNpm(args));
					}
					timings[label] = { rust_ms: Math.round(median(rust)), npm_ms: Math.round(median(npm)) };
				}
				const forkArgs = ['chats', 'fork', chatId!, '--from-message', cut!.id!, '--title', 'Timing fork', '--json'];
				timings['chats fork'] = { rust_ms: Math.round(await timeRust(forkArgs)), npm_ms: Math.round(await timeNpm(forkArgs)) };
				console.log(`[rust-vs-npm] ${JSON.stringify(timings)}`);
				await testInfo.attach('rust-vs-npm-timings.json', { body: JSON.stringify(timings, null, 2), contentType: 'application/json' });
				for (const [label, timing] of Object.entries(timings)) {
					expect(timing.rust_ms, `${label}: rust ${timing.rust_ms}ms vs npm ${timing.npm_ms}ms`).toBeLessThanOrEqual(timing.npm_ms);
				}
			} finally {
				removeWorkflowCliHome(npmHome);
			}

			// rewind --yes to the first turn deletes the rest; retry then refuses.
			const rewound = json(await cli(['chats', 'rewind', forkId, '--to-message', forkMessages[0].id!, '--yes', '--json'], 90_000), 'chats rewind');
			expect(rewound.deleted_message_count).toBe(2);
			const afterRewind = collectMessages(json(await cli(['chats', 'show', forkId, '--json'], 90_000), 'show rewound fork'));
			expect(afterRewind.map((m) => m.role)).toEqual(['user']);
			const refused = await cli(['chats', 'retry', forkId, '--json'], 90_000);
			expect(refused.code, refused.stdout).toBe(1);
			expect(refused.stderr).toContain('Cannot retry a chat whose first message is the failed user turn.');
			// The source chat is untouched by fork/rewind of its copy.
			expect(collectMessages(json(await cli(['chats', 'show', chatId!, '--json'], 90_000), 'source after fork')).filter((m) => m.role === 'user')).toHaveLength(4);

			// --- Work-recovery projection commands (npm parity). ---
			const recoveryHelp = await cli(['recovery']);
			expect(recoveryHelp.code, recoveryHelp.stderr).toBe(0);
			expect(recoveryHelp.stdout).toContain('Usage: openmates recovery full-sync --project <project-id> --root <external-root>');
			const missing = await cli(['recovery', 'validate', '--file', `${home}/absent.yml`]);
			expect(missing.code).toBe(1);
			expect(missing.stderr).toContain(`Recovery projection does not exist: ${home}/absent.yml`);

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
