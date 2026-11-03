/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (raw real-terminal recordings are attached per step)
/**
 * Two native Rust CLI devices on one fresh-account session pair stay in sync
 * through the incremental chat sync feed (architecture.sync@2) on the
 * disposable isolated backend. Device A creates and deletes chats, the web
 * session schedules a reminder for one chat; device B's warm `chats list`
 * replays only the feed changes (diagnostic branch `feed_hit`, no phase=all),
 * drops the deleted chat and shows the due-soon chat first. Replies come from
 * committed TEST_MOCK fixtures; no provider inference.
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

type Run = { code: number | null; stdout: string; stderr: string };

function listIds(result: Run, label: string): string[] {
	expect(result.code, `${label}\n${result.stderr}\n${result.stdout}`).toBe(0);
	return (JSON.parse(result.stdout).chats as Array<{ id: string }>).map((chat) => chat.id);
}

/** The opt-in isolated-CI list diagnostic names the branch that served the list. */
function listBranch(result: Run): string | undefined {
	for (const line of result.stderr.split('\n')) {
		if (!line.includes('native-list-stages-v1')) continue;
		try {
			return JSON.parse(line).branch;
		} catch {
			return undefined;
		}
	}
	return undefined;
}

test.describe('Native Rust CLI chat sync feed', () => {
	skipWithoutCredentials(test, email, password, otpKey);
	let binary = '';

	// eslint-disable-next-line no-empty-pattern -- Playwright requires a destructured fixture argument before testInfo.
	test.beforeAll(async ({}, testInfo: TestInfo) => {
		test.setTimeout(2_700_000);
		binary = buildRustCli(testInfo);
	});

	// contract-test: direct surface=cli assertions=sync.delta.cursor-gap-free,sync.delta.metadata-only,sync.deletion.partial-window-not-authoritative,sync.overview.priority-order,sync.overview.cross-device,sync.startup.bounded-phases
	test('a second device replays deletes and due-soon order through the feed', async ({ page }: { page: any }, testInfo: TestInfo) => {
		test.setTimeout(900_000);
		expect(process.env.E2E_USE_MOCKS, 'Committed fixture replies only; never paid inference').toBeTruthy();
		const baseUrl = process.env.PLAYWRIGHT_TEST_BASE_URL || '';
		const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || deriveApiUrl(baseUrl);
		const recordings: Array<{ dispose(): Promise<void> }> = [];
		const device = (name: string) => {
			const env = {
				...rustEnv(createRustHome(`feed-${name}`), apiUrl, baseUrl),
				CI: 'true',
				OPENMATES_CI_ISOLATED: '1',
				OPENMATES_CI_LIST_STAGE_DIAGNOSTIC: '1'
			};
			return {
				env,
				run: (args: string[], timeoutMs = 90_000): Promise<Run> => runRust(binary, env, args, timeoutMs),
				record: (args: string[], label: string, options: Record<string, unknown> = {}) => {
					const handle = recordRust(binary, args, env, testInfo, `${name}-${label}`, options);
					recordings.push(handle);
					return handle;
				}
			};
		};
		const pairLogin = async (cli: ReturnType<typeof device>) => {
			const login = cli.record(['login'], 'login', { timeoutSeconds: 180 });
			const token = (await login.waitForOutput(/#pair=([A-Za-z0-9]+)/, 30_000))[1];
			await page.goto(`${baseUrl}/#pair=${token}`);
			const allow = page.getByTestId('pair-allow-button');
			await expect(allow).toBeVisible({ timeout: 15_000 });
			await allow.click();
			const pinDisplay = page.getByTestId('pair-pin-display');
			await expect(pinDisplay).toBeVisible({ timeout: 15_000 });
			const pin = ((await pinDisplay.textContent()) || '').replace(/\s/g, '');
			await login.waitForOutput(/Pairing PIN from the browser:/, 30_000);
			login.typeText(pin);
			login.key('Return');
			const done = await login.waitForExit(90_000);
			expect(done.code, done.output).toBe(0);
		};
		const newChat = async (cli: ReturnType<typeof device>, label: string) => {
			const prompt = withMockMarker(`@Gemini-3.8-Flash Feed sync check ${label}`, 'chat_flow_capital');
			expect(prompt).toContain('<<<TEST_MOCK:');
			const sent = await cli.record(['chats', 'new', prompt], `new-${label}`).waitForExit(150_000);
			expect(sent.code, sent.output).toBe(0);
			const id = sent.output.match(CHAT_ID)?.[1];
			expect(id, sent.output).toBeTruthy();
			return id as string;
		};
		try {
			await loginToTestAccount(page);
			const deviceA = device('a');
			const deviceB = device('b');
			await pairLogin(deviceA);
			await pairLogin(deviceB);

			const kept = await newChat(deviceA, 'kept');
			const removed = await newChat(deviceA, 'removed');

			// Device B cold start: bounded sync that also returns the feed cursor.
			const cold = await deviceB.run(['chats', 'list', '--json', '--limit', '50']);
			const coldIds = listIds(cold, 'cold chats list');
			expect(coldIds).toEqual(expect.arrayContaining([kept, removed]));
			// Login may already have cold-started; either way a cursor now exists.
			expect(['foreground', 'feed_hit']).toContain(listBranch(cold));

			// Device A deletes one chat; the web session schedules a reminder
			// for the other chat two hours from now (due soon).
			const deleted = await deviceA.run(['chats', 'delete', removed, '--yes']);
			expect(deleted.code, deleted.stderr).toBe(0);
			const reminder = await page.request.post(`${apiUrl}/v1/apps/reminder/skills/set-reminder`, {
				data: {
					prompt: 'Feed sync due-soon check', trigger_type: 'specific', timezone: 'UTC',
					trigger_datetime: new Date(Date.now() + 2 * 3600 * 1000).toISOString(),
					target_type: 'existing_chat', chat_id: kept, response_type: 'simple'
				}
			});
			expect(reminder.ok(), await reminder.text()).toBe(true);
			const reminderId = ((await reminder.json()).data || {}).reminder_id;

			// Device B warm start: one feed catch-up from its cursor.
			await expect
				.poll(async () => {
					const warm = await deviceB.run(['chats', 'list', '--json', '--limit', '50']);
					const ids = listIds(warm, 'warm chats list');
					return { branch: listBranch(warm), first: ids[0], removedPresent: ids.includes(removed) };
				}, { timeout: 60_000, intervals: [2_000, 5_000] })
				.toEqual({ branch: 'feed_hit', first: kept, removedPresent: false });

			// A chat with an encrypted title keeps that title through the feed sync:
			// device B's feed-hit list shows the same title device A sees.
			const titleOf = async (cli: ReturnType<typeof device>) => {
				const out = await cli.run(['chats', 'list', '--json', '--limit', '50']);
				const chats = (JSON.parse(out.stdout).chats || []) as Array<{ id: string; title: string | null }>;
				return chats.find((chat) => chat.id === kept)?.title ?? null;
			};
			await expect
				.poll(async () => {
					const [a, b] = [await titleOf(deviceA), await titleOf(deviceB)];
					return a !== null && a !== '' && b === a;
				}, { timeout: 90_000, intervals: [3_000, 5_000] })
				.toBe(true);

			if (reminderId) {
				const cancelled = await page.request.delete(`${apiUrl}/v1/settings/reminders/${reminderId}`);
				expect(cancelled.ok()).toBe(true);
			}
		} finally {
			for (const recording of recordings) await recording.dispose();
		}
	});
});
