/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Opt-in shared Rust core (WASM) — composer PII detection on the shared Worker
 * `composer` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: composer). A logged-in account types a
 * draft with two emails and one phone number; the editor must highlight exactly
 * those three spans, with the detection served by the Rust composer unit (zero
 * failures, one shared Worker, no WASM on the page). Records keystroke ->
 * highlight latency as an advisory metric. Runs only in the CI lane that builds
 * the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=pii.composer.detect-redact-exclude
test('composer PII highlights are served by the shared Rust composer unit', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_COMPOSER');
	const screenshot = createStepScreenshotter(log);
	const unitErrors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (/UnitPortError|PII detector returned invalid/.test(text)) unitErrors.push(text.slice(0, 300));
	});
	await loginToTestAccount(page, log, screenshot);
	await startNewChat(page, log);
	const editor = page.getByTestId('message-editor');
	await expect(editor).toBeVisible({ timeout: 15000 });
	await editor.click({ position: { x: 12, y: 12 }, force: true });
	const started = Date.now();
	await page.keyboard.insertText(
		'Write a draft from max@posteo.de to sarah@proton.com about the heater. My phone number is +49 170 1234567 for callbacks.',
	);
	await page.keyboard.type(' ', { delay: 10 });
	const highlights = page.locator('[data-testid="pii-highlight"]');
	await expect.poll(async () => highlights.count(), { timeout: 30000 }).toBe(3);
	const highlightMs = Date.now() - started;
	await expect(page.locator('[data-testid="pii-highlight"][data-pii-type="EMAIL"]')).toHaveCount(2);
	await expect(page.locator('[data-testid="pii-highlight"][data-pii-type="PHONE"]')).toHaveCount(1);

	const stats = await page.evaluate(() => (window as any).__openmatesRustComposerStats?.() ?? null);
	expect(stats, 'the Rust composer adapter served the detection').not.toBeNull();
	expect(stats.calls, 'composer unit was called').toBeGreaterThan(0);
	expect(stats.failures, 'no composer unit call failed').toBe(0);
	const instances = await rustCoreInstances(page);
	expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
	expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
	expect(unitErrors, 'no composer unit errors').toEqual([]);
	console.log(`[web-rust-core-composer] ${JSON.stringify({ highlightMs, calls: stats.calls })}`);
	await testInfo.attach('composer-pii-latency.json', { body: JSON.stringify({ highlightMs, stats, ...instances }, null, 2), contentType: 'application/json' });
	await screenshot(page, 'composer-pii-highlighted');
});
