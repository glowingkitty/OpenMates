/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Opt-in shared Rust core (WASM) in the web app — VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane of the TS -> Rust migration): the normal TS
 * login is handed to the Rust core as an in-memory second device, and Rust feeds the
 * UNCHANGED chat UI (ActiveChat -> ChatHistory/ChatMessage). Covers:
 *   1. TS login and TS chat list (unchanged), first message sent by the TS composer.
 *   2. Cold reload with Rust disabled (measurement opt-out): TS opens the chat (baseline).
 *   3. Cold reload with Rust enabled: Rust reads + decrypts the saved chat and the normal
 *      message-user / message-assistant rows render it (html data-rust-core-history).
 *   4. Send/encrypt: new chats sent from the TS composer with TS crypto vs with
 *      crypto routed through the shared Rust Worker (click to encrypted admission frame).
 * The TS runs also opt out of the Rust crypto unit (pure TS baseline); the Rust runs
 * route history AND crypto through the one shared Worker. Records WASM/worker
 * transfer sizes and TS vs Rust timings as JSON. Gated (medians, Rust <= TS):
 * saved-chat open-to-rendered and send-to-admission wall time, browser CPU and RSS.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage } = require('./helpers/chat-test-helpers');
const { createBrowserProcessEvidence } = require('./helpers/browser-process-evidence.cjs');
const { rustCoreInstances } = require('./helpers/rust-core-instances');
const { installMainThreadTrace, readMainThreadTrace } = require('./helpers/main-thread-trace');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function rustTransfer(page: any): Promise<Record<string, number>> {
	return page.evaluate(() => {
		const rows: Record<string, number> = { wasmTransfer: 0, wasmDecoded: 0, workerTransfer: 0 };
		for (const entry of performance.getEntriesByType('resource') as PerformanceResourceTiming[]) {
			if (entry.name.includes('openmates_browser_bg')) { rows.wasmTransfer += entry.transferSize; rows.wasmDecoded += entry.decodedBodySize; }
			if (entry.name.includes('shared.worker')) rows.workerTransfer += entry.transferSize;
		}
		const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory;
		if (memory) rows.mainHeapBytes = memory.usedJSHeapSize;
		return rows;
	});
}

let consoleForFailure: string[] = [];
test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
	if (testInfo.status !== testInfo.expectedStatus) {
		const trail = await page.evaluate(() => JSON.stringify((window as unknown as { __sendTrail?: unknown[] }).__sendTrail ?? []).slice(0, 6000)).catch(() => 'unavailable');
		console.log('--- TS send debug trail ---\n' + trail);
		console.log('--- browser console (last 80) ---\n' + consoleForFailure.slice(-80).join('\n'));
		const relevant = consoleForFailure.filter((line) => /error|warn|fail|Senders|handleSend|rust|Rust|session_expired|setup incomplete/i.test(line));
		console.log('--- browser console (errors/warnings/send, first 150) ---\n' + relevant.slice(0, 150).join('\n'));
	}
});

const HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';
// Measurement-only opt-out of the Rust crypto unit (webCryptoRegistration.ts).
const CRYPTO_OPT_OUT_KEY = 'openmates_rust_core_crypto';

/** TS runs opt out of Rust history and Rust crypto; Rust runs use both. */
async function selectPath(page: any, path: 'ts' | 'rust'): Promise<void> {
	await page.evaluate(([keys, value]: [string[], string | null]) => {
		for (const key of keys) { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); }
	}, [[HISTORY_OPT_OUT_KEY, CRYPTO_OPT_OUT_KEY], path === 'ts' ? 'ts' : null]);
}

const median = (rows: Array<Record<string, unknown>>, path: string, key: string) => {
	const values = rows.filter((row) => row.path === path && typeof row[key] === 'number').map((row) => Number(row[key])).sort((a, b) => a - b);
	return values.length ? values[Math.floor((values.length - 1) / 2)] : null;
};

/**
 * Approved "not noticeable" budget on every gated median of one user-facing flow: wall time
 * (Ms keys) <= max(+10%, +50 ms), CPU <= +15%, RSS (anything else) <= TS.
 */
function medianLimit(key: string, ts: number): number {
	if (key.endsWith('Ms') && key !== 'browserCpuMs') return Math.max(ts * 1.1, ts + 50);
	if (key === 'browserCpuMs') return ts * 1.15;
	return ts;
}

function expectNotWorseThanTs(flow: string, rows: Array<Record<string, unknown>>, keys: string[]): Record<string, unknown> {
	const medians: Record<string, unknown> = {};
	for (const key of keys) {
		const ts = median(rows, 'ts', key), rust = median(rows, 'rust', key);
		medians[key] = { ts, rust, ratio: ts && rust ? rust / ts : null };
		expect(ts, `${flow} TS median ${key}`).not.toBeNull();
		expect(rust, `${flow} Rust median ${key}: Rust ${rust} vs TS ${ts}`).not.toBeNull();
		// Soft: every gate of the flow is reported, not only the first miss.
		expect.soft(rust!, `${flow} ${key}: Rust ${rust} vs TS ${ts}`).toBeLessThanOrEqual(medianLimit(key, ts!));
	}
	return medians;
}

/** Reload the chat deep link and time open-to-rendered (ms since navigation start). */
async function openChatAfterReload(page: any, chatId: string, path: 'ts' | 'rust', processes: any): Promise<Record<string, unknown>> {
	await selectPath(page, path);
	// The URL already carries this chat id, so goto alone is a same-document hash change.
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	await processes.begin();
	await page.reload();
	const timing: Record<string, unknown> = await page.evaluate((wantRust: boolean) => new Promise<Record<string, unknown>>((resolve) => {
		const result: Record<string, unknown> = {};
		const tick = () => {
			const now = performance.now();
			const marker = document.documentElement.dataset.rustCoreHistory ?? null;
			if (result.uiInteractive === undefined && document.querySelector('[data-testid="message-editor"]')) result.uiInteractive = now;
			const rendered = document.querySelectorAll('[data-testid="message-user"]').length >= 1
				&& document.querySelectorAll('[data-testid="message-assistant"]').length >= 1
				// Rendered means the decrypted contents are visible, not just the bubbles.
				&& [...document.querySelectorAll('[data-testid="message-user"] [data-testid="message-content"], [data-testid="message-assistant"] [data-testid="message-content"]')]
					.every((node) => (node.textContent ?? '').trim().length > 0);
			if (rendered && (!wantRust || marker?.startsWith('rust:'))) {
				result.chatRendered = now;
				result.marker = marker;
				const read = performance.getEntriesByName('openmates:rust-history-read').at(-1);
				if (read) result.rustReadMs = read.duration;
				result.rustSource = document.documentElement.dataset.rustCoreHistorySource ?? null;
				// Stage breakdown (fixed mark names, no content): ms since navigation start.
				// First occurrence per stage (later repeats, e.g. reconcile, keep the first time).
				const stages: Record<string, number> = {};
				for (const entry of performance.getEntriesByType('mark')) {
					const name = entry.name.slice('openmates:rust:'.length);
					if (entry.name.startsWith('openmates:rust:') && !(name in stages)) stages[name] = Math.round(entry.startTime);
				}
				result.rustStages = stages;
				resolve(result);
			} else if (now > 90000 || marker?.startsWith('error:')) {
				result.marker = marker;
				resolve(result);
			} else setTimeout(tick, 20);
		};
		tick();
	}), path === 'rust');
	// CPU/RSS: CDP process window over reload-to-rendered (all verified Chromium
	// processes, incl. the Rust Worker); heap: main JS heap at rendered.
	const process = await processes.end();
	timing.browserCpuMs = process.available ? process.stableReportedProcessCpuMs : null;
	timing.browserRssBytes = process.available ? process.after.summedReportedProcessRssBytes : null;
	timing.mainHeapBytes = await page.evaluate(() => (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? null);
	// Main-thread long tasks and page IndexedDB requests, split at the chat open (load-chat).
	const stages = (timing.rustStages ?? {}) as Record<string, number>;
	timing.mainThread = await readMainThreadTrace(page, stages['load-chat'] ?? null, typeof timing.chatRendered === 'number' ? timing.chatRendered : null);
	// Shared-Worker bench counters: dedicated Workers and WASM instantiations of this load.
	Object.assign(timing, await rustCoreInstances(page));
	return timing;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted,chats.streaming.ordered-final,sdk.web.before-after-performance
test('opens a saved chat in the normal chat UI from Rust-decrypted history', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	// Ten reload opens plus six timed sends (each waits for the reply).
	test.setTimeout(600000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE');
	const screenshot = createStepScreenshotter(log);
	const metrics: Record<string, unknown> = {};
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`${new Date().toISOString().slice(11, 23)} [${msg.type()}] ${msg.text()}`.slice(0, 500)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });
	page.on('worker', (worker: any) => { consoleLines.push(`[worker] ${worker.url()}`); });
	await page.addInitScript(installMainThreadTrace);
	// Keep every TS send debug step (the app only exposes the latest one).
	await page.addInitScript(() => {
		// Send timing: last composer send gesture -> first encrypted admission frame.
		const send = { starts: [] as number[], admitAt: null as number | null };
		(window as unknown as { __sendTiming: typeof send }).__sendTiming = send;
		const markStart = (event: Event) => {
			const target = event.target as Element | null;
			if (event.type === 'custom-send-message' || target?.closest?.('[data-testid="composer-send-button"]')) send.starts.push(performance.now());
		};
		document.addEventListener('click', markStart, true);
		document.addEventListener('custom-send-message', markStart, true);
		const nativeSend = WebSocket.prototype.send;
		WebSocket.prototype.send = function (data) {
			if (send.admitAt === null && typeof data === 'string' && data.includes('"chat_turn_admit"')) send.admitAt = performance.now();
			return nativeSend.call(this, data);
		};
		const trail: unknown[] = [];
		(window as unknown as { __sendTrail: unknown[] }).__sendTrail = trail;
		let last: unknown = null;
		Object.defineProperty(window, '__openmatesLastSendDebug', { configurable: true,
			get: () => last, set: (value) => { last = value; trail.push(value); } });
	});

	// Count the server's storage confirmations of TS assistant replies: the Rust read after
	// the reload is server-only, so it can only see a reply the server has already stored.
	let storedReplies = 0;
	page.on('websocket', (socket: any) => socket.on('framereceived', (frame: any) => {
		if (String(frame.payload).includes('"ai_response_storage_confirmed"')) storedReplies++;
	}));

	// 1. Normal TS login (unchanged by the Rust switch).
	// "Stay logged in" keeps the master key across the cold reloads below; without it a
	// reload is a forced logout and neither TS nor Rust can open the chat.
	await loginToTestAccount(page, log, screenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	// Same settle as chat-scroll-streaming.spec.ts: let post-login sync finish first.
	await page.waitForTimeout(5000);
	const newChatButton = page.getByTestId('new-chat-button');
	if (await newChatButton.isVisible()) {
		await newChatButton.click();
		await page.waitForTimeout(2000);
	}
	await screenshot(page, 'logged-in');

	// 2. First message through the TS composer creates the saved chat (send/stream stay
	//    TS-owned). Text avoids place names so offline PII detection does not intervene.
	await sendMessage(page, withMockMarker('Please explain how photosynthesis works in detail.', 'chat_flow_capital', 'fast'), log, screenshot, 'ts-send');
	const chatId = await expect.poll(() => page.url().match(/chat-id=([a-f0-9-]{36})/)?.[1] ?? null, { timeout: 30000 }).not.toBeNull()
		.then(() => page.url().match(/chat-id=([a-f0-9-]{36})/)![1]);
	log('TS created chat', { chatId });

	await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60000 });
	await expect.poll(() => storedReplies, { timeout: 60000, message: 'server stored the TS assistant reply' }).toBeGreaterThanOrEqual(1);
	metrics.firstLoad = await rustTransfer(page);

	// 3. Alternate TS baseline and Rust opens of the same saved chat, same page and run.
	const renderedTexts = () => page.locator('[data-testid="message-user"] [data-testid="message-content"], [data-testid="message-assistant"] [data-testid="message-content"]').allInnerTexts();
	let tsTexts: string[] = [];
	const runs: Array<Record<string, unknown>> = [];
	const processes = await createBrowserProcessEvidence(page);
	// Five alternating pairs: the median is the middle run, robust to one slow reload.
	for (const path of ['ts', 'rust', 'ts', 'rust', 'ts', 'rust', 'ts', 'rust', 'ts', 'rust'] as const) {
		const timing = await openChatAfterReload(page, chatId, path, processes);
		log('open timing', { path, ...timing });
		runs.push({ path, ...timing });
		expect(timing.chatRendered, `${path} rendered the saved chat after reload`).toBeDefined();
		expect(timing.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
		// Flag-on reload (both arms; Rust auth restores the session in each, as before the
		// shared Worker): exactly one Rust Worker, the shared core Worker, with one WASM instance.
		const loadWorkers = timing.workers as { name: string; wasm: number }[];
		expect(loadWorkers.filter((worker) => worker.name === 'auth.worker').length, `${path}: no dedicated auth Worker`).toBe(0);
		expect(timing.rustWorkers, `${path}: one Rust Worker after reload`).toBe(1);
		expect(timing.dedicatedWorkers, `${path}: one dedicated Worker after reload`).toBe(1);
		expect(timing.sharedWorkerWasm, `${path}: the shared Worker holds the WASM instance`).toBe(1);
		expect(timing.wasmInstantiations, `${path}: one WASM instance in the tab`).toBe(1);
		if (path === 'ts') {
			expect(timing.marker, 'TS baseline did not use Rust').toBeNull();
			// Bubbles mount before their decrypted content; wait until every content is filled in.
			await expect.poll(async () => { tsTexts = await renderedTexts(); return tsTexts.length >= 2 && tsTexts.every((text) => text.trim().length > 0); },
				{ timeout: 20000, message: 'TS rendered the saved message contents' }).toBe(true);
			continue;
		}
		// 4. The normal UI shows the Rust-decrypted rows.
		const marker = String(timing.marker);
		expect(marker, 'Rust supplied the opened chat history').toMatch(/^rust:\d+$/);
		const workers = timing.workers as { name: string; wasm: number }[];
		expect(workers.filter((worker) => worker.name === 'shared.worker').length, 'history runs on the one shared Rust core Worker').toBe(1);
		expect(workers.filter((worker) => worker.name === 'production.worker').length, 'no dedicated history Worker').toBe(0);
		expect(timing.sharedWorkerWasm, 'one WASM instance serves the Rust history').toBe(1);
		expect(timing.rustSource, 'Rust rendered the retained IndexedDB rows first (cache-first, like TS)').toBe('cache');
		const supplied = Number(marker.slice('rust:'.length));
		expect(supplied).toBeGreaterThanOrEqual(2);
		await expect(page.getByTestId('message-user').first()).toContainText('photosynthesis');
		await expect(page.getByTestId('message-assistant').first()).toBeVisible();
		await expect(page.getByTestId('message-editor')).toBeVisible();
		expect(await page.locator('[data-testid="message-user"], [data-testid="message-assistant"]').count()).toBe(supplied);
		await expect.poll(renderedTexts, { timeout: 20000, message: 'Rust renders the identical decrypted message contents as TS' }).toEqual(tsTexts);
		// After the background Rust server reconcile the rows are neither duplicated nor changed.
		await expect.poll(() => page.evaluate(() => performance.getEntriesByName('openmates:rust:server-read-end').length),
			{ timeout: 30000, message: 'Rust reconciled the cached page with the server' }).toBeGreaterThanOrEqual(1);
		expect(await page.locator('[data-testid="message-user"], [data-testid="message-assistant"]').count(), 'reconcile kept the row count').toBe(supplied);
		expect(await renderedTexts(), 'reconcile kept the decrypted message contents').toEqual(tsTexts);
		await screenshot(page, `rust-history-${runs.length}`);
	}

	// 5. Send/encrypt from a fresh chat after a cold reload, alternating TS and Rust crypto.
	const sends: Array<Record<string, unknown>> = [];
	for (const path of ['ts', 'rust', 'ts', 'rust', 'ts', 'rust'] as const) {
		await selectPath(page, path);
		await page.goto(getE2EDebugUrl('/'));
		await page.reload();
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
		// Same settle as the first send: post-login sync, then a fresh chat.
		await page.waitForTimeout(3000);
		const button = page.getByTestId('new-chat-button');
		if (await button.isVisible()) { await button.click(); await page.waitForTimeout(2000); }
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
		await page.evaluate(() => { const t = (window as unknown as { __sendTiming: { starts: number[]; admitAt: number | null } }).__sendTiming; t.starts = []; t.admitAt = null; });
		await processes.begin();
		await sendMessage(page, withMockMarker(`Please explain how leaves use sunlight, run ${sends.length + 1}.`, 'chat_flow_capital', 'fast'), log, screenshot, `${path}-send-${sends.length + 1}`);
		const send = await expect.poll(() => page.evaluate(() => (window as unknown as { __sendTiming: { starts: number[]; admitAt: number | null } }).__sendTiming),
			{ timeout: 30000, message: `${path}: encrypted admission frame sent` }).toMatchObject({ admitAt: expect.any(Number) })
			.then(() => page.evaluate(() => (window as unknown as { __sendTiming: { starts: number[]; admitAt: number } }).__sendTiming));
		const process = await processes.end();
		// After the send: the crypto unit is opened lazily by the first crypto call.
		const instances = await rustCoreInstances(page);
		const start = send.starts.filter((value: number) => value <= send.admitAt).at(-1);
		expect(start, `${path}: send gesture recorded before admission`).toBeDefined();
		const row = { path, sendToAdmitMs: send.admitAt - start!,
			browserCpuMs: process.available ? process.stableReportedProcessCpuMs : null,
			browserRssBytes: process.available ? process.after.summedReportedProcessRssBytes : null,
			sharedWorkerWasm: instances.sharedWorkerWasm };
		log('send timing', row);
		sends.push(row);
		// One shared-Worker WASM instance in both arms: Rust auth (both) plus Rust crypto (Rust arm).
		expect(instances.sharedWorkerWasm, `${path} send: one shared Worker WASM instance`).toBe(1);
		expect(instances.wasmInstantiations, `${path} send: one WASM instance in the tab`).toBe(1);
		await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60000 });
		await expect(page.getByTestId('message-user').last()).toContainText('leaves use sunlight');
	}
	await processes.close();
	metrics.openToRenderedMs = { runs };
	metrics.perOpenMedians = Object.fromEntries((['ts', 'rust'] as const).map((path) => [path,
		{ chatRendered: median(runs, path, 'chatRendered'), browserCpuMs: median(runs, path, 'browserCpuMs'), browserRssBytes: median(runs, path, 'browserRssBytes'),
			mainHeapBytes: median(runs, path, 'mainHeapBytes'), dedicatedWorkers: median(runs, path, 'dedicatedWorkers'), rustWorkers: median(runs, path, 'rustWorkers'),
			wasmInstantiations: median(runs, path, 'wasmInstantiations'), sharedWorkerWasm: median(runs, path, 'sharedWorkerWasm') }]));
	metrics.sendToAdmission = { sends };
	metrics.reload = await rustTransfer(page);
	log('Rust core metrics', metrics);
	await testInfo.attach('web-rust-core-metrics.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	// Strict user-facing gates (attached above, so a failing run keeps its numbers).
	metrics.gates = {
		open: expectNotWorseThanTs('saved-chat open', runs, ['chatRendered', 'browserCpuMs', 'browserRssBytes']),
		send: expectNotWorseThanTs('send/encrypt', sends, ['sendToAdmitMs', 'browserCpuMs', 'browserRssBytes'])
	};
	log('Rust core gates', metrics.gates);
});
