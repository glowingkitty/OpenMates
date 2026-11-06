/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page/TestInfo handles are untyped in these CommonJS specs. */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Shared body of the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench.spec.ts) and its attribution entry
 * (web-rust-core-profile.spec.ts). See web-rust-core-bench.spec.ts for the
 * method and metrics. With `profile`, after the paired samples (never inside
 * them, so tracing overhead stays out of the verdicts) two extra TS/Rust reload
 * pairs run under bench-profile.ts and the second pair's attribution is attached
 * as web-rust-core-profile.json.
 */
export {};

const { expect } = require('./cookie-audit');
const { skipWithoutCredentials } = require('./env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('../signup-flow-helpers');
const { seedCodeEmbedChat } = require('./embed-ready-metrics');
const { rustCoreInstances } = require('./rust-core-instances');
const { createBrowserProcessEvidence } = require('./browser-process-evidence.cjs');
const { summarizePaired, markdownTable } = require('./bench-stats');
const { createBenchProfiler } = require('./bench-profile');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
/** Measurement-only opt-out of the Rust history source (rustChatHistoryBootstrap.ts). */
const HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';
const MARGIN = Number.parseFloat(process.env.OPENMATES_BENCH_MARGIN ?? '0.03') || 0.03;

/** Approved gate: wall time and CPU within +3% (paired 95% CI), RSS within +30 MB, at most one WASM instance. */
const GATED_RATIO_METRICS = ['chatRenderedMs', 'embedReadyMs', 'uiInteractiveMs', 'browserCpuMs'] as const;
const RSS_LIMIT_BYTES = 30 * 1024 * 1024;
const REPORTED_METRICS = ['mainHeapBytes', 'dedicatedWorkers', 'rustWorkers'] as const;

/** In-page: one navigation window until chat, embed and editor are all ready. */
function waitAllReady(wantRust: boolean): Promise<Record<string, any>> {
	return new Promise((resolve) => {
		const result: Record<string, any> = {};
		const embedSelector = '[data-testid="message-assistant"] [data-testid="embed-preview"][data-app-id="code"][data-status="finished"]';
		const tick = () => {
			const now = performance.now();
			const marker = document.documentElement.dataset.rustCoreHistory ?? null;
			if (result.uiInteractiveMs === undefined && document.querySelector('[data-testid="message-editor"]')) result.uiInteractiveMs = now;
			const contents = [...document.querySelectorAll('[data-testid="message-user"] [data-testid="message-content"], [data-testid="message-assistant"] [data-testid="message-content"]')];
			const rendered = document.querySelectorAll('[data-testid="message-user"]').length >= 1
				&& document.querySelectorAll('[data-testid="message-assistant"]').length >= 1
				&& contents.length >= 2 && contents.every((node) => (node.textContent ?? '').trim().length > 0);
			if (result.chatRenderedMs === undefined && rendered && (!wantRust || marker?.startsWith('rust:'))) result.chatRenderedMs = now;
			if (result.embedReadyMs === undefined && document.querySelector(embedSelector)) result.embedReadyMs = now;
			const done = result.chatRenderedMs !== undefined && result.embedReadyMs !== undefined && result.uiInteractiveMs !== undefined;
			if (done || now > 90000) {
				result.marker = marker;
				const loadChat = performance.getEntriesByName('openmates:rust:load-chat')[0];
				if (loadChat) result.loadChatStageMs = loadChat.startTime;
				resolve(result);
			} else setTimeout(tick, 10);
		};
		tick();
	});
}

async function reloadSample(page: any, chatId: string, path: 'ts' | 'rust', processes: any, profiler: any = null): Promise<Record<string, any>> {
	await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); }, [HISTORY_OPT_OUT_KEY, path === 'ts']);
	// The URL already carries this chat id, so goto alone is a same-document hash change.
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	await processes.begin();
	if (profiler) await profiler.begin();
	await page.reload();
	const sample = await page.evaluate(waitAllReady, path === 'rust');
	if (profiler) sample.profile = await profiler.end();
	const process = await processes.end();
	sample.browserCpuMs = process.available ? process.stableReportedProcessCpuMs : null;
	sample.browserRssBytes = process.available ? process.after.summedReportedProcessRssBytes : null;
	sample.mainHeapBytes = await page.evaluate(() => (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? null);
	Object.assign(sample, await rustCoreInstances(page));
	expect(sample.chatRenderedMs, `${path}: saved chat rendered`).toBeDefined();
	expect(sample.embedReadyMs, `${path}: embed preview finished`).toBeDefined();
	expect(sample.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
	if (path === 'rust') expect(String(sample.marker), 'Rust supplied the history').toMatch(/^rust:\d+$/);
	else expect(sample.marker, 'TS arm did not use Rust history').toBeNull();
	return sample;
}

let consoleForFailure: string[] = [];
/** Failure diagnostics; each spec registers it with `test.afterEach(benchFailureDiagnostics)`. */
async function benchFailureDiagnostics({ page }: { page: any }, testInfo: any): Promise<void> {
	if (testInfo.status !== testInfo.expectedStatus) {
		console.log('--- failure url ---\n' + page.url());
		console.log('--- browser console (errors/warnings/rust, last 100) ---\n'
			+ consoleForFailure.filter((line) => /error|warn|fail|rust/i.test(line)).slice(-100).join('\n'));
	}
}

/**
 * Runs the paired bench on `page` and attaches its verdicts; `profile` adds the
 * attribution pairs after the paired samples. Called from each spec's own test().
 */
async function runWebRustCoreBench(page: any, testInfo: any, options: { pairs: number; profile: boolean }): Promise<void> {
	const PAIRS = options.pairs;
	const log = createSignupLogger('WEB_RUST_CORE_BENCH');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	consoleForFailure = consoleLines;
	page.on('console', (msg: any) => { consoleLines.push(`[${msg.type()}] ${msg.text()}`.slice(0, 400)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });

	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	const processes = await createBrowserProcessEvidence(page);
	const pairs: { ts: Record<string, any>; rust: Record<string, any> }[] = [];
	try {
		// Pair 0 is a discarded warm-up (HTTP/WASM caches, JIT); then ABAB.
		for (let index = 0; index <= PAIRS; index += 1) {
			const ts = await reloadSample(page, chatId, 'ts', processes);
			const rust = await reloadSample(page, chatId, 'rust', processes);
			if (index === 0) continue;
			pairs.push({ ts, rust });
			log('pair', { index, tsRendered: ts.chatRenderedMs, rustRendered: rust.chatRenderedMs, tsEmbed: ts.embedReadyMs, rustEmbed: rust.embedReadyMs });
		}
		if (options.profile) {
			const profiler = await createBenchProfiler(page);
			try {
				let profiled: { ts: Record<string, any>; rust: Record<string, any> } | null = null;
				for (let round = 0; round < 2; round += 1) {
					profiled = { ts: await reloadSample(page, chatId, 'ts', processes, profiler), rust: await reloadSample(page, chatId, 'rust', processes, profiler) };
				}
				await testInfo.attach('web-rust-core-profile.json', { body: JSON.stringify(profiled, null, 2), contentType: 'application/json' });
				log('profile attached', { tsRendered: profiled!.ts.chatRenderedMs, rustRendered: profiled!.rust.chatRenderedMs });
			} finally {
				await profiler.close();
			}
		}
	} finally {
		await processes.close();
		await page.evaluate((key: string) => localStorage.removeItem(key), HISTORY_OPT_OUT_KEY).catch(() => undefined);
	}

	const column = (metric: string) => pairs.map((pair) => ({ ts: pair.ts[metric], rust: pair.rust[metric] }));
	const summary: Record<string, Record<string, any>> = {};
	for (const metric of GATED_RATIO_METRICS) summary[metric] = summarizePaired(column(metric), { mode: 'ratio', margin: MARGIN });
	summary.browserRssBytes = summarizePaired(column('browserRssBytes'), { mode: 'difference', limit: RSS_LIMIT_BYTES });
	for (const metric of REPORTED_METRICS) summary[metric] = summarizePaired(column(metric), { mode: 'difference', gate: false });
	// More than one WASM instance in a Rust load is an automatic failure, whatever the statistics say.
	const maxRustWasm = Math.max(...pairs.map((pair) => Number(pair.rust.wasmInstantiations)));
	summary.wasmInstantiations = { ...summarizePaired(column('wasmInstantiations'), { mode: 'difference' }), verdict: maxRustWasm > 1 ? 'rust_worse' : 'rust_not_worse', maxRustInstances: maxRustWasm };
	const loadChat = pairs.map((pair) => pair.rust.loadChatStageMs).filter((v) => typeof v === 'number').sort((a, b) => a - b);
	const report = {
		pairs: PAIRS, margin: MARGIN, rssLimitBytes: RSS_LIMIT_BYTES, order: 'ts,rust interleaved after one discarded warm-up pair',
		summary,
		rustLoadChatStageMs: { n: loadChat.length, median: loadChat.length ? loadChat[Math.floor((loadChat.length - 1) / 2)] : null },
		samples: pairs,
	};
	const table = markdownTable(summary);
	log('bench table\n' + table, { rustLoadChatStageMs: report.rustLoadChatStageMs });
	await testInfo.attach('web-rust-core-bench.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-bench.md', { body: table, contentType: 'text/markdown' });
	for (const metric of ['chatRenderedMs', 'embedReadyMs'] as const) {
		expect(summary[metric].pairs, `${metric}: usable pairs`).toBe(PAIRS);
	}
	// Approved gate: more than one WASM instance in a Rust load is an automatic failure (report is attached first).
	expect(maxRustWasm, 'at most one WASM instance per Rust load').toBeLessThanOrEqual(1);
}

module.exports = { runWebRustCoreBench, benchFailureDiagnostics, skipWithoutCredentials, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY };
