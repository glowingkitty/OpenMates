/* eslint-disable @typescript-eslint/no-explicit-any -- Playwright Page handles are untyped in these CommonJS specs. */
/* eslint-disable @typescript-eslint/no-require-imports -- Playwright CommonJS specs. */
/**
 * Shared sidebar-search steps of web-rust-core-search.spec.ts: wait for the
 * per-load app metadata, open the sidebar search, type a query and time until
 * its message snippets are rendered (no warming-up indicator and an unchanged
 * snippet list for 100 ms; the time the complete render first appeared).
 */
export {};

const { expect } = require('./cookie-audit');

const RARE_QUERY = 'pandas';
const COMMON_QUERY = 'the';
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

module.exports = { appMetadataSettled, openSidebarSearch, searchAndWait, sorted, SNIPPETS, RARE_QUERY, COMMON_QUERY };
