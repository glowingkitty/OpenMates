/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page/TestInfo handles are untyped in these CommonJS specs. */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Search flow of the interleaved TS-vs-Rust web benchmark
 * (web-rust-core-bench.spec.ts) and the shared steps of web-rust-core-search.spec.ts.
 *
 * One code-embed chat is seeded through the normal send. Each sample reloads
 * that chat, opens the sidebar search, types a rare query (`pandas`, from the
 * seeded chat) and waits until its message snippet is rendered — this
 * includes the on-demand index warm-up that a first search after a reload
 * pays (measurement waits for the warm-up to complete: no warming-up indicator and
 * an unchanged snippet list for 100 ms, identically on both arms, reporting the time
 * the complete render first appeared) — then clears the field and types a common query (`the`, matching most
 * indexed messages and the public example chats) and waits for its snippets.
 * Samples run on one page in the same counterbalanced pairs as the reload bench
 * (bench-stats.ts pairOrder: ts,rust then rust,ts alternately) after one
 * discarded ts,rust warm-up pair; the TS arm sets the measurement-only
 * opt-out (rustChatSearch.ts SEARCH_OPT_OUT_KEY). Each sample searches only after
 * the per-load app metadata settled (appMetadataSettled). Every pair must render the
 * same snippet texts (compared as sorted lists: chats with equal timestamps
 * may settle in either order on both arms). Gated per metric (paired bootstrap 95% CI upper bound within max(+10%, +50 ms) wall, +15% CPU):
 *   searchRenderedMs  query typed -> rare-query snippet rendered (cold index)
 *   commonSearchMs    query typed -> common-query snippets rendered (warm index)
 *   searchCpuMs       browser CPU (all verified Chromium processes) over both searches
 * plus RSS (<= +30 MB, each Rust sample against the TS level interpolated between
 * the TS samples around it: bench-stats.ts interpolatedBaselinePairs) and at most
 * one WASM instance.
 */
export {};

const { expect } = require('./cookie-audit');
const { createSignupLogger, createStepScreenshotter, getE2EDebugUrl } = require('../signup-flow-helpers');
const { seedCodeEmbedChat } = require('./embed-ready-metrics');
const { rustCoreInstances } = require('./rust-core-instances');
const { createBrowserProcessEvidence } = require('./browser-process-evidence.cjs');
const { summarizePaired, markdownTable, pairOrder, interpolatedBaselinePairs, transitionIncrements } = require('./bench-stats');

/** Measurement-only opt-out of the Rust search unit (rustChatSearch.ts). */
const SEARCH_OPT_OUT_KEY = 'openmates_rust_core_search';
const RARE_QUERY = 'pandas';
const COMMON_QUERY = 'the';
/** Approved budget (.claude/rules/cli-sdk.md): wall max(+10%, +50 ms) with p95 at most +100 ms; CPU +15%. */
const MARGIN = Number.parseFloat(process.env.OPENMATES_BENCH_MARGIN ?? '0.1') || 0.1;
const WALL_FLOOR_MS = 50;
const P95_ALLOW_MS = 100;
const CPU_MARGIN = 0.15;
const RSS_LIMIT_BYTES = 30 * 1024 * 1024;
const GATED_RATIO_METRICS = ['searchRenderedMs', 'commonSearchMs', 'searchCpuMs'] as const;
const SNIPPETS = '[data-testid="search-results"] .message-snippet:not(.metadata-snippet)';

const sorted = (texts: string[]): string[] => [...texts].sort();

/**
 * Arms, before a reload, a wait for the two per-load fetches that decide snippet
 * context labels: SearchResults.svelte renders "App · Skill" from
 * appSkillsStore.getState(), which fails open (all skills) until
 * /v1/apps/metadata and /v1/features/availability have settled, and the label is
 * not re-rendered afterwards. Both arms search only after both settled, so a
 * label never depends on which arm happened to render first.
 */
function appMetadataSettled(page: any): Promise<void> {
	const finished = (path: string) => page.waitForEvent('requestfinished', { predicate: (request: any) => new URL(request.url()).pathname.endsWith(path), timeout: 60000 });
	return Promise.all([finished('/v1/apps/metadata'), finished('/v1/features/availability')])
		.then(() => page.evaluate(() => new Promise((settle) => requestAnimationFrame(() => setTimeout(settle, 0)))))
		.then(() => undefined);
}

/** Opens the sidebar search bar and returns its input (sidebar closed by default below 1440px). */
async function openSidebarSearch(page: any): Promise<any> {
	const searchButton = page.getByTestId('search-button');
	if (!(await searchButton.isVisible().catch(() => false))) {
		const toggle = page.getByTestId('sidebar-toggle');
		if (await toggle.isVisible().catch(() => false)) await toggle.click();
	}
	await expect(searchButton).toBeVisible({ timeout: 30000 });
	await searchButton.click();
	const input = page.getByTestId('search-input');
	await expect(input).toBeVisible({ timeout: 10000 });
	return input;
}

/** In-page: ms from `startMark` until message snippets matching the query are rendered. */
function waitSnippets({ selector, query, startMark }: { selector: string; query: string; startMark: string }): Promise<{ ms: number | null; snippets: string[] }> {
	const start = performance.getEntriesByName(startMark).at(-1)?.startTime ?? performance.now();
	const STABLE_MS = 100;
	return new Promise((resolve) => {
		let lastKey = '';
		let candidateAt = 0;
		const tick = () => {
			const nodes = [...document.querySelectorAll(selector)];
			const texts = nodes.map((node) => (node.textContent ?? '').replace(/\s+/g, ' ').trim());
			const now = performance.now();
			// A partial render while the search index is still warming up shows only some chats' snippets.
			const warmingUp = document.querySelector('[data-testid="search-results"] [data-testid="warming-up"]') !== null;
			const matching = texts.length > 0 && texts.every((text) => text.toLowerCase().includes(query));
			if (matching && !warmingUp) {
				const key = texts.join('\n');
				if (key !== lastKey) { lastKey = key; candidateAt = now; }
				// Resolved once the complete render stayed unchanged; the time reported is when it first appeared.
				if (now - candidateAt >= STABLE_MS) { resolve({ ms: candidateAt - start, snippets: texts }); return; }
			} else lastKey = '';
			if (now - start > 90000) resolve({ ms: null, snippets: texts });
			else setTimeout(tick, 5);
		};
		tick();
	});
}

/** Types `query` into the open search input and waits for its message snippets. */
async function searchAndWait(page: any, input: any, query: string, mark: string): Promise<{ ms: number | null; snippets: string[] }> {
	await page.evaluate((name: string) => performance.mark(name), mark);
	await input.fill(query);
	return page.evaluate(waitSnippets, { selector: SNIPPETS, query: query.toLowerCase(), startMark: mark });
}

/** In-page: totals per search phase measure (`openmates:search:*`, `openmates:rust:search:*`) since the page load. */
function collectPhases(): Record<string, Record<string, number>> {
	const totals: Record<string, Record<string, number>> = {};
	for (const measure of performance.getEntriesByType('measure')) {
		if (!measure.name.startsWith('openmates:search:') && !measure.name.startsWith('openmates:rust:search:')) continue;
		const total = (totals[measure.name.replace('openmates:', '')] ??= { count: 0, ms: 0 });
		total.count += 1;
		total.ms += measure.duration;
		for (const [key, value] of Object.entries((measure.detail ?? {}) as Record<string, unknown>)) {
			if (typeof value === 'number') total[key] = (total[key] ?? 0) + value;
		}
	}
	return totals;
}

/** One reload of the seeded chat with both searches on the `path` arm. */
async function searchSample(page: any, chatId: string, path: 'ts' | 'rust', processes: any): Promise<Record<string, any>> {
	await page.evaluate(([key, ts]: [string, boolean]) => { if (ts) localStorage.setItem(key, 'ts'); else localStorage.removeItem(key); }, [SEARCH_OPT_OUT_KEY, path === 'ts']);
	await page.goto(getE2EDebugUrl(`/#chat-id=${chatId}`));
	const settled = appMetadataSettled(page);
	await page.reload();
	await expect(page.getByTestId('message-editor')).toBeVisible({ timeout: 60000 });
	await settled;
	const input = await openSidebarSearch(page);
	await processes.begin();
	const rare = await searchAndWait(page, input, RARE_QUERY, 'bench:search-rare');
	await input.fill('');
	await expect(page.locator(SNIPPETS)).toHaveCount(0, { timeout: 15000 });
	const common = await searchAndWait(page, input, COMMON_QUERY, 'bench:search-common');
	const process = await processes.end();
	const sample: Record<string, any> = {
		searchRenderedMs: rare.ms, commonSearchMs: common.ms,
		rareSnippets: rare.snippets, commonSnippets: common.snippets,
		searchCpuMs: process.available ? process.stableReportedProcessCpuMs : null,
		browserRssBytes: process.available ? process.after.summedReportedProcessRssBytes : null,
		browserRssBeforeBytes: process.available ? process.before.summedReportedProcessRssBytes : null,
		marker: await page.evaluate(() => document.documentElement.dataset.rustCoreSearch ?? null),
		phases: await page.evaluate(collectPhases),
	};
	Object.assign(sample, await rustCoreInstances(page));
	expect(sample.searchRenderedMs, `${path}: rare-query snippet rendered`).not.toBeNull();
	expect(sample.commonSearchMs, `${path}: common-query snippets rendered`).not.toBeNull();
	expect(sample.wasmMainThreadInstantiations, `${path}: no WASM on the page realm`).toBe(0);
	if (path === 'rust') expect(String(sample.marker), 'the Rust search unit served the queries').toMatch(/^rust:\d+$/);
	else expect(sample.marker, 'TS arm did not use the Rust search unit').toBeNull();
	return sample;
}

/** Median per arm of every phase total (diagnostic, not gated): where a search sample spends its time. */
function phaseMedianTable(pairs: { ts: Record<string, any>; rust: Record<string, any> }[]): { rows: Record<string, { ts: number | null; rust: number | null }>; table: string } {
	const keys = new Set<string>();
	for (const pair of pairs) for (const arm of [pair.ts, pair.rust]) for (const [name, fields] of Object.entries(arm.phases ?? {})) for (const field of Object.keys(fields as object)) keys.add(`${name}.${field}`);
	const medianOf = (values: number[]): number | null => {
		if (values.length === 0) return null;
		const ordered = [...values].sort((a, b) => a - b);
		const mid = ordered.length >> 1;
		return Math.round((ordered.length % 2 ? ordered[mid] : (ordered[mid - 1] + ordered[mid]) / 2) * 10) / 10;
	};
	const rows: Record<string, { ts: number | null; rust: number | null }> = {};
	for (const key of [...keys].sort()) {
		const [name, field] = [key.slice(0, key.lastIndexOf('.')), key.slice(key.lastIndexOf('.') + 1)];
		const pick = (arm: 'ts' | 'rust') => medianOf(pairs.map((pair) => pair[arm].phases?.[name]?.[field]).filter((value) => Number.isFinite(value)) as number[]);
		rows[key] = { ts: pick('ts'), rust: pick('rust') };
	}
	const table = ['| phase.field (median per sample) | TS | Rust |', '|---|---|---|', ...Object.entries(rows).map(([key, row]) => `| ${key} | ${row.ts ?? '-'} | ${row.rust ?? '-'} |`)].join('\n');
	return { rows, table };
}

/** Runs the paired search bench and attaches web-rust-core-bench-search.{json,md}. */
async function runSearchBench(page: any, testInfo: any, options: { pairs: number }): Promise<void> {
	const log = createSignupLogger('WEB_RUST_CORE_BENCH_SEARCH');
	const screenshot = createStepScreenshotter(log);
	const chatId = await seedCodeEmbedChat(page, log, screenshot);
	const processes = await createBrowserProcessEvidence(page);
	const pairs: { ts: Record<string, any>; rust: Record<string, any> }[] = [];
	// Every sample in measurement order (warm-up included) for the RSS level metrics.
	const sequence: { arm: 'ts' | 'rust'; sample: Record<string, any>; warmUp: boolean }[] = [];
	try {
		for (let index = 0; index <= options.pairs; index += 1) {
			const pair: Record<string, Record<string, any>> = {};
			for (const arm of pairOrder(index)) {
				pair[arm] = await searchSample(page, chatId, arm, processes);
				sequence.push({ arm, sample: pair[arm], warmUp: index === 0 });
			}
			const { ts, rust } = pair;
			expect(sorted(rust.rareSnippets), 'Rust and TS render the same rare-query snippets').toEqual(sorted(ts.rareSnippets));
			expect(sorted(rust.commonSnippets), 'Rust and TS render the same common-query snippets').toEqual(sorted(ts.commonSnippets));
			if (index === 0) continue;
			pairs.push({ ts, rust });
			log('search pair', { index, order: pairOrder(index).join(','), ts: [ts.searchRenderedMs, ts.commonSearchMs], rust: [rust.searchRenderedMs, rust.commonSearchMs] });
		}
		// The RSS baseline interpolates between TS samples on both sides of each Rust sample.
		if (sequence[sequence.length - 1].arm === 'rust') sequence.push({ arm: 'ts', sample: await searchSample(page, chatId, 'ts', processes), warmUp: false });
	} finally {
		await processes.close();
		await page.evaluate((key: string) => localStorage.removeItem(key), SEARCH_OPT_OUT_KEY).catch(() => undefined);
	}
	await screenshot(page, 'search-bench-done');
	const column = (metric: string) => pairs.map((pair) => ({ ts: pair.ts[metric], rust: pair.rust[metric] }));
	const summary: Record<string, Record<string, any>> = {};
	for (const metric of GATED_RATIO_METRICS) {
		summary[metric] = metric === 'searchCpuMs'
			? summarizePaired(column(metric), { mode: 'ratio', margin: CPU_MARGIN })
			: summarizePaired(column(metric), { mode: 'ratio', margin: MARGIN, floorMs: WALL_FLOOR_MS, p95AllowMs: P95_ALLOW_MS });
	}
	const measured = sequence.filter((entry) => !entry.warmUp);
	summary.browserRssBytes = summarizePaired(interpolatedBaselinePairs(measured.map((entry) => ({ arm: entry.arm, value: entry.sample.browserRssBytes }))), { mode: 'difference', limit: RSS_LIMIT_BYTES });
	summary.browserRssBytesAdjacentPair = summarizePaired(column('browserRssBytes'), { mode: 'difference', gate: false });
	summary.dedicatedWorkers = summarizePaired(column('dedicatedWorkers'), { mode: 'difference', gate: false });
	const maxRustWasm = Math.max(...pairs.map((pair) => Number(pair.rust.wasmInstantiations)));
	summary.wasmInstantiations = { ...summarizePaired(column('wasmInstantiations'), { mode: 'difference' }), verdict: maxRustWasm > 1 ? 'rust_worse' : 'rust_not_worse', maxRustInstances: maxRustWasm };
	const phaseMedians = phaseMedianTable(pairs);
	log('search phase medians (per sample totals)\n' + phaseMedians.table);
	const commonSnippetCount = pairs[0]?.rust.commonSnippets.length ?? 0;
	const report = {
		flow: 'search', pairs: options.pairs, margin: MARGIN, cpuMargin: CPU_MARGIN, wallFloorMs: WALL_FLOOR_MS, p95AllowMs: P95_ALLOW_MS, rssLimitBytes: RSS_LIMIT_BYTES, queries: { rare: RARE_QUERY, common: COMMON_QUERY, commonSnippetCount },
		order: 'counterbalanced ts,rust / rust,ts pairs after one discarded ts,rust warm-up pair', summary,
		phases: phaseMedians.rows, rssIncrementPerReloadBytes: transitionIncrements(sequence.map((entry) => ({ arm: entry.arm, before: entry.sample.browserRssBeforeBytes, after: entry.sample.browserRssBytes }))),
		sequence: sequence.map((entry) => `${entry.warmUp ? 'w' : ''}${entry.arm}`).join(','),
		samples: pairs,
	};
	const table = markdownTable(summary);
	log('search bench table\n' + table, { commonSnippetCount });
	await testInfo.attach('web-rust-core-bench-search.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
	await testInfo.attach('web-rust-core-bench-search.md', { body: `${table}\n\n${phaseMedians.table}`, contentType: 'text/markdown' });
	for (const metric of ['searchRenderedMs', 'commonSearchMs'] as const) expect(summary[metric].pairs, `${metric}: usable pairs`).toBe(options.pairs);
	expect(maxRustWasm, 'at most one WASM instance per Rust load').toBeLessThanOrEqual(1);
	for (const metric of GATED_RATIO_METRICS) expect.soft(summary[metric].verdict, `${metric} gate (CI upper bound <= ${metric === 'searchCpuMs' ? `+${CPU_MARGIN * 100}%` : `max(+${MARGIN * 100}%, +${WALL_FLOOR_MS} ms), p95 +${P95_ALLOW_MS} ms`})`).not.toBe('rust_worse');
}

module.exports = { runSearchBench, appMetadataSettled, openSidebarSearch, searchAndWait, sorted, SEARCH_OPT_OUT_KEY, SNIPPETS, RARE_QUERY, COMMON_QUERY };
