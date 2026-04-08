import { expect, test } from './helpers/cookie-audit';
import type { Page } from '@playwright/test';
/* eslint-disable @typescript-eslint/no-require-imports */
const { getE2EDebugUrl } = require('./signup-flow-helpers');

/**
 * Page load performance spec — guards against regressions introduced
 * by the /docs redesign (commit 309abd310).
 *
 * Concern: The docs page redesign added:
 *   - SSR + prerendering for all /docs routes
 *   - docs-data.json (4.5 MB) imported at build time by multiple components
 *   - DocsSidebar, DocsMessage, ChatHeader, TipTap imports
 *   - A separate docsPanelState store that syncs with isActivityHistoryOpen
 *
 * Risk: If the docs bundle is not properly code-split, these assets may
 * bleed into the main app chunk, slowing down the root "/" load.
 *
 * Architecture context: docs/architecture/docs-web-app.md
 * Test reference: run via scripts/run-tests.sh --suite playwright
 */

// Thresholds (milliseconds). Kept generous to avoid CI flakiness from
// network variance — goal is catching large regressions, not micro-optimising.
const THRESHOLDS = {
	// Root "/" — the main web app. Must be fast regardless of /docs work.
	rootDomContentLoaded: 4000,
	rootNetworkIdle: 10000,
	// Docs index "/docs" — allowed to be heavier (TipTap, sidebar, prerendered HTML).
	docsDomContentLoaded: 6000,
	docsNetworkIdle: 15000,
	// Individual doc page "/docs/<slug>"
	docsSlugDomContentLoaded: 6000,
	docsSlugNetworkIdle: 15000
};

// ────────────────────────────────────────────────────────────────────────────
// Helper
// ────────────────────────────────────────────────────────────────────────────

type TimingResult = {
	domContentLoaded: number;
	networkIdleMs: number;
	transferSizeKB: number;
	jsHeapMB: number;
};

async function measurePageLoad(page: Page, url: string): Promise<TimingResult> {
	const startMs = Date.now();
	await page.goto(url, { waitUntil: 'domcontentloaded' });
	const domContentLoaded = Date.now() - startMs;

	await page.waitForLoadState('networkidle');
	const networkIdleMs = Date.now() - startMs;

	const { transferBytes, heapBytes } = await page.evaluate(() => {
		const entries = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
		const navEntry = performance.getEntriesByType(
			'navigation'
		)[0] as PerformanceNavigationTiming;
		const navBytes = navEntry?.transferSize ?? 0;
		const resourceBytes = entries.reduce((sum, e) => sum + (e.transferSize ?? 0), 0);
		const mem = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
		return { transferBytes: navBytes + resourceBytes, heapBytes: mem?.usedJSHeapSize ?? 0 };
	});

	return {
		domContentLoaded,
		networkIdleMs,
		transferSizeKB: Math.round(transferBytes / 1024),
		jsHeapMB: Math.round((heapBytes / 1024 / 1024) * 10) / 10
	};
}

// ────────────────────────────────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────────────────────────────────

test.describe('Page load performance — docs regression guard', () => {
	test.setTimeout(120_000);

	test('measure and compare load times: / vs /docs vs /docs/<slug>', async ({ page }) => {
		test.slow();

		// ── Root "/" ──────────────────────────────────────────────────────────
		const rootMetrics = await measurePageLoad(page, getE2EDebugUrl('/'));
		console.log('\n── Load metrics ──────────────────────────────────────────────');
		console.log(
			`  /                domContentLoaded: ${rootMetrics.domContentLoaded}ms  networkIdle: ${rootMetrics.networkIdleMs}ms  transfer: ${rootMetrics.transferSizeKB}KB  heap: ${rootMetrics.jsHeapMB}MB`
		);

		// ── /docs ─────────────────────────────────────────────────────────────
		const docsMetrics = await measurePageLoad(page, getE2EDebugUrl('/docs'));
		console.log(
			`  /docs            domContentLoaded: ${docsMetrics.domContentLoaded}ms  networkIdle: ${docsMetrics.networkIdleMs}ms  transfer: ${docsMetrics.transferSizeKB}KB  heap: ${docsMetrics.jsHeapMB}MB`
		);

		// ── /docs/<slug> — grab first real doc link from the sidebar ──────────
		const firstDocHref = await page.locator('a[href^="/docs/"]').first().getAttribute('href');
		const slugUrl = firstDocHref ?? '/docs/architecture';
		const docsSlugMetrics = await measurePageLoad(page, getE2EDebugUrl(slugUrl));
		console.log(
			`  ${slugUrl.padEnd(16)} domContentLoaded: ${docsSlugMetrics.domContentLoaded}ms  networkIdle: ${docsSlugMetrics.networkIdleMs}ms  transfer: ${docsSlugMetrics.transferSizeKB}KB  heap: ${docsSlugMetrics.jsHeapMB}MB`
		);
		console.log('──────────────────────────────────────────────────────────────');

		const docsOverheadMs = docsMetrics.networkIdleMs - rootMetrics.networkIdleMs;
		const docsOverheadKB = docsMetrics.transferSizeKB - rootMetrics.transferSizeKB;
		console.log(
			`  /docs overhead vs /: +${docsOverheadMs}ms network-idle, +${docsOverheadKB}KB transfer\n`
		);

		// ── Assertions: root "/" must stay within its tight budget ────────────
		expect(
			rootMetrics.domContentLoaded,
			`Root "/" DOMContentLoaded ${rootMetrics.domContentLoaded}ms exceeds ${THRESHOLDS.rootDomContentLoaded}ms. ` +
				`Likely cause: /docs assets (docs-data.json is 4.5MB) leaked into the main bundle.`
		).toBeLessThan(THRESHOLDS.rootDomContentLoaded);

		expect(
			rootMetrics.networkIdleMs,
			`Root "/" network-idle ${rootMetrics.networkIdleMs}ms exceeds ${THRESHOLDS.rootNetworkIdle}ms. ` +
				`Check whether docs prerendering or docs-data.json fetch is blocking startup.`
		).toBeLessThan(THRESHOLDS.rootNetworkIdle);

		// ── Assertions: /docs has its own looser budget ───────────────────────
		expect(
			docsMetrics.domContentLoaded,
			`/docs DOMContentLoaded ${docsMetrics.domContentLoaded}ms exceeds ${THRESHOLDS.docsDomContentLoaded}ms`
		).toBeLessThan(THRESHOLDS.docsDomContentLoaded);

		expect(
			docsMetrics.networkIdleMs,
			`/docs network-idle ${docsMetrics.networkIdleMs}ms exceeds ${THRESHOLDS.docsNetworkIdle}ms`
		).toBeLessThan(THRESHOLDS.docsNetworkIdle);

		// ── Assertions: /docs/<slug> ──────────────────────────────────────────
		expect(
			docsSlugMetrics.domContentLoaded,
			`${slugUrl} DOMContentLoaded ${docsSlugMetrics.domContentLoaded}ms exceeds ${THRESHOLDS.docsSlugDomContentLoaded}ms`
		).toBeLessThan(THRESHOLDS.docsSlugDomContentLoaded);

		expect(
			docsSlugMetrics.networkIdleMs,
			`${slugUrl} network-idle ${docsSlugMetrics.networkIdleMs}ms exceeds ${THRESHOLDS.docsSlugNetworkIdle}ms`
		).toBeLessThan(THRESHOLDS.docsSlugNetworkIdle);
	});

	test('root "/" does not fetch docs-data.json or docs-specific JS chunks', async ({ page }) => {
		test.slow();

		const docsResources: string[] = [];

		page.on('request', (req) => {
			const url = req.url();
			// docs-data.json being fetched at runtime means prerendering failed
			if (url.includes('docs-data')) {
				docsResources.push(`[docs-data] ${url}`);
			}
			// SvelteKit code-splits by route; docs chunks are named after the route segment
			if (
				url.includes('/_app/immutable/') &&
				(url.includes('-docs-') ||
					url.includes('_docs_') ||
					url.toLowerCase().includes('docssidebar') ||
					url.toLowerCase().includes('docsmessage'))
			) {
				docsResources.push(`[docs-chunk] ${url}`);
			}
		});

		await page.goto(getE2EDebugUrl('/'), { waitUntil: 'networkidle' });
		await page.waitForTimeout(2000);

		if (docsResources.length > 0) {
			console.warn(
				'\n⚠️  Root "/" loaded docs-related resources — docs assets are NOT code-split from main bundle:\n' +
					docsResources.map((u) => `  ${u}`).join('\n') +
					'\n'
			);
		} else {
			console.log('\n✅  Root "/" loaded zero docs-related resources — code split is healthy.\n');
		}

		expect(
			docsResources,
			`Root "/" fetched ${docsResources.length} docs-specific resource(s). ` +
				`The /docs redesign may have broken SvelteKit code-splitting. ` +
				`Resources: ${docsResources.join(', ')}`
		).toHaveLength(0);
	});

	test('/docs page renders sidebar and doc links without JS errors', async ({ page }) => {
		test.slow();

		const pageErrors: string[] = [];
		page.on('pageerror', (err) => pageErrors.push(`${err.name}: ${err.message}`));

		const start = Date.now();
		const response = await page.goto(getE2EDebugUrl('/docs'), { waitUntil: 'networkidle' });
		const elapsed = Date.now() - start;

		expect(response?.status(), '/docs should return HTTP 200').toBe(200);

		// Sidebar must be present — key output of the docs redesign
		await expect(
			page.locator('[data-testid="docs-sidebar"], .docs-sidebar, nav').first()
		).toBeVisible({ timeout: 10_000 });

		// At least one doc link must be present
		await expect(page.locator('a[href^="/docs/"]').first()).toBeVisible({ timeout: 10_000 });

		console.log(`\n  /docs total load: ${elapsed}ms\n`);

		expect(
			elapsed,
			`/docs full load took ${elapsed}ms, exceeds ${THRESHOLDS.docsNetworkIdle}ms budget`
		).toBeLessThan(THRESHOLDS.docsNetworkIdle);

		if (pageErrors.length > 0) {
			console.error('JS errors on /docs:', pageErrors);
		}
		expect(pageErrors, '/docs should have no JS errors at load').toHaveLength(0);
	});
});
