/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Opt-in shared Rust core (WASM) — Apps skill execution policy on the shared
 * Worker `apps` unit, VITE_OPENMATES_RUST_CORE=1 build.
 *
 * Engineering migration check (web lane: apps). A guest runs the natural-language
 * Web search request of apps-workspace.spec.ts (fixture interpreter, details,
 * request quote and provider response): the result fullscreen must show both
 * results. Alternating reloads run the same request on the TypeScript policy
 * (measurement opt-out `openmates_rust_core_apps=ts`) and on the Rust unit; the
 * Rust arm must route its decisions through the unit (stats hook): skill
 * execution, the natural-language request plan/body/interpretation, input
 * validation and result retention, with exactly one shared Worker, one WASM
 * instance and none on the page. Request -> result-ready latency runs as 12
 * ABBA pairs against the web Rust budget (web-rust-core-apps-bench.ts).
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');
const { APPS_BENCH_PAIRS, runAppsLatencyPairs } = require('./helpers/web-rust-core-apps-bench');

const APPS_OPT_OUT_KEY = 'openmates_rust_core_apps';

async function fixtureRoutes(page: any): Promise<{ providerPosts: () => number }> {
	let providerPosts = 0;
	await page.route('**/v1/apps/web/skills/search/details', (route: any) => route.fulfill({ json: {
		app_id: 'web', skill_id: 'search', slug: 'search', name: 'Search web', name_translation_key: 'web.search.name',
		description: 'Search web fixture', description_translation_key: 'web.search.description', icon_image: null,
		input_schema: { type: 'object', required: ['requests'], properties: { requests: { type: 'array', minItems: 1, items: {
			type: 'object', required: ['query'], properties: { query: { type: 'string', minLength: 1 }, count: { type: 'integer', minimum: 1, maximum: 20 } } } } } },
		primary_fields: ['requests[].query'], defaults: { requests: [{ count: 10 }] }, pricing: null, providers: [], models: [],
		anonymous_allowed: true, execution_available: true, unavailable_reason: null, execution_mode: 'sync',
	} }));
	await page.route('**/v1/anonymous/apps/web/skills/search/availability', (route: any) => route.fulfill({ json: { allowed: true } }));
	await page.route('**/v1/apps/workspace/interpret', (route: any) => {
		const body = route.request().postDataJSON();
		return route.fulfill({ json: { action: 'execute', request_id: body.request_id, skill_id: 'search', input: { requests: [{ query: 'gardens near Berlin', count: 2 }] } } });
	});
	await page.route('**/v1/anonymous/apps/web/skills/search', (route: any) => {
		providerPosts++;
		expect(route.request().postDataJSON().requests[0].query).toBe('gardens near Berlin');
		return route.fulfill({ json: { success: true, data: { results: [{ results: [
			{ type: 'search_result', title: 'Community garden Berlin', url: 'https://example.test/community', description: 'Outdoor community garden' },
			{ type: 'search_result', title: 'Botanical garden Berlin', url: 'https://example.test/botanical', description: 'Botanical collections' },
		] }] } } });
	});
	return { providerPosts: () => providerPosts };
}

async function runRequest(page: any): Promise<number> {
	await page.goto(getE2EDebugUrl('/#apps/web'), { waitUntil: 'domcontentloaded' });
	const composer = page.getByTestId('apps-detail-fullscreen').getByTestId('apps-request-composer');
	await expect(composer).toBeVisible({ timeout: 30000 });
	await composer.getByTestId('apps-request-textarea').fill('Find gardens near Berlin');
	const started = Date.now();
	await composer.getByTestId('apps-request-submit').click();
	const grid = page.getByTestId('apps-result-fullscreen').getByTestId('search-template-grid');
	await expect(grid.getByTestId('embed-preview')).toHaveCount(2, { timeout: 30000 });
	const elapsed = Date.now() - started;
	await expect(grid).toContainText('Community garden Berlin');
	await expect(grid).toContainText('Botanical garden Berlin');
	return elapsed;
}

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,apps.requests.natural-language,sdk.web.before-after-performance
test('guest Apps skill runs on the shared Rust apps unit with one Worker and one WASM instance', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(900000);
	await page.setViewportSize({ width: 1180, height: 844 });
	const routes = await fixtureRoutes(page);
	const samples: Record<'ts' | 'rust', Record<string, any>[]> = { ts: [], rust: [] };
	const sample = async (path: 'ts' | 'rust'): Promise<number> => {
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); },
			[APPS_OPT_OUT_KEY, path === 'ts']);
		// Fresh realm per sample: the policy choice and the unit client are per page load.
		await page.reload({ waitUntil: 'domcontentloaded' });
		const posts = routes.providerPosts();
		const requestMs = await runRequest(page);
		expect(routes.providerPosts() - posts, `${path}: one provider dispatch`).toBe(1);
		const stats = await page.evaluate(() => (window as any).__openmatesRustAppsStats?.() ?? null);
		if (path === 'rust') {
			expect(stats, 'Rust arm loaded the apps unit client').not.toBeNull();
			// Skill execution (details, admission, quote, provider response) plus the
			// request plan, interpreter body, interpretation, input validation and retention plan.
			expect(stats.calls, 'Rust arm routed its decisions through the apps unit').toBeGreaterThanOrEqual(10);
			expect(stats.failures, 'no apps unit call failed').toBe(0);
		} else {
			expect(stats, 'TS arm never loaded the Rust apps adapter').toBeNull();
		}
		const instances = await rustCoreInstances(page);
		expect(instances.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
		expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, `${path}: one shared Rust core Worker`).toBe(1);
		expect(instances.rustWorkers, `${path}: no other Rust core Worker`).toBe(1);
		if (path === 'rust') expect(instances.sharedWorkerWasm, 'rust: one WASM instance in the shared Worker').toBe(1);
		samples[path].push({ requestMs, ...instances, stats });
		return requestMs;
	};
	// Warm-up sample (index 0 of pairOrder's scheme) is not part of the paired set.
	await sample('ts');
	samples.ts.length = 0;
	const bench = await runAppsLatencyPairs(sample, APPS_BENCH_PAIRS);
	await page.evaluate((key: string) => localStorage.removeItem(key), APPS_OPT_OUT_KEY);
	const summary = { pairs: bench.pairs, ratio: bench.ratio, difference: bench.difference, tsP95: bench.tsP95, rustP95: bench.rustP95, verdict: bench.verdict };
	console.log(`[web-rust-core-apps] ${JSON.stringify(summary)}`);
	await testInfo.attach('apps-skill-latency.json', { body: JSON.stringify({ ...bench, samples }, null, 2), contentType: 'application/json' });
	expect(bench.pairs, 'budget needs at least 12 pairs').toBeGreaterThanOrEqual(12);
	expect.soft(bench.verdict, `app request latency budget: ${JSON.stringify(summary)}`).toBe('rust_not_worse');
});
