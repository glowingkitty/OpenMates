/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page handles are untyped in these CommonJS specs. */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Paired send flow of the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench-run.ts). Engineering measurement, not a product flow.
 *
 * Each sample cold-reloads `/`, opens a fresh chat and sends one mocked message
 * from the normal composer. The TS arm opts out of the Rust history source and the
 * Rust crypto unit (the same measurement-only keys web-rust-core-chat.spec.ts
 * uses); the Rust arm routes crypto through the shared Rust Worker. Per sample:
 *   sendToAdmitMs   last composer send gesture -> first encrypted `chat_turn_admit` frame
 *   browserCpuMs    stable reported browser-process CPU over the same window
 *   phases          the app's send-preparation phase marks (ms after the gesture)
 *   cryptoCalls     Rust crypto unit calls/batches/memo hits during the send (Rust arm)
 * Samples run in the bench's ABBA order (pairOrder) after one discarded warm-up
 * pair. Every send adds one chat to the account, so later sends are slower in both
 * arms; ABBA counterbalancing cancels that linear drift in the paired ratios.
 * With `profile`, one extra TS/Rust send pair runs under bench-profile.ts after the
 * measured pairs and its attribution is returned (never inside the verdicts).
 */
export {};

const { expect } = require('./cookie-audit');
const { getE2EDebugUrl, withMockMarker } = require('../signup-flow-helpers');
const { sendMessage, waitForChatReady, focusMessageEditor } = require('./chat-test-helpers');
const { summarizePaired, pairOrder } = require('./bench-stats');
const { createBenchProfiler } = require('./bench-profile');

const HISTORY_OPT_OUT_KEY = 'openmates_rust_core_history';
const CRYPTO_OPT_OUT_KEY = 'openmates_rust_core_crypto';
/** sessionStorage switch of recordSendPreparationPhase (chatSyncService.ts). */
const SEND_PREP_TIMING_KEY = 'openmates:send-prep-timing';

/** In-page (init script): send gesture and first admission frame timestamps. */
function installSendTiming(): void {
	const timing = { starts: [] as number[], admitAt: null as number | null };
	(window as unknown as { __benchSendTiming: typeof timing }).__benchSendTiming = timing;
	const markStart = (event: Event) => {
		const target = event.target as Element | null;
		if (event.type === 'custom-send-message' || target?.closest?.('[data-testid="composer-send-button"]')) timing.starts.push(performance.now());
	};
	document.addEventListener('click', markStart, true);
	document.addEventListener('custom-send-message', markStart, true);
	const nativeSend = WebSocket.prototype.send;
	WebSocket.prototype.send = function (data) {
		if (timing.admitAt === null && typeof data === 'string' && data.includes('"chat_turn_admit"')) timing.admitAt = performance.now();
		return nativeSend.call(this, data);
	};
}

type Arm = 'ts' | 'rust';

async function sendSample(page: any, arm: Arm, index: number, ctx: { processes: any; log: any; screenshot: any; profiler?: any }): Promise<Record<string, any>> {
	await page.evaluate(([keys, ts, prepKey]: [string[], boolean, string]) => {
		for (const key of keys) { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); }
		sessionStorage.setItem(prepKey, '1');
	}, [[HISTORY_OPT_OUT_KEY, CRYPTO_OPT_OUT_KEY], arm === 'ts', SEND_PREP_TIMING_KEY]);
	await page.goto(getE2EDebugUrl('/'));
	await page.reload();
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	// Same settle as web-rust-core-chat.spec.ts: post-login sync, then a fresh chat.
	await page.waitForTimeout(3000);
	const button = page.getByTestId('new-chat-button');
	if (await button.isVisible()) { await button.click(); await page.waitForTimeout(2000); }
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	await waitForChatReady(page, ctx.log);
	// Prime the draft before the measured gesture: the first typed text creates the
	// draft chat, whose saved model preference then restores. A click racing that
	// restore is rejected by the composer ("owner changed during model restoration"),
	// so the measured send starts only once the draft chat and its model are settled.
	await focusMessageEditor(page.getByTestId('message-editor'));
	await page.keyboard.insertText('Please');
	await expect.poll(() => page.evaluate(() => {
		const draft = (window as any).__openmatesE2EDraftState?.();
		return Boolean(draft?.currentChatId) && draft.isSaveInProgress === false;
	}), { timeout: 30000, message: `${arm}: primed draft chat saved` }).toBe(true);
	await expect(page.getByTestId('composer-model-selector')).toHaveAttribute('data-loading', 'false', { timeout: 15000 });
	const cryptoBefore = await page.evaluate(() => {
		const timing = (window as any).__benchSendTiming;
		timing.starts = []; timing.admitAt = null;
		(window as any).__openmatesSendPrepPhases = [];
		return (window as any).__openmatesRustCryptoStats?.() ?? null;
	});
	await ctx.processes.begin();
	if (ctx.profiler) await ctx.profiler.begin();
	await sendMessage(page, withMockMarker(` explain how roots take up water, bench run ${index}.`, 'chat_flow_capital', 'fast'), ctx.log, ctx.screenshot, `bench-${arm}-send-${index}`, { preserveExistingContent: true });
	await expect.poll(() => page.evaluate(() => (window as any).__benchSendTiming.admitAt), { timeout: 30000, message: `${arm}: encrypted admission frame sent` }).not.toBeNull();
	const profile = ctx.profiler ? await ctx.profiler.end() : undefined;
	const process = await ctx.processes.end();
	const inPage = await page.evaluate(() => ({
		timing: (window as any).__benchSendTiming,
		phases: (window as any).__openmatesSendPrepPhases ?? [],
		crypto: (window as any).__openmatesRustCryptoStats?.() ?? null
	}));
	const start = inPage.timing.starts.filter((value: number) => value <= inPage.timing.admitAt).at(-1);
	expect(start, `${arm}: send gesture recorded before admission`).toBeDefined();
	const phases = Object.fromEntries(inPage.phases.filter((entry: any) => entry.ms >= start)
		.map((entry: any) => [entry.phase, Math.round((entry.ms - start) * 10) / 10]));
	const calls = (stats: any) => stats ? Object.values(stats.calls as Record<string, number>).reduce((sum, value) => sum + value, 0) : 0;
	const sample: Record<string, any> = {
		arm,
		sendToAdmitMs: inPage.timing.admitAt - start,
		browserCpuMs: process.available ? process.stableReportedProcessCpuMs : null,
		phases,
		cryptoCalls: inPage.crypto ? calls(inPage.crypto) - calls(cryptoBefore) : null,
		cryptoBatches: inPage.crypto ? inPage.crypto.batches - (cryptoBefore?.batches ?? 0) : null,
		cryptoMemoHits: inPage.crypto ? (inPage.crypto.memoHits ?? 0) - (cryptoBefore?.memoHits ?? 0) : null,
		cryptoOps: inPage.crypto ? Object.fromEntries(Object.entries(inPage.crypto.calls as Record<string, number>)
			.map(([op, count]) => [op, count - (cryptoBefore?.calls?.[op] ?? 0)]).filter(([, count]) => (count as number) > 0)) : null
	};
	if (profile) sample.profile = profile;
	if (arm === 'rust') expect(inPage.crypto, 'Rust arm: crypto ran through the Rust unit').not.toBeNull();
	else expect(inPage.crypto, 'TS arm: Rust crypto unit not installed').toBeNull();
	// Settle the turn before the next reload so the reply never overlaps the next sample.
	await expect(page.getByTestId('message-assistant').last()).toBeVisible({ timeout: 60000 });
	await expect(page.getByTestId('message-user').last()).toContainText('roots take up water');
	return sample;
}

/**
 * Runs `pairs` ABBA-ordered TS/Rust send pairs (plus one warm-up) on `page` and
 * returns the paired verdicts and samples. Leaves both opt-out keys removed.
 */
async function runSendBench(page: any, options: { pairs: number; margin: number; processes: any; log: any; screenshot: any; profile: boolean }): Promise<Record<string, any>> {
	await page.addInitScript(installSendTiming);
	const pairs: { ts: Record<string, any>; rust: Record<string, any> }[] = [];
	const sequence: string[] = [];
	let profiled: Record<string, any> | null = null;
	let index = 0;
	try {
		for (; index <= options.pairs; index += 1) {
			const pair: Record<string, Record<string, any>> = {};
			for (const arm of pairOrder(index)) {
				pair[arm] = await sendSample(page, arm, index, options);
				sequence.push(`${index === 0 ? 'w' : ''}${arm}`);
			}
			if (index === 0) continue;
			pairs.push({ ts: pair.ts, rust: pair.rust });
			options.log('send pair', { index, ts: pair.ts.sendToAdmitMs, rust: pair.rust.sendToAdmitMs, tsCpu: pair.ts.browserCpuMs, rustCpu: pair.rust.browserCpuMs });
		}
		if (options.profile) {
			const profiler = await createBenchProfiler(page);
			try {
				profiled = {};
				for (const arm of ['ts', 'rust'] as const) profiled[arm] = await sendSample(page, arm, index++, { ...options, profiler });
			} finally {
				await profiler.close();
			}
		}
	} finally {
		await page.evaluate((keys: string[]) => { for (const key of keys) localStorage.removeItem(key); }, [HISTORY_OPT_OUT_KEY, CRYPTO_OPT_OUT_KEY]).catch(() => undefined);
	}
	const column = (metric: string) => pairs.map((pair) => ({ ts: pair.ts[metric], rust: pair.rust[metric] }));
	return {
		summary: {
			sendToAdmitMs: summarizePaired(column('sendToAdmitMs'), { mode: 'ratio', margin: options.margin }),
			sendBrowserCpuMs: summarizePaired(column('browserCpuMs'), { mode: 'ratio', margin: options.margin })
		},
		sequence: sequence.join(','),
		samples: pairs,
		profile: profiled
	};
}

module.exports = { runSendBench };
