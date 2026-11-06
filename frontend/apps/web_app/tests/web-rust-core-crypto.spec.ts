/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (crypto parity + benchmark; the UI is unchanged, the Playwright video is kept)
/**
 * Opt-in shared Rust core web crypto (VITE_OPENMATES_RUST_CORE=1 build).
 *
 * With the flag ON, the TS crypto modules (chat content, master-key Formats C/D,
 * chat/embed share blobs, short URLs, media, chat-key write guard) delegate to
 * shared Rust in the single shared Rust core Worker's `crypto` unit. No WASM runs
 * on the page; calls issued in the same task are one batch message and per-item
 * calls under one key are one bulk request (one WASM call for a list decrypt).
 *   1. A chat + audio embed created by the TS client code (CI archive fixture)
 *      decrypts after login with zero Rust decrypt failures.
 *   2. The TS-corpus vectors (packages/openmates-rust/tests/crypto_fixtures/
 *      ts_web_*.json) decrypt identically through Rust and through the original
 *      TS code in the same page; Rust- and TS-written chat content reads back
 *      through the original TS reader.
 *   3. Benchmark: 1000 TS-encrypted messages decrypted and re-encrypted + chat-key
 *      unwraps with the real master key, TS vs Rust in the same browser run (wall,
 *      renderer CPU, RSS, Worker census, main-thread WASM), plus a sequential
 *      cost attribution (round trip vs WASM AES vs key import), recorded as an
 *      attachment. Census gate: exactly one Rust Worker, no web-crypto Worker and
 *      no WASM fetched by the page.
 *      PERF IS RECORDED, NOT GATED here (coordinator decision, round 4): every
 *      arm of this benchmark is an isolated page-to-Worker micro-op (sequential
 *      single decrypt, parallel list decrypt/encrypt, master-key unwrap ms/op,
 *      renderer CPU). Each pays a page->Worker hop the TS main-thread code does
 *      not have (the recorded empty-echo list round trip alone is about the TS
 *      list decrypt time). The user-facing gates (saved-chat open, embed ready,
 *      send/encrypt) live in web-rust-core-chat / web-rust-core-embeds and are
 *      strict on wall time, CPU and RSS. Correctness assertions stay strict.
 *   4. The pre-existing share link (created by the TS CLI) opens logged out.
 *   5. Logout clears the crypto unit's chat-key ciphers in the same page.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { openChatAfterContextSync } = require('./helpers/chat-hydration');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const ROOT = path.resolve(__dirname, '../../../..');
const FIXTURES = path.join(ROOT, 'packages/openmates-rust/tests/crypto_fixtures');
const readFixture = (name: string) => JSON.parse(fs.readFileSync(path.join(FIXTURES, name), 'utf8'));
const DECRYPT_FAILURE = /\[CryptoService\] (Chat decryption failed|Key fingerprint mismatch)|\[ShareEncryption\] Error decrypting|MediaEncryptionError/;
const MESSAGES = 1000;
// Unwraps per round: enough that the 0.1 ms page timer is ~0.2 us per unwrap.
const UNWRAPS = 500;
const ROUNDS = 5;
const MODES = ['parallel', 'sequential'] as const;
type Mode = (typeof MODES)[number];
const ARMS = ['ts', 'rust'] as const;
type Arm = (typeof ARMS)[number];
/** Reference target ratio recorded next to the micro-op numbers (not gated, see header). */
const MAX_RUST_TO_TS = 1.1;
/** Renderer CPU time is sampled in 10 ms ticks (recorded for reading the CPU ratio). */
const CPU_TICK_MS = 10;

type Stats = {
	calls: Record<string, number>; failures: Record<string, number>; fingerprintMismatches: number; workerErrors: number;
	batches: number; batchedRequests: number; bulkRequests: number; bulkItems: number; chatKeyClears: number;
};

async function chatKeyCacheSize(page: any): Promise<number> {
	return page.evaluate(async () => (await window.__openmatesRustCryptoProof!()).chatKeyCacheSize());
}

async function logoutViaMenu(page: any): Promise<void> {
	const settings = page.locator('[data-testid="settings-menu"].visible');
	if (!(await settings.isVisible().catch(() => false))) await page.getByTestId('profile-container').click();
	await expect(settings).toBeVisible({ timeout: 10000 });
	await page.getByRole('menuitem', { name: /logout|abmelden/i }).click();
	await expect(page.locator('[data-authenticated="true"]')).toHaveCount(0, { timeout: 15000 });
}

async function rustStats(page: any): Promise<Stats> {
	await expect.poll(() => page.evaluate(() => typeof window.__openmatesRustCryptoStats === 'function'), {
		timeout: 30000, message: 'Rust web crypto registered (flag build)'
	}).toBe(true);
	return page.evaluate(() => window.__openmatesRustCryptoStats!());
}

/** Renderer processes' CPU (includes Worker threads) and RSS when /proc is visible. */
async function rendererUsage(cdp: any): Promise<{ cpuMs: number; rssKb: number | null }> {
	const { processInfo } = await cdp.send('SystemInfo.getProcessInfo');
	let cpuMs = 0;
	let rssKb: number | null = null;
	for (const info of processInfo as { type: string; id: number; cpuTime: number }[]) {
		if (info.type !== 'renderer') continue;
		cpuMs += info.cpuTime * 1000;
		try {
			const status = fs.readFileSync(`/proc/${info.id}/status`, 'utf8') as string;
			const match = status.match(/VmRSS:\s+(\d+)/);
			if (match) rssKb = (rssKb ?? 0) + Number(match[1]);
		} catch {
			// Browser in another process namespace: RSS reported as null, never estimated.
		}
	}
	return { cpuMs, rssKb };
}

/** Exact case count runCorpus derives from the fixtures (mirrors webCryptoProof.runCorpus). */
function expectedCorpusCases(formats: any, policy: any): number {
	let n = formats.chat_content.length + 1 + 1 + policy.chat_content.length + formats.master_text.length + 1;
	for (const c of formats.share.chat) n += 1 + (c.password ? 2 : 0) + (c.duration_seconds > 0 ? 1 : 0);
	n += formats.share.embed.length + 1 + 2 + formats.media.cases.length + 1;
	return n;
}

const median = (values: number[]) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,chats.persistence.client-encrypted,chat-share-settings.shared-link-open,sdk.web.before-after-performance
test('TS-created chats, embeds and share links decrypt through the Rust web crypto core', async ({ page, browser }: { page: any; browser: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const sharedChatUrl = process.env.OPENMATES_CI_SHARED_CHAT_URL;
	if (!sharedChatUrl) throw new Error('Fresh shared-chat archive fixture is required');
	const archiveChatId = new URL(sharedChatUrl).pathname.match(/([0-9a-f-]{36})/)?.[1];
	expect(archiveChatId, 'archive chat id in share URL').toBeTruthy();
	const log = createSignupLogger('WEB_RUST_CORE_CRYPTO');
	const screenshot = createStepScreenshotter(log);
	const report: Record<string, unknown> = {};
	const failures: string[] = [];
	page.on('console', (msg: any) => { if (DECRYPT_FAILURE.test(msg.text())) failures.push(msg.text().slice(0, 300)); });

	// 1. Login; open the archive chat the TS client code encrypted (chat key wrapped
	//    with the master key, title + message under the chat key, audio embed).
	await loginToTestAccount(page, log, screenshot);
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
	// The archive fixture is not guaranteed to be in the sidebar's first page, so
	// select it by hash once the initial account sync can no longer replace it.
	await openChatAfterContextSync(page, archiveChatId!, testInfo);
	const audioEmbed = page.locator('[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="transcribe"]').first();
	await expect(audioEmbed).toBeVisible({ timeout: 45000 });
	await expect(audioEmbed).toHaveAttribute('data-status', 'finished', { timeout: 45000 });
	await expect(async () => {
		const text = (await audioEmbed.getByTestId('recording-preview').textContent())?.trim() ?? '';
		expect(text).toContain('synthetic archived voice memo');
	}).toPass({ timeout: 20000 });
	await screenshot(page, 'archive-chat-decrypted');
	const appStats = await rustStats(page);
	report.appStats = appStats;
	expect(appStats.calls.decryptChatContent ?? 0, 'chat content decrypted by Rust').toBeGreaterThan(0);
	expect(appStats.calls.masterDecrypt ?? 0, 'chat key unwrapped by Rust').toBeGreaterThan(0);
	expect(appStats.failures.decryptChatContent ?? 0).toBe(0);
	expect(appStats.failures.masterDecrypt ?? 0).toBe(0);
	expect(appStats.fingerprintMismatches).toBe(0);
	expect(appStats.workerErrors).toBe(0);
	expect(failures, 'no decrypt failure logged while opening TS data').toEqual([]);

	// 2. TS corpus through Rust and through the original TS code, same page.
	const corpus = await page.evaluate(
		async ({ formats, policy }: { formats: unknown; policy: unknown }) => (await window.__openmatesRustCryptoProof!()).runCorpus(formats as never, policy as never),
		{ formats: readFixture('ts_web_formats.json'), policy: readFixture('ts_web_policy.json') }
	);
	report.corpus = { cases: corpus.cases.length, failures: corpus.failures, failed: corpus.cases.filter((c: { ok: boolean }) => !c.ok) };
	expect(corpus.cases.length, 'every fixture vector ran').toBe(expectedCorpusCases(readFixture('ts_web_formats.json'), readFixture('ts_web_policy.json')));
	expect(corpus.cases.filter((c: { ok: boolean }) => !c.ok)).toEqual([]);

	// 3. Benchmark (same page, same run). Warm every arm with one full-size round
	// per mode (JIT and WASM tier-up for both paths), then alternate.
	const cdp = await browser.newBrowserCDPSession();
	report.benchmarkFixture = await page.evaluate(async (count: number) => (await window.__openmatesRustCryptoProof!()).prepareBenchmark(count), MESSAGES);
	const rounds: Record<string, unknown>[] = [];
	const statsBeforeBenchmark = await rustStats(page);
	for (const mode of MODES) {
		for (const arm of ARMS) {
			await page.evaluate(async ({ a, m, u }: { a: Arm; m: Mode; u: number }) =>
				(await window.__openmatesRustCryptoProof!()).runBenchmarkArm(a, m, u), { a: arm, m: mode, u: UNWRAPS });
		}
		for (let round = 0; round < ROUNDS; round += 1) {
			// Rotate the arm order every round so no arm always runs first.
			const order = ARMS.map((_, index) => ARMS[(index + round) % ARMS.length]);
			for (const arm of order) {
				const before = await rendererUsage(cdp);
				const wallStart = Date.now();
				const result = await page.evaluate(async ({ a, m, u }: { a: Arm; m: Mode; u: number }) =>
					(await window.__openmatesRustCryptoProof!()).runBenchmarkArm(a, m, u), { a: arm, m: mode, u: UNWRAPS });
				const wallMs = Date.now() - wallStart;
				const after = await rendererUsage(cdp);
				const mainHeapBytes = await page.evaluate(async () => (await window.__openmatesRustCryptoProof!()).mainHeapBytes());
				expect(result.failures, `${arm} ${mode} benchmark decrypt failures`).toBe(0);
				rounds.push({ ...result, round, wallMs, cpuMs: after.cpuMs - before.cpuMs, rssKb: after.rssKb, mainHeapBytes });
			}
		}
	}
	const summary: Record<string, unknown> = {};
	for (const mode of MODES) {
		for (const arm of ARMS) {
			const rows = rounds.filter((row) => row.mode === mode && row.arm === arm) as Record<string, number>[];
			summary[`${mode}.${arm}`] = {
				decryptMs: median(rows.map((row) => row.decryptMs)),
				encryptMs: median(rows.map((row) => row.encryptMs)),
				unwrapMsPer: median(rows.map((row) => row.unwrapMs)) / UNWRAPS,
				cpuMs: median(rows.map((row) => row.cpuMs)),
				rssKb: rows.at(-1)?.rssKb ?? null,
				mainHeapBytes: rows.at(-1)?.mainHeapBytes ?? null
			};
		}
	}
	// Where the sequential Rust time goes: page<->Worker round trip, Rust stages
	// and WebCrypto import/decrypt inside the Worker.
	summary.profile = await page.evaluate(async (reps: number) =>
		(await window.__openmatesRustCryptoProof!()).profileDecrypt(reps), 5);
	const statsAfterBenchmark = await rustStats(page);
	// Rust core instance census for this page: one WASM instance per Rust Worker,
	// none on the page.
	const { targetInfos } = await cdp.send('Target.getTargets');
	const workers = (targetInfos as { type: string; title: string; url: string }[])
		.filter((target) => target.type === 'worker')
		.map((target) => `${target.title} ${target.url}`);
	const mainThreadWasm = await page.evaluate(async () => (await window.__openmatesRustCryptoProof!()).mainThreadWasmResources());
	summary.instances = { workers, workerCount: workers.length, mainThreadWasm };
	report.benchmark = { messages: MESSAGES, unwraps: UNWRAPS, rounds: ROUNDS, summary, rows: rounds, statsAfterBenchmark };
	await cdp.detach();
	log('benchmark', summary);
	// Attached before the assertions so a failing run still records its numbers.
	await testInfo.attach('web-rust-core-crypto-benchmark-only.json', { body: JSON.stringify(report.benchmark, null, 2), contentType: 'application/json' });
	// One shared Rust Worker holds the crypto unit; no dedicated web-crypto Worker, no page WASM.
	expect(workers.filter((name) => /openmates-rust-shared|shared\.worker/.test(name)), 'one shared Rust core Worker').toHaveLength(1);
	expect(workers.filter((name) => /openmates-rust-web-crypto|webCrypto\.worker/.test(name)), 'no dedicated web crypto Worker').toEqual([]);
	expect(mainThreadWasm, 'no WASM instantiated on the page').toEqual([]);
	// Same-task calls were batched and same-key items coalesced into bulk requests.
	expect(statsAfterBenchmark.bulkItems - statsBeforeBenchmark.bulkItems).toBeGreaterThanOrEqual(MESSAGES * ROUNDS * 2);
	// Recorded, not gated (see the header): isolated page->Worker micro-ops,
	// reported as Rust/TS ratios next to the raw medians.
	{
		const ratios: Record<string, Record<string, number | null>> = {};
		for (const mode of MODES) {
			const ts = summary[`${mode}.ts`] as Record<string, number>;
			const rust = summary[`${mode}.rust`] as Record<string, number>;
			ratios[mode] = Object.fromEntries((['decryptMs', 'encryptMs', 'unwrapMsPer', 'cpuMs'] as const)
				.map((metric) => [metric, ts[metric] > 0 ? rust[metric] / ts[metric] : null]));
		}
		report.recordedMicroOps = { ratios, targetRatio: MAX_RUST_TO_TS, cpuTickMs: CPU_TICK_MS };
		log('recorded micro-ops (not gated)', report.recordedMicroOps);
	}
	// The corpus (step 2) deliberately records failures for its negative vectors;
	// the benchmark itself must add none.
	const failuresDuring = (op: string) => (statsAfterBenchmark.failures[op] ?? 0) - (statsBeforeBenchmark.failures[op] ?? 0);
	expect(failuresDuring('decryptChatContent'), 'benchmark chat decrypt failures').toBe(0);
	expect(failuresDuring('masterDecrypt'), 'benchmark unwrap failures').toBe(0);
	expect(statsAfterBenchmark.workerErrors).toBe(0);

	// 4. Logged out: the share link created by the TS CLI opens via the Rust share reader.
	const visitor = await browser.newContext();
	const shared = await visitor.newPage();
	const visitorFailures: string[] = [];
	shared.on('console', (msg: any) => { if (DECRYPT_FAILURE.test(msg.text())) visitorFailures.push(msg.text().slice(0, 300)); });
	await shared.goto(sharedChatUrl);
	await expect(shared).toHaveURL(/#chat-id=/, { timeout: 45000 });
	await expect(shared.getByTestId('chat-header-banner').getByTestId('shared-chat-badge')).toHaveText('Shared chat', { timeout: 45000 });
	const sharedEmbed = shared.locator('[data-testid="embed-preview"][data-app-id="audio"][data-skill-id="transcribe"]').first();
	await expect(sharedEmbed).toBeVisible({ timeout: 45000 });
	await expect(async () => {
		const text = (await sharedEmbed.getByTestId('recording-preview').textContent())?.trim() ?? '';
		expect(text).toContain('synthetic archived voice memo');
	}).toPass({ timeout: 20000 });
	await screenshot(shared, 'share-link-opened');
	const shareStats = await rustStats(shared);
	report.shareStats = shareStats;
	expect(shareStats.calls.decryptShareKeyBlob ?? 0, 'share blob read by Rust').toBeGreaterThan(0);
	expect(shareStats.failures.decryptShareKeyBlob ?? 0).toBe(0);
	expect(shareStats.failures.decryptChatContent ?? 0).toBe(0);
	expect(visitorFailures).toEqual([]);
	await visitor.close();

	// 5. Logout drops every cached chat-key cipher of the crypto unit in this same page.
	const cachesBeforeLogout = await chatKeyCacheSize(page);
	expect(cachesBeforeLogout, 'crypto unit chat-key ciphers cached before logout').toBeGreaterThan(0);
	const clearsBeforeLogout = (await rustStats(page)).chatKeyClears;
	await logoutViaMenu(page);
	await expect.poll(async () => chatKeyCacheSize(page), { timeout: 10000, message: 'Rust chat-key caches empty after logout' })
		.toBe(0);
	const statsAfterLogout = await rustStats(page);
	// Same page (no reload): the counter proves the logout path itself cleared them.
	expect(statsAfterLogout.chatKeyClears, 'clearChatKeys ran on logout').toBeGreaterThan(clearsBeforeLogout);
	report.logoutChatKeyCaches = { before: cachesBeforeLogout, after: await chatKeyCacheSize(page), clears: statsAfterLogout.chatKeyClears - clearsBeforeLogout };
	await screenshot(page, 'logged-out-chat-key-caches-cleared');

	log('benchmark', summary);
	await testInfo.attach('web-rust-core-crypto-benchmark.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
});
