/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — web WebSocket lifecycle policy on the shared
 * Worker `ws` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: ws unit). A logged-in account sends one
 * message; then, alternating the TypeScript policy (measurement opt-out
 * `openmates_rust_core_ws=ts`) and the Rust unit, the test drops the page's
 * WebSocket server-side (close 1001) and requires the service to reconnect and
 * keep working (a second message gets an assistant reply). The Rust arm must
 * route the close/reconnect decisions through the unit with zero failures, one
 * shared Worker and no WASM on the page; the TS arm must never load the adapter.
 * Records drop -> reconnected latency per arm (paired medians, approved
 * not-noticeable budget, soft gate).
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage, deleteActiveChat } = require('./helpers/chat-test-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const WS_OPT_OUT_KEY = 'openmates_rust_core_ws';
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

	const samples: Record<'ts' | 'rust', Record<string, unknown>[]> = { ts: [], rust: [] };
	try {
		for (let i = 0; i < PAIRS * 2; i++) {
			const path = i % 2 === 0 ? 'ts' : 'rust';
			await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
				[WS_OPT_OUT_KEY, path === 'ts']);
			await page.reload({ waitUntil: 'domcontentloaded' });
			await expect(page.getByTestId('message-assistant').first().getByTestId('message-content')).not.toBeEmpty({ timeout: 60000 });
			const before = sockets.length;
			const dropped = Date.now();
			await sockets.at(-1).close({ code: 1001, reason: 'e2e drop' });
			await expect.poll(() => sockets.length, { timeout: 45000, message: `${path}: the service reconnected after the drop` }).toBeGreaterThan(before);
			const reconnectMs = Date.now() - dropped;
			const readStats = () => page.evaluate(() => (window as any).__openmatesRustWsStats?.() ?? null);
			const stats = await readStats();
			if (path === 'rust') {
				expect(stats?.ops.closePlan ?? 0, 'Rust arm routed the close decision through the unit').toBeGreaterThan(0);
				expect(stats.failures, 'no ws unit call failed').toBe(0);
			} else {
				expect(stats, 'TS arm never loaded the Rust ws adapter').toBeNull();
			}
			const instances = await rustCoreInstances(page);
			expect(instances.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
			expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, `${path}: one shared Rust core Worker`).toBe(1);
			samples[path].push({ reconnectMs, stats, ...instances });
		}
		await sendMessage(page, withMockMarker('And what is the capital of France?', 'chat_flow_capital', 'fast'), log, screenshot, 'ws-send-after-reconnect');
		await expect(page.getByTestId('message-assistant').last().getByTestId('message-content')).not.toBeEmpty({ timeout: 90000 });
		expect(wsErrors, 'no ws unit errors in either arm').toEqual([]);
	} finally {
		await page.evaluate((key: string) => localStorage.removeItem(key), WS_OPT_OUT_KEY);
		await deleteActiveChat(page, log, screenshot, 'ws-cleanup');
	}
	const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
	const rust = median(samples.rust.map((row) => Number(row.reconnectMs)));
	const ts = median(samples.ts.map((row) => Number(row.reconnectMs)));
	const limit = Math.max(ts * 1.1, ts + 50);
	const metrics = { pairs: PAIRS, rustMedianMs: rust, tsMedianMs: ts, verdict: rust <= limit ? 'rust_not_worse' : 'rust_worse', samples };
	console.log(`[web-rust-core-ws] ${JSON.stringify({ rustMedianMs: rust, tsMedianMs: ts, verdict: metrics.verdict })}`);
	await testInfo.attach('ws-reconnect-latency.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	expect.soft(rust, `drop-to-reconnected: Rust ${rust} ms vs TS ${ts} ms`).toBeLessThanOrEqual(limit);
});
