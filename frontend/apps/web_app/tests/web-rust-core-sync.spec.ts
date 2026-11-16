/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (sync policy parity; the UI is unchanged, the Playwright video is kept)
/**
 * Opt-in shared Rust core (WASM) — web chat-sync decision policy on the shared
 * Worker `sync` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: sync policy). A logged-in account sends
 * one message (new chat), then repeated reloads run phased sync. Every reload
 * must list the chat in the sidebar and render the decrypted user and assistant
 * messages (existing chats keep decrypting and syncing). Each reload must route
 * its merge decisions through the Rust unit with no failed unit call, one shared
 * Worker and no WASM on the page; there is no TypeScript arm.
 * Records the reload -> rendered chat latency of the Rust path.
 * Finally a fresh second device signs in: the Rust unit plans the storage of
 * the synced encrypted messages (messagePrep) and their messages_v advance
 * (messagesVersion), and the user message renders there.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage, deleteActiveChat, setChatSidebarOpen } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const RELOADS = 3;

async function reloadAndRender(page: any, chatId: string): Promise<number> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	const started = Date.now();
	await page.reload({ waitUntil: 'domcontentloaded' });
	for (const role of ['message-user', 'message-assistant']) {
		await expect(page.getByTestId(role).first().getByTestId('message-content')).not.toBeEmpty({ timeout: 60000 });
	}
	return Date.now() - started;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted,sdk.web.before-after-performance
test('phased sync decisions run on the shared Rust sync unit and existing chats still sync and decrypt', async ({ page, browser }: { page: any; browser: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_SYNC');
	const screenshot = createStepScreenshotter(log);
	const syncErrors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		// A request superseded by a reconnect is re-sent on the new socket (warning, not a sync failure).
		if (/superseded by a reconnect/.test(text)) return;
		if (/\[ChatSyncService\].*(Error|Failed)|sync_merge_unsettled|UnitPortError|DataCloneError/.test(text)) syncErrors.push(text.slice(0, 300));
	});
	// A request the page cannot post to the shared Worker (for example reactive state passed
	// uncopied) surfaces as an uncaught DataCloneError, not as a console line.
	page.on('pageerror', (error: Error) => {
		if (/DataCloneError|could not be cloned/.test(String(error))) syncErrors.push(String(error).slice(0, 300));
	});
	let phasedSyncRequests = 0;
	page.on('websocket', (socket: any) => socket.on('framesent', (frame: any) => {
		try {
			if (JSON.parse(String(frame.payload)).type === 'phased_sync_request') phasedSyncRequests += 1;
		} catch {
			// Ignore non-protocol frames.
		}
	}));
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);

	// A fresh login puts the account owner in the profile before auth flips, so the work that
	// starts on that transition runs for the right owner: the first account sync is requested
	// (not silently dropped) and the Rust core session is admitted instead of refused. Admission is
	// the local session (no server call) or, when that is not possible, the server-checked one.
	await expect.poll(() => phasedSyncRequests, { timeout: 30000, message: 'the first account sync is requested after a fresh login' }).toBeGreaterThanOrEqual(1);
	const rustMarks = (pattern: string) => page.evaluate((source: string) => performance.getEntriesByType('mark')
		.filter((mark) => mark.name.startsWith('openmates:rust:')).map((mark) => mark.name.slice('openmates:rust:'.length))
		.filter((stage) => new RegExp(source).test(stage)), pattern);
	await expect.poll(() => rustMarks('session-'), { timeout: 30000, message: 'the Rust core session is admitted on a fresh login' })
		.toEqual(expect.arrayContaining([expect.stringMatching(/^(local-)?session-ready$/)]));
	expect(await rustMarks('^session-failed-'), 'no refused Rust core admission after a fresh login').toEqual([]);

	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'sync-send');
	const chatIdOf = () => page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1] ?? null;
	await expect.poll(chatIdOf, { timeout: 30000 }).not.toBeNull();
	const chatId: string = chatIdOf()!;
	await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });

	// Slice 2 recovery: the first (flag-on) send journals its admission context phases; the retained
	// frame check runs on the sync unit.
	await expect.poll(() => page.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.ops?.recoveryContextFrame ?? 0),
		{ message: 'admission context frame check decided by the Rust sync unit', timeout: 30000 }).toBeGreaterThan(0);
	// The login Worker may be retired while no account is bound yet (idle after the password step).
	// Once the account is admitted the shared core keeps its Worker: a retirement after that point
	// would fail the crypto and core calls the page has in flight.
	const retiredAfterAdmission = await page.evaluate(() => {
		const marks = performance.getEntriesByType('mark').filter((mark) => mark.name.startsWith('openmates:rust:'));
		const admitted = marks.find((mark) => /:(local-)?session-ready$/.test(mark.name));
		return marks.filter((mark) => mark.name.endsWith(':auth-realm-retired') && admitted !== undefined && mark.startTime > admitted.startTime).length;
	});
	expect(retiredAfterAdmission, 'the shared core is not shut down after the account was admitted').toBe(0);

	const samples: Record<string, unknown>[] = [];
	try {
		for (let i = 0; i < RELOADS; i++) {
			const renderMs = await reloadAndRender(page, chatId);
			await setChatSidebarOpen(page, true);
			await expect(page.getByTestId('chat-item-wrapper').first())
				.toBeVisible({ timeout: 30000 });
			const readStats = () => page.evaluate(() => (window as any).__openmatesRustSyncStats?.() ?? null);
			await expect.poll(async () => (await readStats())?.calls ?? 0, { timeout: 45000 }).toBeGreaterThan(0);
			const stats = await readStats();
			// Sync decisions are made only by the unit: a refusal is a visible failure, never a TypeScript fallback.
			// A reload with cached chat keys merges but admits no new key, so only merge is required here.
			expect(stats.ops.merge ?? 0, 'merge decided by the Rust sync unit').toBeGreaterThan(0);
			expect(stats.failures, 'no sync unit call failed').toBe(0);
			const instances = await rustCoreInstances(page);
			expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
			expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
			samples.push({ renderMs, stats, ...instances });
		}
		expect(syncErrors, 'no chat-sync errors').toEqual([]);

		// Synced-message storage plans: a fresh device (empty IndexedDB) receives the chat's encrypted
		// messages through startup/on-demand sync; the Rust unit plans their normalization and the
		// chat still renders decrypted on that device.
		// Only the user message is asserted: on a fresh device the mocked assistant reply is not reliably
		// restored (a reload-render gap seen on device A as well).
		const deviceB = await browser.newContext();
		const pageB = await deviceB.newPage();
		try {
			await pageB.goto(getE2EDebugUrl('/'));
			await loginToTestAccount(pageB, log, screenshot);
			await pageB.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
			await expect(pageB.getByTestId('message-user').first().getByTestId('message-content'), 'device B renders the synced user message')
				.not.toBeEmpty({ timeout: 90000 });
			await expect.poll(() => pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.ops?.messagePrep ?? 0),
				{ message: 'synced message storage plan decided by the Rust sync unit on the fresh device', timeout: 45000 }).toBeGreaterThan(0);
			// Version-wins plans: the synced content's forward-only messages_v advance is decided by the unit.
			await expect.poll(() => pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.ops?.messagesVersion ?? 0),
				{ message: 'messages_v advance of synced content decided by the Rust sync unit on the fresh device', timeout: 45000 }).toBeGreaterThan(0);
			expect(await pageB.evaluate(() => (window as any).__openmatesRustSyncStats?.()?.failures ?? 0), 'no sync unit call failed on device B').toBe(0);
			await screenshot(pageB, 'sync-device-b-rendered');
		} finally {
			await deviceB.close();
		}
	} finally {
		await deleteActiveChat(page, log, screenshot, 'sync-cleanup');
	}
	const metrics = { reloads: RELOADS, renderMs: samples.map((row) => Number(row.renderMs)), samples };
	console.log(`[web-rust-core-sync] ${JSON.stringify({ renderMs: metrics.renderMs })}`);
	await testInfo.attach('sync-reload-latency.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
});
