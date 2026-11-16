/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
// proof-video: not_required reason=visual_smoke_not_needed (send preparation policy parity; the UI is unchanged, the Playwright video is kept)
/**
 * Opt-in shared Rust core (WASM) - web send-preparation decisions on the shared
 * Worker `sendPrep` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check: a logged-in account sends one message in a new
 * chat and the assistant answers. The model-routing restrictions of the send
 * payload must be decided by the Rust `sendPrep` unit (routingRestrictions op
 * served, zero failed calls, no refusal), with one shared Worker and no WASM on
 * the page. Runs only in the CI lane that builds the Rust core package.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
test('send routing restrictions are decided by the shared Rust sendPrep unit', async ({ page }: { page: any }) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_SEND_PREP');
	const screenshot = createStepScreenshotter(log);
	const errors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (/UnitPortError|DataCloneError|send_prep|sendPrep.*(fail|refus)/i.test(text)) errors.push(text.slice(0, 300));
	});
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	const stats = () => page.evaluate(() => (window as any).__openmatesRustSendPrepStats?.() ?? null);
	const before = (await stats())?.ops?.routingRestrictions ?? 0;

	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'send-prep');
	await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });

	await expect.poll(async () => (await stats())?.ops?.routingRestrictions ?? 0,
		{ message: 'routing restrictions decided by the Rust sendPrep unit', timeout: 30000 }).toBeGreaterThan(before);
	const after = await stats();
	expect(after.failures, 'no failed or refused sendPrep call').toBe(0);
	expect(after.opens, 'one sendPrep unit port').toBeLessThanOrEqual(1);
	expect(errors, 'no unit errors during the send').toEqual([]);
});
