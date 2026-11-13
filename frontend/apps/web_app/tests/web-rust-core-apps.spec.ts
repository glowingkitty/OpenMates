/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Shared Rust core (WASM) — Apps skill execution policy on the shared Worker
 * `apps` unit (the only apps path).
 *
 * Engineering check (web lane: apps). A guest runs the natural-language Web
 * search request of apps-workspace.spec.ts (fixture interpreter, details,
 * request quote and provider response): the result fullscreen must show both
 * results. The decisions must route through the unit (stats hook): skill
 * execution, the natural-language request plan/body/interpretation, input
 * validation and result retention, with exactly one shared Worker, one WASM
 * instance and none on the page. Request -> result-ready latency is logged for
 * a few fresh page loads.
 * Runs only in the CI lane that builds the Rust core package (web-rust-core-* specs).
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { rustCoreInstances } = require('./helpers/rust-core-instances');

const LATENCY_SAMPLES = 3;

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

// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary,apps.requests.natural-language
test('guest Apps skill runs on the shared Rust apps unit with one Worker and one WASM instance', async ({ page }: { page: any }, testInfo: any) => {
	test.slow();
	test.setTimeout(300000);
	await page.setViewportSize({ width: 1180, height: 844 });
	const routes = await fixtureRoutes(page);
	// Diagnostics: a hung request leaves no UI error, so keep page console/errors and apps-unit stats on failure.
	const diagnostics: string[] = [];
	page.on('console', (message: any) => { if (['error', 'warning'].includes(message.type())) diagnostics.push(`[console.${message.type()}] ${message.text()}`); });
	page.on('pageerror', (error: Error) => diagnostics.push(`[pageerror] ${error.message}`));
	page.on('requestfailed', (request: any) => diagnostics.push(`[requestfailed] ${request.url()} ${request.failure()?.errorText}`));
	const samples: Record<string, any>[] = [];
	for (let index = 0; index < LATENCY_SAMPLES; index++) {
		// Fresh realm per sample: the unit client is per page load.
		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
		await page.reload({ waitUntil: 'domcontentloaded' });
		const posts = routes.providerPosts();
		let requestMs: number;
		try {
			requestMs = await runRequest(page);
		} catch (error) {
			const unitStats = await page.evaluate(() => (window as any).__openmatesRustAppsStats?.() ?? null).catch(() => null);
			await testInfo.attach('apps-request-diagnostics.json', { body: JSON.stringify({ unitStats, diagnostics }, null, 2), contentType: 'application/json' });
			throw error;
		}
		expect(routes.providerPosts() - posts, 'one provider dispatch').toBe(1);
		const stats = await page.evaluate(() => (window as any).__openmatesRustAppsStats?.() ?? null);
		expect(stats, 'the apps unit client loaded').not.toBeNull();
		// Skill execution (details, admission, quote, provider response) plus the
		// request plan, interpreter body, interpretation, input validation and retention plan.
		expect(stats.calls, 'decisions were routed through the apps unit').toBeGreaterThanOrEqual(10);
		expect(stats.failures, 'no apps unit call failed').toBe(0);
		const instances = await rustCoreInstances(page);
		expect(instances.wasmMainThreadInstantiations, 'no WASM on the page realm').toBe(0);
		expect(instances.workers.filter((worker: { name: string }) => worker.name === 'shared.worker').length, 'one shared Rust core Worker').toBe(1);
		expect(instances.rustWorkers, 'no other Rust core Worker').toBe(1);
		expect(instances.sharedWorkerWasm, 'one WASM instance in the shared Worker').toBe(1);
		samples.push({ requestMs, ...instances, stats });
	}
	console.log(`[web-rust-core-apps] ${JSON.stringify(samples.map((sample) => sample.requestMs))}`);
	await testInfo.attach('apps-skill-latency.json', { body: JSON.stringify({ samples }, null, 2), contentType: 'application/json' });
});
