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
const { summarizePaired, markdownTable, pairOrder, interpolatedBaselinePairs, transitionIncrements } = require('./bench-stats');
const { createBenchProfiler } = require('./bench-profile');
const { runSendBench } = require('./web-rust-core-bench-send');
const { measureDraftSaves } = require('./draft-save-metrics');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
/** Measurement-only opt-out of the Rust history source (rustChatHistoryBootstrap.ts). */
const HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';
/** Measurement-only opt-out of the Rust IndexedDB message-row policy (db/messageOperations.ts). */
const PERSIST_OPT_OUT_KEY = 'openmates_rust_core_persist';
const MARGIN = Number.parseFloat(process.env.OPENMATES_BENCH_MARGIN ?? '0.1') || 0.1;
const CPU_MARGIN = 0.15;
const WALL_FLOOR_MS = 50;
const P95_ALLOW_MS = 100;
const COLD_START_P95_ALLOW_MS = 200;

/** Approved gate: wall time within max(+10%, +50 ms) and p95 +100 ms (+200 ms cold start), CPU within +15% (paired 95% CI), RSS within +30 MB, at most one WASM instance. */
const GATED_WALL_METRICS = ['chatRenderedMs', 'embedReadyMs', 'uiInteractiveMs'] as const;
const GATED_RATIO_METRICS = [...GATED_WALL_METRICS, 'browserCpuMs'] as const;
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
	await page.evaluate(([keys, ts]: [string[], boolean]) => { for (const key of keys) { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); } },
		[[HISTORY_OPT_OUT_KEY, PERSIST_OPT_OUT_KEY], path === 'ts']);
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
	sample.browserRssBeforeBytes = process.available ? process.before.summedReportedProcessRssBytes : null;
	sample.mainHeapBytes = await page.evaluate(() => (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory?.usedJSHeapSize ?? null);
	Object.assign(sample, await rustCoreInstances(page));
	if (!profiler) {
		// Draft save (draft-save-metrics.ts) after the reload window, outside the CPU/RSS evidence.
		Object.assign(sample, await measureDraftSaves(page, chatId, path === 'rust'));
		if (path === 'rust') expect(String(sample.draftSaveMarker), 'Rust saved the draft').toMatch(/^rust-(local|synced)$/);
		else expect(sample.draftSaveMarker === null || String(sample.draftSaveMarker).startsWith('ts-'), 'TS arm used the TS draft writer').toBe(true);
	}
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
	// Every reload in measurement order (warm-up included) for the RSS level metrics.
	const sequence: { arm: 'ts' | 'rust'; sample: Record<string, any>; warmUp: boolean }[] = [];
	let send: Record<string, any> | null = null;
	try {
		// Pair 0 is a discarded warm-up (HTTP/WASM caches, JIT); then counterbalanced
		// pairs (ts,rust / rust,ts alternately) so carry-over from the previous arm cancels.
		for (let index = 0; index <= PAIRS; index += 1) {
			const pair: Record<string, Record<string, any>> = {};
			for (const arm of pairOrder(index)) {
				pair[arm] = await reloadSample(page, chatId, arm, processes);
				sequence.push({ arm, sample: pair[arm], warmUp: index === 0 });
			}
			if (index === 0) continue;
			const { ts, rust } = pair;
			pairs.push({ ts, rust });
			log('pair', { index, order: pairOrder(index).join(','), tsRendered: ts.chatRenderedMs, rustRendered: rust.chatRenderedMs, tsEmbed: ts.embedReadyMs, rustEmbed: rust.embedReadyMs });
		}
		// The RSS baseline interpolates between TS samples on both sides of each Rust sample.
		if (sequence[sequence.length - 1].arm === 'rust') sequence.push({ arm: 'ts', sample: await reloadSample(page, chatId, 'ts', processes), warmUp: false });
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
		// Paired send flow (web-rust-core-bench-send.ts), after every reload sample.
		// Opt-in (OPENMATES_BENCH_SEND=1) until the send-time session refusal flake is fixed.
		if (process.env.OPENMATES_BENCH_SEND === '1') send = await runSendBench(page, { pairs: Number.parseInt(process.env.OPENMATES_BENCH_SEND_PAIRS ?? '', 10) || PAIRS, margin: MARGIN, processes, log, screenshot, profile: options.profile });
	} finally {
		await processes.close();
		await page.evaluate((keys: string[]) => keys.forEach((key) => localStorage.removeItem(key)), [HISTORY_OPT_OUT_KEY, PERSIST_OPT_OUT_KEY]).catch(() => undefined);
	}

	const column = (metric: string) => pairs.map((pair) => ({ ts: pair.ts[metric], rust: pair.rust[metric] }));
	const summary: Record<string, Record<string, any>> = {};
	for (const metric of GATED_RATIO_METRICS) summary[metric] = metric === 'browserCpuMs'
		? summarizePaired(column(metric), { mode: 'ratio', margin: CPU_MARGIN })
		: summarizePaired(column(metric), { mode: 'ratio', margin: MARGIN, floorMs: WALL_FLOOR_MS, p95AllowMs: metric === 'uiInteractiveMs' ? COLD_START_P95_ALLOW_MS : P95_ALLOW_MS });
	// Summed process RSS climbs with every same-renderer reload whatever the arm, so the
	// gate compares each Rust sample with the TS level interpolated at its position
	// (bench-stats.ts interpolatedBaselinePairs); the adjacent-pair difference is reported.
	const measured = sequence.filter((entry) => !entry.warmUp);
	summary.browserRssBytes = summarizePaired(interpolatedBaselinePairs(measured.map((entry) => ({ arm: entry.arm, value: entry.sample.browserRssBytes }))), { mode: 'difference', limit: RSS_LIMIT_BYTES });
	summary.browserRssBytesAdjacentPair = summarizePaired(column('browserRssBytes'), { mode: 'difference', gate: false });
	for (const metric of REPORTED_METRICS) summary[metric] = summarizePaired(column(metric), { mode: 'difference', gate: false });
	summary.draftSaveP95Ms = summarizePaired(column('draftSaveP95Ms'), { mode: 'ratio', margin: MARGIN });
	// More than one WASM instance in a Rust load is an automatic failure, whatever the statistics say.
	const maxRustWasm = Math.max(...pairs.map((pair) => Number(pair.rust.wasmInstantiations)));
	summary.wasmInstantiations = { ...summarizePaired(column('wasmInstantiations'), { mode: 'difference' }), verdict: maxRustWasm > 1 ? 'rust_worse' : 'rust_not_worse', maxRustInstances: maxRustWasm };
	if (send) Object.assign(summary, send.summary);
	const loadChat = pairs.map((pair) => pair.rust.loadChatStageMs).filter((v) => typeof v === 'number').sort((a, b) => a - b);
	const report = {
		pairs: PAIRS, margin: MARGIN, rssLimitBytes: RSS_LIMIT_BYTES, order: 'counterbalanced ts,rust / rust,ts pairs after one discarded ts,rust warm-up pair',
		summary,
		rustLoadChatStageMs: { n: loadChat.length, median: loadChat.length ? loadChat[Math.floor((loadChat.length - 1) / 2)] : null },
		rssIncrementPerReloadBytes: transitionIncrements(sequence.map((entry) => ({ arm: entry.arm, before: entry.sample.browserRssBeforeBytes, after: entry.sample.browserRssBytes }))),
		sequence: sequence.map((entry) => `${entry.warmUp ? 'w' : ''}${entry.arm}`).join(','),
		samples: pairs,
		send: send ? { sequence: send.sequence, samples: send.samples } : null,
	};
	if (send?.profile) await testInfo.attach('web-rust-core-send-profile.json', { body: JSON.stringify(send.profile, null, 2), contentType: 'application/json' });
	const table = markdownTable(summary);
	log('bench table\n' + table, { rustLoadChatStageMs: report.rustLoadChatStageMs, rssIncrementPerReloadBytes: report.rssIncrementPerReloadBytes });
	await testInfo.attach('web-rust-core-bench.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-bench.md', { body: table, contentType: 'text/markdown' });
	for (const metric of ['chatRenderedMs', 'embedReadyMs'] as const) {
		expect(summary[metric].pairs, `${metric}: usable pairs`).toBe(PAIRS);
	}
	// Approved gate: more than one WASM instance in a Rust load is an automatic failure (report is attached first).
	expect(maxRustWasm, 'at most one WASM instance per Rust load').toBeLessThanOrEqual(1);
}

module.exports = { runWebRustCoreBench, benchFailureDiagnostics, waitAllReady, HISTORY_OPT_OUT_KEY, skipWithoutCredentials, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY };
