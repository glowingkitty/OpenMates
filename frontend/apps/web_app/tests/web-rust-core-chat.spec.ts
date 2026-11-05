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
 * Records WASM/worker transfer sizes and TS vs Rust open-to-rendered timings (five
 * alternating pairs, medians and their ratio; target <= 1.1x) as JSON.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl, withMockMarker } = require('./signup-flow-helpers');
const { loginToTestAccount, sendMessage } = require('./helpers/chat-test-helpers');
const { createBrowserProcessEvidence } = require('./helpers/browser-process-evidence.cjs');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();

async function rustTransfer(page: any): Promise<Record<string, number>> {
	return page.evaluate(() => {
		const rows: Record<string, number> = { wasmTransfer: 0, wasmDecoded: 0, workerTransfer: 0 };
		for (const entry of performance.getEntriesByType('resource') as PerformanceResourceTiming[]) {
			if (entry.name.includes('openmates_browser_bg')) { rows.wasmTransfer += entry.transferSize; rows.wasmDecoded += entry.decodedBodySize; }
			if (entry.name.includes('production.worker')) rows.workerTransfer += entry.transferSize;
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

/** Reload the chat deep link and time open-to-rendered (ms since navigation start). */
async function openChatAfterReload(page: any, chatId: string, path: 'ts' | 'rust', processes: any): Promise<Record<string, unknown>> {
	await page.evaluate(([key, value]: [string, string | null]) => {
		if (value) localStorage.setItem(key, value); else localStorage.removeItem(key);
	}, [HISTORY_OPT_OUT_KEY, path === 'ts' ? 'ts' : null]);
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
	return timing;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted,chats.streaming.ordered-final,sdk.web.before-after-performance
test('opens a saved chat in the normal chat UI from Rust-decrypted history', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(240000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE');
	const screenshot = createStepScreenshotter(log);
	const metrics: Record<string, unknown> = {};
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`${new Date().toISOString().slice(11, 23)} [${msg.type()}] ${msg.text()}`.slice(0, 500)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });
	page.on('worker', (worker: any) => { consoleLines.push(`[worker] ${worker.url()}`); });
	// Keep every TS send debug step (the app only exposes the latest one).
	await page.addInitScript(() => {
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
	await processes.close();
	const median = (path: string, key = 'chatRendered') => {
		const values = runs.filter((run) => run.path === path && typeof run[key] === 'number').map((run) => Number(run[key])).sort((a, b) => a - b);
		return values.length ? values[Math.floor((values.length - 1) / 2)] : null;
	};
	const tsMedian = median('ts'), rustMedian = median('rust');
	// Target: rustMedian <= 1.1 x tsMedian. Recorded, not yet gated: CI runners still
	// vary between ~1.05x and ~1.3x (Worker/WASM readiness is on the critical path).
	metrics.openToRenderedMs = { runs, tsMedian, rustMedian, rustToTsRatio: tsMedian && rustMedian ? rustMedian / tsMedian : null };
	metrics.perOpenMedians = Object.fromEntries((['ts', 'rust'] as const).map((path) => [path,
		{ browserCpuMs: median(path, 'browserCpuMs'), browserRssBytes: median(path, 'browserRssBytes'), mainHeapBytes: median(path, 'mainHeapBytes') }]));
	metrics.reload = await rustTransfer(page);
	log('Rust core metrics', metrics);
	await testInfo.attach('web-rust-core-metrics.json', { body: JSON.stringify(metrics, null, 2), contentType: 'application/json' });
	expect(tsMedian, 'TS baseline median').not.toBeNull();
	expect(rustMedian, 'Rust median').not.toBeNull();
});
