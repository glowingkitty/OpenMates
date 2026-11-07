/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — web chat-list ordering and grouping and the
 * active-chat URL plan on the shared Worker `chatState` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Also proves the message-list transitions (window prune, timeline merge/index), the
 * typing/processing indicator decisions and the private message bookmark toggle
 * (account settings decrypt, toggle, encrypt) are served by the unit.
 *
 * Engineering migration check (web lane: chatState). A logged-in account sends
 * one message (new chat), then alternating reloads render the sidebar on the
 * TypeScript sort/grouping (measurement opt-out `openmates_rust_core_chatstate=ts`)
 * and on the Rust unit. Every reload must show the chat just sent inside the
 * "today" group (the Rust arm decided that order and grouping through the
 * unit with zero failures, one shared Worker and no WASM on the page); the TS
 * arm must never load the adapter. Records reload -> sidebar-rendered latency per
 * arm (paired medians, approved not-noticeable budget, soft gate).
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage, deleteActiveChat, setChatSidebarOpen, startNewChat } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const CHATSTATE_OPT_OUT_KEY = 'openmates_rust_core_chatstate';
const PAIRS = Number(process.env.CHATSTATE_PAIRS || 12);

async function reloadAndRenderSidebar(page: any, chatId: string): Promise<number> {
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	const started = Date.now();
	await page.reload({ waitUntil: 'domcontentloaded' });
	await setChatSidebarOpen(page, true);
	const today = page.locator('[data-testid="chat-group"][data-group-key="today"]');
	await expect(today.first().getByTestId('chat-item').first()).toBeVisible({ timeout: 60000 });
	return Date.now() - started;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,sdk.web.before-after-performance
test('chat list ordering and grouping run on the shared Rust chatState unit and the sidebar renders the same chats', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(1500000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_CHATSTATE');
	const screenshot = createStepScreenshotter(log);
	const unitErrors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (/Rust (chat-list (sort|grouping)|selection plan|URL plan|unread update) failed|UnitPortError/.test(text)) unitErrors.push(text.slice(0, 300));
	});
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'chatstate-send');
	const chatIdOf = () => page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1] ?? null;
	await expect.poll(chatIdOf, { timeout: 30000 }).not.toBeNull();
	const chatId: string = chatIdOf()!;
	await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });

	const samples: Record<'ts' | 'rust', Record<string, unknown>[]> = { ts: [], rust: [] };
	try {
		for (let i = 0; i < PAIRS * 2; i++) {
			const path = i % 2 === 0 ? 'ts' : 'rust';
			await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
				[CHATSTATE_OPT_OUT_KEY, path === 'ts']);
			const renderMs = await reloadAndRenderSidebar(page, chatId);
			await expect(page.locator(`[data-testid="chat-group"][data-group-key="today"] [data-chat-id="${chatId}"]`).first(), `${path}: the chat just sent sits in the today group`).toBeVisible();
			const readStats = () => page.evaluate(() => (window as any).__openmatesRustChatStateStats?.() ?? null);
			if (path === 'rust') {
				await expect.poll(async () => (await readStats())?.calls ?? 0, { timeout: 45000 }).toBeGreaterThan(0);
			}
			const stats = await readStats();
			if (path === 'rust') {
				expect(stats.ops.sort ?? 0, 'Rust arm sorted the chat list through the unit').toBeGreaterThan(0);
				expect(stats.ops.group ?? 0, 'Rust arm grouped the chat list through the unit').toBeGreaterThan(0);
				for (const op of ['windowPrune', 'timelineMerge', 'timelineIndex', 'indicatorComposer', 'indicatorTitle']) {
					await expect.poll(async () => (await readStats())?.ops?.[op] ?? 0, { message: `Rust arm decided ${op} through the unit`, timeout: 30000 }).toBeGreaterThan(0);
				}
				expect((await readStats()).failures, 'no chatState unit call failed').toBe(0);
			} else {
				expect(stats, 'TS arm never loaded the Rust chatState adapter').toBeNull();
			}
			const instances = await rustCoreInstances(page);
			expect(instances.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
			expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, `${path}: one shared Rust core Worker`).toBe(1);
			samples[path].push({ renderMs, stats, ...instances });
		}
		// Private bookmark of the first reply: the unit reads the encrypted account settings, applies the
		// toggle and re-encrypts them (master-key crypto in the Worker); the page only posts the result.
		const reply = page.getByTestId('message-assistant').first();
		await reply.hover();
		const bookmark = reply.getByTestId('message-bookmark-button');
		await bookmark.click();
		await expect(bookmark, 'the bookmark is saved').toHaveAttribute('aria-pressed', 'true', { timeout: 30000 });
		await bookmark.click();
		await expect(bookmark, 'the bookmark is removed again').toHaveAttribute('aria-pressed', 'false', { timeout: 30000 });
		const bookmarkStats = await page.evaluate(() => (window as any).__openmatesRustChatStateStats?.() ?? null);
		for (const op of ['bookmarkIdentity', 'bookmarkReadAccount', 'bookmarkToggleAccount']) {
			expect(bookmarkStats.ops[op] ?? 0, `Rust arm decided ${op} through the unit`).toBeGreaterThan(0);
		}
		expect(bookmarkStats.failures, 'no chatState unit call failed during the bookmark toggles').toBe(0);
		// Leaving the chat clears the active selection: the URL update is planned by the Rust unit.
		await startNewChat(page);
		await expect.poll(async () => (await page.evaluate(() => (window as any).__openmatesRustChatStateStats?.() ?? null))?.ops?.selectionUrlPlan ?? 0,
			{ message: 'Rust arm planned the active-chat URL update through the unit', timeout: 20000 }).toBeGreaterThan(0);
		await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
		expect(unitErrors, 'no chatState unit errors in either arm').toEqual([]);
	} finally {
		await page.evaluate((key: string) => localStorage.removeItem(key), CHATSTATE_OPT_OUT_KEY);
		await deleteActiveChat(page, log, screenshot, 'chatstate-cleanup');
	}
	const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
	const rust = median(samples.rust.map((row) => Number(row.renderMs)));
	const ts = median(samples.ts.map((row) => Number(row.renderMs)));
	const limit = Math.max(ts * 1.1, ts + 50);
	const metrics = { pairs: PAIRS, rustMedianMs: rust, tsMedianMs: ts, verdict: rust <= limit ? 'rust_not_worse' : 'rust_worse', samples };
	console.log(`[web-rust-core-chatstate] ${JSON.stringify({ rustMedianMs: rust, tsMedianMs: ts, verdict: metrics.verdict })}`);
	await testInfo.attach('chatstate-reload-latency.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	expect.soft(rust, `reload-to-rendered sidebar: Rust ${rust} ms vs TS ${ts} ms`).toBeLessThanOrEqual(limit);
});
