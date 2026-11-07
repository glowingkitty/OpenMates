/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Send/stream entry of the interleaved TS-vs-Rust web benchmark
 * (VITE_OPENMATES_RUST_CORE=1 build, web-rust-core-* CI lane). Engineering
 * measurement, not a product flow: logs in once, then runs only the paired send
 * flow of helpers/web-rust-core-bench-send.ts (ABBA-ordered pairs after one discarded
 * warm-up pair, PAIRS_PER_JOB below) with the per-phase send-preparation marks.
 * Verdict per the approved budget: wall within
 * max(+10%, +50 ms), p95 at most +100 ms slower, CPU within +15% (paired 95% CI,
 * bench-stats.ts). One extra profiled TS/Rust pair after the measured pairs
 * is always attached as web-rust-core-send-profile.json (never inside the verdicts).
 * Attached as web-rust-core-send-bench.json plus a markdown table.
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { createBrowserProcessEvidence } = require('./helpers/browser-process-evidence.cjs');
const { markdownTable } = require('./helpers/bench-stats');
const { runSendBench } = require('./helpers/web-rust-core-bench-send');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const MARGIN = 0.1;
/**
 * Pairs per job. Sends in one account stop being accepted after about 14 chats in a run
 * (observed with both arms, job 3fb38d57), so one job takes 5 pairs + the warm-up pair +
 * the 2 profile sends = 14 sends; submit the same source with `--attempt 1..3` (fresh
 * accounts) and combine the paired samples for the 12-pair verdict.
 */
const PAIRS_PER_JOB = 5;

// contract-test: tooling

test('interleaved TS vs Rust send benchmark with paired bootstrap verdicts', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(2400000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_CORE_SEND_BENCH');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	page.on('console', (msg: any) => { consoleLines.push(`[${msg.type()}] ${msg.text()}`.slice(0, 400)); });
	page.on('pageerror', (error: Error) => { consoleLines.push(`[pageerror] ${error.message}`.slice(0, 400)); });
	await loginToTestAccount(page, log, screenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	const processes = await createBrowserProcessEvidence(page);
	const pairs = PAIRS_PER_JOB;
	let send: Record<string, any>;
	try {
		send = await runSendBench(page, { pairs, margin: MARGIN, processes, log, screenshot, profile: true });
	} catch (error) {
		console.log('--- browser console (last 40) ---\n' + consoleLines.slice(-40).join('\n'));
		console.log('--- browser console (rust/403/unit/send, last 80) ---\n' + consoleLines.filter((line) => /403|Forbidden|retire|unit_|Rust|rust|crash|send_failed|pageerror/i.test(line)).slice(-80).join('\n'));
		throw error;
	} finally {
		await processes.close();
	}
	const table = markdownTable(send.summary);
	log('send bench table\n' + table, { sequence: send.sequence });
	if (send.profile) await testInfo.attach('web-rust-core-send-profile.json', { body: JSON.stringify(send.profile, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-send-bench.json', { body: JSON.stringify({ pairs, margin: MARGIN, summary: send.summary, phaseDeltas: send.phaseDeltas, failures: send.failures, sequence: send.sequence, samples: send.samples }, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-send-bench.md', { body: table, contentType: 'text/markdown' });
	expect(send.summary.sendToAdmitMs.pairs, 'send pairs usable').toBe(pairs);
});
