/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — sidebar chat search on the shared Worker's
 * `search` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: search). A code embed chat is seeded
 * through the normal send (CI mock replay). After a reload the sidebar search
 * must find the seeded chat's message by a word of its content, served by the
 * Rust search unit inside the one shared Worker (no page-realm WASM, at most one
 * WASM instance), and must render exactly the snippets the TypeScript search
 * renders for the same query on the same page (measurement opt-out arm).
 * Clicking the snippet opens the seeded chat. A common query exercises the
 * warm Worker index and the same TS parity. Performance is gated by the
 * search section of web-rust-core-bench.spec.ts.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { seedCodeEmbedChat } = require('./helpers/embed-ready-metrics');
const { rustCoreInstances } = require('./helpers/rust-core-instances');
const { appMetadataSettled, openSidebarSearch, searchAndWait, sorted, SEARCH_OPT_OUT_KEY, SNIPPETS, RARE_QUERY, COMMON_QUERY } = require('./helpers/web-rust-core-bench-search');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

let consoleForFailure: string[] = [];
test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== testInfo.expectedStatus) {
		console.log('--- failure url ---\n' + page.url());
		console.log('--- browser console (errors/warnings/search/rust, last 150) ---\n'
			+ consoleForFailure.filter((line) => /error|warn|fail|search|rust/i.test(line)).slice(-150).join('\n'));
	}
});

/** Reloads the seeded chat on the `path` arm and runs the rare then the common query. */
async function searchArm(page: any, chatId: string, path: 'ts' | 'rust') {
	await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); }, [SEARCH_OPT_OUT_KEY, path === 'ts']);
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	const settled = appMetadataSettled(page);
	await page.reload();
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 60000 });
	await settled;
	const input = await openSidebarSearch(page);
	const rare = await searchAndWait(page, input, RARE_QUERY, `e2e:${path}:rare`);
	expect(rare.ms, `${path}: rare-query snippet rendered`).not.toBeNull();
	await input.fill('');
	await expect(page.locator(SNIPPETS)).toHaveCount(0, { timeout: 15000 });
	const common = await searchAndWait(page, input, COMMON_QUERY, `e2e:${path}:common`);
	expect(common.ms, `${path}: common-query snippets rendered`).not.toBeNull();
	const marker = await page.evaluate(() => document.documentElement.dataset.rustCoreSearch ?? null);
	return { input, rare: rare.snippets, common: common.snippets, marker };
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,sdk.web.before-after-performance
test('Rust search unit finds saved chat messages with the same snippets as TS', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_SEARCH');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`[${msg.type()}] ${msg.text()}`.slice(0, 400)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });

	const chatId = await seedCodeEmbedChat(page, log, screenshot);

	const ts = await searchArm(page, chatId, 'ts');
	expect(ts.marker, 'TS arm did not use the Rust search unit').toBeNull();
	const rust = await searchArm(page, chatId, 'rust');
	await screenshot(page, 'rust-search-common');
	expect(String(rust.marker), 'the Rust search unit served both queries').toMatch(/^rust:\d+$/);
	expect(Number(String(rust.marker).slice(5)), 'one Rust search per query (cold rerun included)').toBeGreaterThanOrEqual(2);
	expect(sorted(rust.rare), 'rare query: Rust snippets equal TS snippets').toEqual(sorted(ts.rare));
	expect(sorted(rust.common), 'common query: Rust snippets equal TS snippets').toEqual(sorted(ts.common));
	expect(rust.rare.some((text: string) => text.toLowerCase().includes(RARE_QUERY)), 'seeded message found').toBe(true);
	log('search parity', { rare: rust.rare.length, common: rust.common.length });

	const instances = await rustCoreInstances(page);
	expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
	expect(instances.wasmInstantiations, 'at most one WASM instance').toBeLessThanOrEqual(1);
	expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);

	// The rare-query snippet still navigates to the seeded chat.
	await rust.input.fill('');
	await expect(page.locator(SNIPPETS)).toHaveCount(0, { timeout: 15000 });
	await searchAndWait(page, rust.input, RARE_QUERY, 'e2e:rust:navigate');
	await screenshot(page, 'rust-search-rare');
	await page.locator(SNIPPETS).filter({ hasText: new RegExp(RARE_QUERY, 'i') }).first().click();
	await expect(page).toHaveURL(new RegExp(`chat-id=${chatId}`), { timeout: 15000 });
	await expect(page.locator('[data-testid="message-user"]').first()).toBeVisible({ timeout: 30000 });
	await page.evaluate((key: string) => localStorage.removeItem(key), SEARCH_OPT_OUT_KEY);
});
