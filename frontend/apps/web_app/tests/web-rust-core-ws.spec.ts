/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Shared Rust core (WASM) — web WebSocket lifecycle decisions on the shared
 * Worker `ws` unit (the only path; no TypeScript reconnect branch exists).
 *
 * Engineering migration check (web lane: ws unit). A logged-in account sends one
 * message; then the test drops the page's WebSocket server-side (close 1001)
 * several times and requires the service to reconnect and keep working (a
 * further message gets an assistant reply). Every close/reconnect decision must
 * route through the unit with zero failures, one shared Worker and no WASM on
 * the page. Records drop -> reconnected latency.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const PAIRS = 3;

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted,sdk.web.before-after-performance
test('websocket close and reconnect decisions run on the shared Rust ws unit and the connection recovers', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(420000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_WS');
	const screenshot = createStepScreenshotter(log);
	const wsErrors: string[] = [];
	page.on('console', (msg: any) => {
		const text = msg.text();
		if (/UnitPortError|Rust lifecycle reconnect(ion)? failed/.test(text)) wsErrors.push(text.slice(0, 300));
	});
	const sockets: any[] = [];
	await page.routeWebSocket(/\/ws(?:\?|$)/, (socket: any) => {
		const server = socket.connectToServer();
		socket.onMessage((message: any) => server.send(message));
		server.onMessage((message: any) => socket.send(message));
		sockets.push(socket);
	});
	await page.goto(getE2EDebugUrl('/'));
	await loginToTestAccount(page, log, screenshot);
	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'ws-send');
	await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });

	const samples: Record<string, unknown>[] = [];
	try {
		for (let i = 0; i < PAIRS; i++) {
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 60000 });
			const before = sockets.length;
			const dropped = Date.now();
			await sockets.at(-1).close({ code: 1001, reason: 'e2e drop' });
			await expect.poll(() => sockets.length, { timeout: 45000, message: 'the service reconnected after the drop' }).toBeGreaterThan(before);
			const reconnectMs = Date.now() - dropped;
			const stats = await page.evaluate(() => (window as any).__openmatesRustWsStats?.() ?? null);
			expect(stats?.ops.closePlan ?? 0, 'the close decision ran through the unit').toBeGreaterThan(0);
			expect(stats.failures, 'no ws unit call failed').toBe(0);
			const instances = await rustCoreInstances(page);
			expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
			expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
			samples.push({ reconnectMs, stats, ...instances });
		}
		await sendMessage(page, withMockMarker('And what is the capital of France?', 'chat_flow_capital', 'fast'), log, screenshot, 'ws-send-after-reconnect');
		await expect(page.getByTestId('message-assistant').last().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });
		expect(wsErrors, 'no ws unit errors').toEqual([]);
	} finally {
		await deleteActiveChat(page, log, screenshot, 'ws-cleanup');
	}
	const metrics = { drops: PAIRS, samples };
	await testInfo.attach('ws-reconnect-latency.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
});
