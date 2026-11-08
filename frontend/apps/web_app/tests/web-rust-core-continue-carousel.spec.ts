/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM), VITE_OPENMATES_RUST_CORE=1 build: the welcome-screen
 * "Continue where you left off" priority layer (reminder index by chat and the priority
 * order) is decided by the shared Worker `chatState` unit op `continueDecide`
 * (packages/openmates-rust/src/web_continue.rs) instead of continueCarouselService.ts.
 *
 * A logged-in account opens the welcome screen; the page must call `continueDecide`
 * for both decisions with zero unit failures, never log the priority-load warning,
 * keep one shared Worker and no WASM on the page realm. Parity of the decisions
 * themselves is proven by the TS-generated vectors (continueCarouselVectors.test.ts,
 * web_continue_tests.rs). Runs only in the CI lane that builds the Rust core package.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=continue-carousel.chat.reminder-gated,sdk.client.thin-platform-boundary
test('welcome continue-carousel priority decisions run on the shared Rust chatState unit', async ({ page }: { page: any }) => {
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_CONTINUE');
	const screenshot = createStepScreenshotter(log);
	const priorityWarnings: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (text.includes('Failed to load priority continue items')) priorityWarnings.push(text.slice(0, 300));
	});
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await page.goto(getE2EDebugUrl('/'));
	await expect(page.locator('[data-action="message-input"]').last()).toBeVisible({ timeout: 60000 });

	const readStats = () => page.evaluate(() => (window as any).__openmatesRustChatStateStats?.() ?? null);
	// One loadPriorityContinueItems run indexes the reminders and then sorts the priority items.
	await expect.poll(async () => (await readStats())?.ops?.continueDecide ?? 0, {
		message: 'the welcome screen decided the continue priority layer through the unit', timeout: 60000,
	}).toBeGreaterThanOrEqual(2);
	await screenshot(page, 'welcome-continue-carousel');
	expect((await readStats()).failures, 'no chatState unit call failed').toBe(0);
	expect(priorityWarnings, 'the priority continue layer loaded without errors').toEqual([]);
	const instances = await rustCoreInstances(page);
	expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
	expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
});
