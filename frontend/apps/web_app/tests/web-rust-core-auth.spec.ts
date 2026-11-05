/* eslint-disable @typescript-eslint/no-require-imports */
// proof-video: not_required reason=visual_smoke_not_needed (request/cookie parity; the UI is unchanged, the Playwright video is kept)
/**
 * Web login, session restore and logout through the shared Rust core
 * (VITE_OPENMATES_RUST_CORE=1 build, CI lane web-rust-core-*).
 *
 * One build, two arms on the same account: `localStorage.openmates_rust_auth=ts`
 * selects the deployed TypeScript path, no override selects Rust. For each arm:
 *   1. password + OTP login (the real two-submit 2FA flow),
 *   2. cold reload: session restore,
 * then logout. The /v1/auth/* request sequence (method, path, headers, body
 * field order and non-secret values) and the resulting cookies must be equal.
 * The Rust arm also logs out with two tabs open: the second tab must drop its
 * session with no second server request (cross-tab invalidation).
 * A JSON attachment records login wall time, time to usable chat, restore time,
 * main-thread CPU and heap per arm.
 */
export {};

const { test, expect, assertNoThirdPartyCookies, cookieAttributeShape } = require('./helpers/cookie-audit');
const { skipWithoutCredentials } = require('./helpers/env-guard');
const { createSignupLogger, createStepScreenshotter, getTestAccount, getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');

const { email: TEST_EMAIL, password: TEST_PASSWORD, otpKey: TEST_OTP_KEY } = getTestAccount();
const SELECT_KEY = 'openmates_rust_auth';
// Values that are not secret and define the request shape; everything else is compared by key only.
const STATIC_BODY_FIELDS = new Set(['purpose', 'login_method', 'credential_version', 'code_type', 'stay_logged_in']);
const COMPARED_HEADERS = ['content-type', 'accept', 'origin'];
const RESTORE_SAMPLES = 3;

interface AuthRequestShape { method: string; path: string; headers: Record<string, string>; body: unknown }

function shapeBody(text: string | null): unknown {
	if (text === null) return null;
	let parsed: unknown;
	try { parsed = JSON.parse(text); } catch { return 'non-json'; }
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return typeof parsed;
	return Object.entries(parsed as Record<string, unknown>).map(([key, value]) => {
		if (STATIC_BODY_FIELDS.has(key)) return [key, value];
		if (value && typeof value === 'object' && !Array.isArray(value)) return [key, Object.keys(value as object)];
		return [key, value === null ? 'null' : typeof value];
	});
}

const NAVIGATION = 'NAVIGATION';

/** Requests of the last document load only: a login helper retry reloads the page and starts over. */
function lastDocument(list: AuthRequestShape[]): AuthRequestShape[] {
	return list.slice(list.map((entry) => entry.method).lastIndexOf(NAVIGATION) + 1);
}

function withoutNavigations(list: AuthRequestShape[]): AuthRequestShape[] {
	return list.filter((entry) => entry.method !== NAVIGATION);
}

/**
 * Waits until no /v1/auth/* request is in flight and none started for a quiet
 * period, so background follow-ups (e.g. sessions/register-meta after a
 * session check) land in the phase that caused them, in both arms.
 */
function trackAuthNetwork(page: any): (page: any) => Promise<void> {
	let inFlight = 0;
	let lastActivity = Date.now();
	const isAuth = (request: any) => new URL(request.url()).pathname.startsWith('/v1/auth/');
	page.on('request', (request: any) => { if (isAuth(request)) { inFlight++; lastActivity = Date.now(); } });
	const done = (request: any) => { if (isAuth(request)) { inFlight = Math.max(0, inFlight - 1); lastActivity = Date.now(); } };
	page.on('requestfinished', done);
	page.on('requestfailed', done);
	return async (target: any) => {
		const deadline = Date.now() + 20000;
		while (inFlight > 0 || Date.now() - lastActivity < 1500) {
			if (Date.now() > deadline) throw new Error(`auth requests did not settle (${inFlight} in flight)`);
			await target.waitForTimeout(250);
		}
	};
}

function recordAuthRequests(page: any, into: () => AuthRequestShape[]): void {
	page.on('framenavigated', (frame: any) => {
		if (frame === page.mainFrame()) into().push({ method: NAVIGATION, path: '', headers: {}, body: null });
	});
	page.on('request', (request: any) => {
		const url = new URL(request.url());
		if (!url.pathname.startsWith('/v1/auth/')) return;
		const headers = request.headers();
		into().push({
			method: request.method(),
			path: url.pathname,
			headers: Object.fromEntries(COMPARED_HEADERS.filter((name) => name in headers).map((name) => [name, headers[name]])),
			body: shapeBody(request.postData()),
		});
	});
}

/** Marks when the app reports authenticated / usable chat, and every login submit click (page clock). */
/**
 * Records every WebAssembly memory instantiated on the page's main thread
 * (Worker instances are not visible here), so main-thread WASM bytes can be
 * reported next to the JS heap.
 */
async function installWasmMemoryProbe(page: any): Promise<void> {
	await page.addInitScript(() => {
		const memories = new Set<WebAssembly.Memory>();
		(window as unknown as { __wasmMemories: Set<WebAssembly.Memory> }).__wasmMemories = memories;
		const track = (instance: WebAssembly.Instance) => {
			for (const value of Object.values(instance.exports)) if (value instanceof WebAssembly.Memory) memories.add(value);
			return instance;
		};
		const wasm = WebAssembly as unknown as Record<string, unknown>;
		const instantiate = WebAssembly.instantiate.bind(WebAssembly);
		wasm.instantiate = async (...args: unknown[]) => {
			const result = await (instantiate as (...a: unknown[]) => Promise<unknown>)(...args);
			track(result instanceof WebAssembly.Instance ? result : (result as { instance: WebAssembly.Instance }).instance);
			return result;
		};
		const streaming = WebAssembly.instantiateStreaming?.bind(WebAssembly);
		if (streaming) {
			wasm.instantiateStreaming = async (...args: unknown[]) => {
				const result = await (streaming as (...a: unknown[]) => Promise<{ instance: WebAssembly.Instance }>)(...args);
				track(result.instance);
				return result;
			};
		}
		const NativeInstance = WebAssembly.Instance;
		wasm.Instance = new Proxy(NativeInstance, { construct: (target, args) => track(Reflect.construct(target, args)) });
	});
}

async function mainThreadWasmBytes(page: any): Promise<number> {
	return page.evaluate(() => {
		let total = 0;
		for (const memory of (window as unknown as { __wasmMemories?: Set<WebAssembly.Memory> }).__wasmMemories ?? []) total += memory.buffer.byteLength;
		return total;
	});
}

/** Main-thread JS heap after a forced full GC (garbage awaiting collection would otherwise dominate). */
async function heapAfterGc(cdp: any): Promise<number> {
	await cdp.send('HeapProfiler.collectGarbage');
	const { metrics } = await cdp.send('Performance.getMetrics');
	return metrics.find((metric: { name: string }) => metric.name === 'JSHeapUsedSize')?.value ?? NaN;
}

async function installTimingProbe(page: any): Promise<void> {
	await page.addInitScript(() => {
		const marks: Record<string, number | number[]> = { submits: [] };
		(window as unknown as { __authMarks: typeof marks }).__authMarks = marks;
		document.addEventListener('click', (event) => {
			const target = event.target as Element | null;
			if (target?.closest?.('[data-testid="login-submit-button"]')) (marks.submits as number[]).push(performance.now());
		}, true);
		const check = () => {
			if (marks.authenticated === undefined && document.querySelector('[data-authenticated="true"]')) marks.authenticated = performance.now();
			if (marks.editor === undefined && marks.authenticated !== undefined && document.querySelector('[data-testid="message-editor"]')) marks.editor = performance.now();
		};
		new MutationObserver(check).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-authenticated'] });
	});
}

async function marks(page: any): Promise<{ submits: number[]; authenticated?: number; editor?: number }> {
	return page.evaluate(() => (window as unknown as { __authMarks: { submits: number[]; authenticated?: number; editor?: number } }).__authMarks);
}

async function cpuMetrics(cdp: any): Promise<Record<string, number>> {
	const { metrics } = await cdp.send('Performance.getMetrics');
	const pick = new Set(['TaskDuration', 'ScriptDuration', 'JSHeapUsedSize']);
	return Object.fromEntries(metrics.filter((metric: { name: string }) => pick.has(metric.name)).map((metric: { name: string; value: number }) => [metric.name, metric.value]));
}

/** CDP counters restart with a new document after reload; count from zero then. */
function cpuDelta(before: Record<string, number>, after: Record<string, number>, metric: string): number {
	const end = after[metric] ?? 0;
	const start = before[metric] ?? 0;
	return Math.round((end >= start ? end - start : end) * 1000);
}

function median(values: number[]): number {
	const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
	if (!sorted.length) return NaN;
	const middle = Math.floor(sorted.length / 2);
	return Math.round(sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2);
}

/** Empties the app origin (cookies, storage, IndexedDB) without booting the app, then selects the arm. */
async function startCleanArm(page: any, context: any, selector: string | null): Promise<void> {
	await context.clearCookies();
	await page.goto('/robots.txt'); // a static file on the app origin: storage access without starting the app
	await page.evaluate(async ([key, value]: [string, string | null]) => {
		localStorage.clear();
		sessionStorage.clear();
		const databases = await indexedDB.databases();
		await Promise.all(databases.map((database) => new Promise<void>((resolve, reject) => {
			if (!database.name) { resolve(); return; }
			const request = indexedDB.deleteDatabase(database.name);
			request.onsuccess = () => resolve();
			request.onerror = () => reject(request.error);
			request.onblocked = () => reject(new Error(`database ${database.name} is still open`));
		})));
		if (value !== null) localStorage.setItem(key, value);
	}, [SELECT_KEY, selector]);
}

async function openSettings(page: any): Promise<void> {
	const settings = page.locator('[data-testid="settings-menu"].visible');
	if (!(await settings.isVisible().catch(() => false))) await page.getByTestId('profile-container').click();
	await expect(settings).toBeVisible({ timeout: 10000 });
}

async function logoutViaMenu(page: any): Promise<void> {
	await openSettings(page);
	await page.getByRole('menuitem', { name: /logout|abmelden/i }).click();
	await expect(page.locator('[data-authenticated="true"]')).toHaveCount(0, { timeout: 15000 });
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,sdk.web.before-after-performance
test('Rust login, restore and logout match the TypeScript requests and cookies', async ({ page, context }: { page: any; context: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	skipWithoutCredentials(test, TEST_EMAIL, TEST_PASSWORD, TEST_OTP_KEY);
	const log = createSignupLogger('WEB_RUST_AUTH');
	const screenshot = createStepScreenshotter(log);
	const consoleLines: string[] = [];
	const watchConsole = (target: any, tag: string) => target.on('console', (msg: any) => {
		if (/RustAuth|PasswordAndTfaOtp|AuthSession|AuthStore|Database/.test(msg.text())) consoleLines.push(`${tag}[${msg.type()}] ${msg.text()}`.slice(0, 400));
	});
	watchConsole(page, 'main');
	const workers: string[] = [];
	page.on('worker', (worker: any) => workers.push(worker.url()));
	await installTimingProbe(page);
	await installWasmMemoryProbe(page);
	const cdp = await context.newCDPSession(page);
	await cdp.send('Performance.enable');
	await cdp.send('HeapProfiler.enable');

	const report: Record<string, unknown> = { note: 'Main-thread CDP metrics; Worker CPU (Argon2 in both arms) is not included. TS arm runs first, so the Rust arm sees a warm HTTP cache for shared bundles.' };
	const sequences: Record<string, { login: AuthRequestShape[]; restore: AuthRequestShape[]; logout: AuthRequestShape[] }> = {};
	const cookies: Record<string, string[]> = {};

	let requests: AuthRequestShape[] = [];
	recordAuthRequests(page, () => requests);
	const settleAuthNetwork = trackAuthNetwork(page);
	for (const arm of ['ts', 'rust'] as const) {
		// Both arms start from the same empty origin: no cookies, storage or databases
		// left by the previous arm (e.g. its pending logout cleanup marker). The
		// selector is set before the app boots so start-up already uses this arm's path.
		await startCleanArm(page, context, arm === 'ts' ? 'ts' : null);
		requests = [];
		const workersBefore = workers.length;
		await page.goto(getE2EDebugUrl('/'));

		// 1. Password + OTP login.
		const cpuBefore = await cpuMetrics(cdp);
		await loginToTestAccount(page, log, screenshot);
		await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
		const loginMarks = await marks(page);
		const cpuAfter = await cpuMetrics(cdp);
		const lastSubmit = loginMarks.submits.at(-1) ?? NaN;
		await settleAuthNetwork(page);
		const loginRequests = lastDocument(requests.splice(0));
		// Heap after login with forced GC: once while the auth Worker may still be
		// up, once after its idle teardown (both arms wait the same time).
		const heapAfterLoginGc = await heapAfterGc(cdp);
		const wasmAfterLogin = await mainThreadWasmBytes(page);
		await page.waitForTimeout(5000);
		const heapAfterLoginIdleGc = await heapAfterGc(cdp);
		const wasmAfterLoginIdle = await mainThreadWasmBytes(page);
		await screenshot(page, `${arm}-logged-in`);

		// 2. Cold reloads: session restore (median of RESTORE_SAMPLES; the first one's requests are compared).
		const restoreSamples: { authenticated: number; editor: number; sessionChecked: number; domContentLoaded: number; taskMs: number; scriptMs: number; heap: number; heapGc: number; wasm: number }[] = [];
		let restoreRequests: AuthRequestShape[] = [];
		for (let sample = 0; sample < RESTORE_SAMPLES; sample++) {
			const before = await cpuMetrics(cdp);
			// Every restore must validate the session with the server; waiting for that
			// response also keeps a late check inside this sample's request capture.
			const sessionChecked = page.waitForResponse((response: any) => response.request().method() === 'POST'
				&& new URL(response.url()).pathname === '/v1/auth/session', { timeout: 30000 });
			await page.reload();
			await expect(page.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });
			await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 30000 });
			const sessionResponse = await sessionChecked;
			await sessionResponse.finished();
			const restoreMarks = await marks(page);
			// Session check done, relative to this document's navigation start (Playwright timing: epoch start + relative end).
			const sessionTiming = sessionResponse.request().timing();
			const timeOrigin = await page.evaluate(() => performance.timeOrigin);
			const sessionCheckedAt = sessionTiming.responseEnd >= 0 ? sessionTiming.startTime + sessionTiming.responseEnd - timeOrigin : NaN;
			const after = await cpuMetrics(cdp);
			const domContentLoaded = await page.evaluate(() => (performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming)?.domContentLoadedEventEnd ?? NaN);
			restoreSamples.push({
				authenticated: restoreMarks.authenticated ?? NaN,
				editor: restoreMarks.editor ?? NaN,
				sessionChecked: sessionCheckedAt,
				domContentLoaded,
				taskMs: cpuDelta(before, after, 'TaskDuration'),
				scriptMs: cpuDelta(before, after, 'ScriptDuration'),
				heap: after.JSHeapUsedSize ?? NaN,
				heapGc: await heapAfterGc(cdp),
				wasm: await mainThreadWasmBytes(page),
			});
			await settleAuthNetwork(page);
			const sampleRequests = withoutNavigations(requests.splice(0));
			if (sample === 0) restoreRequests = sampleRequests;
		}
		const restoreMedian = (key: keyof (typeof restoreSamples)[number]) => median(restoreSamples.map((sample) => sample[key]));
		cookies[arm] = await cookieAttributeShape(context);
		await assertNoThirdPartyCookies(context);

		const rustWorkers = workers.slice(workersBefore).filter((url) => /auth\.worker/.test(url));
		if (arm === 'rust') expect(rustWorkers.length, 'the Rust arm must run auth in the Rust auth Worker').toBeGreaterThan(0);
		else expect(rustWorkers, 'the TypeScript arm must not start the Rust auth Worker').toEqual([]);

		// 3. Logout (Rust arm: with a second tab that must follow).
		let peer: any = null;
		if (arm === 'rust') {
			peer = await context.newPage();
			watchConsole(peer, 'peer');
			// Diagnostic only: record cross-tab frames the peer receives.
			await peer.addInitScript(() => {
				const frames: string[] = [];
				(window as unknown as { __authFrames: string[] }).__authFrames = frames;
				new BroadcastChannel('openmates-auth-v1').onmessage = (event) => frames.push(String(event.data).slice(0, 200));
			});
			recordAuthRequests(peer, () => requests);
			await peer.goto(getE2EDebugUrl('/'));
			await expect(peer.locator('[data-authenticated="true"]')).toBeVisible({ timeout: 30000 });
			requests.splice(0); // the peer's own restore check is not part of the logout sequence
		}
		const logoutStarted = Date.now();
		const serverLogout = page.waitForResponse((response: any) => response.request().method() === 'POST'
			&& new URL(response.url()).pathname === '/v1/auth/logout', { timeout: 30000 });
		await logoutViaMenu(page);
		if (peer) {
			try {
				await expect(peer.locator('[data-authenticated="true"]'), 'the second tab must drop its session after logout in the first')
					.toHaveCount(0, { timeout: 15000 });
			} catch (error) {
				const frames = await peer.evaluate(() => (window as unknown as { __authFrames?: string[] }).__authFrames ?? []).catch(() => ['<unavailable>']);
				console.log(`cross-tab diagnostics: frames=${JSON.stringify(frames)} requests=${JSON.stringify(requests.map((r) => r.path))}`);
				console.log(consoleLines.slice(-80).join('\n'));
				throw error;
			}
			report.crossTabLogoutMs = Date.now() - logoutStarted;
			await screenshot(peer, 'rust-peer-logged-out');
		}
		await serverLogout; // the background server logout must reach the server
		await page.waitForTimeout(1000); // a second (duplicate) logout from either tab would arrive here
		const logoutRequests = requests.filter((request) => request.path.includes('logout'));
		if (peer) {
			// The peer only drops local state; it must not revoke a second time.
			expect(logoutRequests.length, 'exactly one server logout across both tabs').toBe(1);
			await peer.close();
		}
		sequences[arm] = { login: loginRequests, restore: restoreRequests, logout: logoutRequests };

		report[arm] = {
			loginWallMs: Math.round((loginMarks.authenticated ?? NaN) - lastSubmit),
			timeToUsableChatMs: Math.round((loginMarks.editor ?? NaN) - lastSubmit),
			restoreSamples: RESTORE_SAMPLES,
			restoreAuthenticatedMedianMs: restoreMedian('authenticated'),
			restoreUsableChatMedianMs: restoreMedian('editor'),
			restoreSessionCheckedMedianMs: restoreMedian('sessionChecked'),
			restoreSessionCheckedSamplesMs: restoreSamples.map((sample) => Math.round(sample.sessionChecked)),
			restoreDomContentLoadedMedianMs: restoreMedian('domContentLoaded'),
			restoreAuthenticatedSamplesMs: restoreSamples.map((sample) => Math.round(sample.authenticated)),
			loginMainThreadTaskMs: cpuDelta(cpuBefore, cpuAfter, 'TaskDuration'),
			loginMainThreadScriptMs: cpuDelta(cpuBefore, cpuAfter, 'ScriptDuration'),
			restoreMainThreadTaskMedianMs: restoreMedian('taskMs'),
			restoreMainThreadScriptMedianMs: restoreMedian('scriptMs'),
			heapAfterLoginBytes: cpuAfter.JSHeapUsedSize ?? null,
			heapAfterLoginGcBytes: heapAfterLoginGc,
			heapAfterLoginIdleGcBytes: heapAfterLoginIdleGc,
			mainThreadWasmAfterLoginBytes: wasmAfterLogin,
			mainThreadWasmAfterLoginIdleBytes: wasmAfterLoginIdle,
			heapAfterRestoreMedianBytes: restoreMedian('heap'),
			heapAfterRestoreGcMedianBytes: restoreMedian('heapGc'),
			mainThreadWasmAfterRestoreMedianBytes: restoreMedian('wasm'),
			authWorkers: rustWorkers.length,
		};
		log(`${arm} arm done`, report[arm] as Record<string, unknown>);
	}

	await testInfo.attach('web-rust-core-auth-timings.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-auth-requests.json', { body: JSON.stringify({ sequences, cookies }, null, 2), contentType: 'application/json' });
	if (consoleLines.length) console.log(consoleLines.slice(-60).join('\n'));

	// Parity: identical requests (order, method, path, headers, body shape) and cookies.
	expect(sequences.rust.login.length, 'password + OTP login must reach the server').toBeGreaterThan(0);
	expect(sequences.rust.login).toEqual(sequences.ts.login);
	expect(sequences.rust.restore).toEqual(sequences.ts.restore);
	expect(sequences.rust.logout).toEqual(sequences.ts.logout);
	expect(cookies.rust).toEqual(cookies.ts);
});
