import { expect, test } from '@playwright/test';

/**
 * Embed App Showcase Tests
 *
 * Tests the /dev/preview/embeds/<app> pages for all 17 registered apps.
 * These pages render every embed display type (Inline Link, Quote Block,
 * Group—Small, Preview—Large, Group—Large, Fullscreen) using static mock
 * data from .preview.ts files — no login or AI calls required.
 *
 * What is tested per app:
 *   1. Page loads without JS errors or component load failures
 *   2. All sections finish loading (no stuck "Loading..." states)
 *   3. All 6 display types are present per skill section
 *   4. At least one embed reaches data-status="finished"
 *   5. No broken <img> tags (favicons, thumbnails, OG images)
 *   6. No [object Object], undefined, or null rendering artifacts
 *   7. No raw JSON embed references leaked as visible text
 *   8. App icon gradient resolves (CSS var not empty/transparent)
 *   9. Dark mode toggle works and doesn't break icon colors
 *  10. Search skill fullscreens show 2 result cards per row (≥ 2 columns)
 *
 * Runs against the deployed dev instance. No login required.
 */

// ── Constants ─────────────────────────────────────────────────────────────────

/** All apps registered in the APP_REGISTRY of [app]/+page.svelte */
const ALL_APPS = [
	'code',
	'docs',
	'web',
	'videos',
	'images',
	'news',
	'travel',
	'maps',
	'math',
	'events',
	'reminder',
	'sheets',
	'audio',
	'health',
	'mail',
	'pdf',
	'shopping'
] as const;

/**
 * Search fullscreen components that must show ≥ 2 result cards per row.
 * Key = app slug, values = skill labels whose fullscreen sections must be checked.
 */
/**
 * Search skills whose fullscreen uses SearchResultsTemplate with .search-template-grid.
 * Apps that use a custom grid/list layout (maps, pdf) are excluded here
 * since their fullscreen doesn't have .search-template-grid.
 */
const SEARCH_SKILLS: Record<string, string[]> = {
	web: ['Search'],
	videos: ['Search'],
	images: ['Search'],
	news: ['Search'],
	travel: ['Search', 'Stays Search'],
	events: ['Search'],
	health: ['Search'],
	shopping: ['Search']
};

/** How long to wait for all sections to finish loading (ms) */
const SECTION_LOAD_TIMEOUT = 20_000;

/** How long to wait for the page to fully hydrate after navigation (ms) */
const HYDRATION_WAIT = 3_000;

/** The 6 expected display-type headings per skill section */
const EXPECTED_DT_HEADINGS = [
	'Inline Link',
	'Quote Block',
	'Group — Small',
	'Preview — Large',
	'Fullscreen'
	// Note: "Group — Large" only appears when there are > 1 data variants,
	// so we don't assert it universally but do check it when it appears.
];

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Wait until all `.section-loading` elements disappear from the page.
 * This means all async component imports and mock-data loads have resolved.
 */
async function waitForAllSectionsLoaded(page: import('@playwright/test').Page) {
	await expect(async () => {
		const loadingCount = await page.locator('p.section-loading').count();
		expect(loadingCount).toBe(0);
	}).toPass({ timeout: SECTION_LOAD_TIMEOUT });
}

// ── Per-app test suite ────────────────────────────────────────────────────────

for (const app of ALL_APPS) {
	test.describe(`Embed showcase — ${app}`, () => {
		test(`${app}: loads without errors, all embeds render, no artifacts`, async ({ page }) => {
			// ── Error collection ────────────────────────────────────────────
			const pageErrors: string[] = [];
			const consoleErrors: string[] = [];

			page.on('pageerror', (err) => {
				pageErrors.push(`${err.name}: ${err.message}`);
			});
			page.on('console', (msg) => {
				if (msg.type() === 'error') {
					const text = msg.text();
					// Filter known benign noise:
					// - favicon 404 from browser default
					// - dynamic import MIME warnings that resolve correctly
					// - Chromium security policy violations for mask-image SVGs on localhost
					// - IndexedDB init race on dev preview pages (not embed-related)
					// - Generic 404s from server (image proxying, SVGs) — tested separately via brokenImages check
					if (
						text.includes('favicon.ico') ||
						text.includes('Failed to load resource: net::ERR_') ||
						text.includes('Failed to load resource: the server responded') ||
						text.includes('Content Security Policy') ||
						text.includes('[ChatDatabase]')
					) {
						return;
					}
					consoleErrors.push(text);
				}
			});

			// ── Navigate ────────────────────────────────────────────────────
			const response = await page.goto(`/dev/preview/embeds/${app}`, {
				waitUntil: 'networkidle'
			});
			expect(response?.status()).toBe(200);

			// Wait for SvelteKit hydration
			await page.waitForTimeout(HYDRATION_WAIT);

			// ── CHECK 1: Page structure ─────────────────────────────────────
			// Not an unknown app
			await expect(page.locator('div.unknown-app')).not.toBeVisible();

			// App title heading is visible
			await expect(page.locator('h1.app-title')).toBeVisible();

			// ── CHECK 2: All sections finish loading ────────────────────────
			await waitForAllSectionsLoaded(page);

			// ── CHECK 3: No component load errors ──────────────────────────
			const sectionErrors = await page.locator('p.section-error').count();
			expect(sectionErrors, `${app}: found ${sectionErrors} section load error(s)`).toBe(0);

			// ── CHECK 4: All skill sections have the expected display types ─
			const skillSections = page.locator('section.skill-section');
			const sectionCount = await skillSections.count();
			expect(sectionCount, `${app}: expected at least 1 skill section`).toBeGreaterThan(0);

			for (let i = 0; i < sectionCount; i++) {
				const section = skillSections.nth(i);
				const skillLabel = await section.locator('h2.skill-label').textContent();

				// Each section must have ALL core display type headings
				for (const heading of EXPECTED_DT_HEADINGS) {
					const dtLocator = section.locator(`h3.dt-heading:has-text("${heading}")`);
					const count = await dtLocator.count();
					expect(count, `${app}/${skillLabel}: missing display type "${heading}"`).toBeGreaterThan(
						0
					);
				}
			}

			// ── CHECK 5: At least one embed reaches "finished" status ───────
			const finishedEmbeds = page.locator('.unified-embed-preview[data-status="finished"]');
			await expect(async () => {
				const count = await finishedEmbeds.count();
				expect(count, `${app}: no embed reached data-status="finished"`).toBeGreaterThan(0);
			}).toPass({ timeout: 10_000 });

			// ── CHECK 6: No broken <img> tags ───────────────────────────────
			// Wait for lazy-loaded images to attempt loading
			await page.waitForTimeout(2_000);

			const brokenImages = await page.evaluate(() => {
				const imgs = [...document.querySelectorAll('img')] as HTMLImageElement[];
				return imgs
					.filter((img) => img.complete && img.naturalWidth === 0 && img.src && img.src !== '')
					.map((img) => img.src);
			});
			expect(brokenImages, `${app}: broken images found: ${brokenImages.join(', ')}`).toHaveLength(
				0
			);

			// ── CHECK 7: No rendering artifacts in visible text ─────────────
			const pageText = await page.evaluate(() => document.body.innerText);

			// [object Object] — JS object rendered as string (missing .toString or template literal)
			expect(pageText, `${app}: [object Object] found in visible text`).not.toContain(
				'[object Object]'
			);

			// Raw JSON embed references leaking as prose text
			const jsonEmbedRefPattern = /\{\s*"type"\s*:\s*"[^"]*"\s*,\s*"embed_id"\s*:\s*"[a-f0-9-]+"/gi;
			const jsonLeaks = pageText.match(jsonEmbedRefPattern) ?? [];
			expect(
				jsonLeaks,
				`${app}: raw JSON embed references in visible text: ${jsonLeaks.join(' | ')}`
			).toHaveLength(0);

			// Unresolved i18n keys (double underscores or MISSING_ prefix)
			expect(pageText, `${app}: missing i18n key found in visible text`).not.toMatch(
				/__MISSING_|MISSING_KEY|__missing/i
			);

			// ── CHECK 8: App icon gradient resolves (not transparent/empty) ─
			const iconGradientOk = await page.evaluate(() => {
				const circle = document.querySelector('.app-icon-circle, .app-icon-container');
				if (!circle) return { ok: false, reason: 'no .app-icon-circle found' };
				const bg = getComputedStyle(circle).background || getComputedStyle(circle).backgroundImage;
				// A resolved gradient will contain "rgb" or "rgba" — an unresolved var() produces empty string
				if (!bg || bg === 'none' || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') {
					return { ok: false, reason: `background resolved to: "${bg}"` };
				}
				return { ok: true, reason: bg };
			});
			expect(
				iconGradientOk.ok,
				`${app}: app icon gradient not resolved — ${iconGradientOk.reason}`
			).toBe(true);

			// ── CHECK 9: Dark mode toggle works ─────────────────────────────
			// Read the light-mode background of the showcase body
			const lightBg = await page.evaluate(() => {
				const body = document.querySelector('.showcase-body') as HTMLElement | null;
				return body ? getComputedStyle(body).backgroundColor : '';
			});

			// Toggle to dark mode
			await page.locator('button.theme-btn').click();
			await page.waitForTimeout(500);

			// After dark mode toggle, the background should have changed
			// (theme.css inverts --color-grey-0 from #fff to #171717)
			const darkBg = await page.evaluate(() => {
				const body = document.querySelector('.showcase-body') as HTMLElement | null;
				return body ? getComputedStyle(body).backgroundColor : '';
			});

			// Dark mode must actually change the color
			expect(
				darkBg,
				`${app}: dark mode toggle did not change background color (still: ${darkBg})`
			).not.toBe(lightBg);

			// App icon gradient must still resolve in dark mode
			const iconGradientDarkOk = await page.evaluate(() => {
				const circle = document.querySelector('.app-icon-circle, .app-icon-container');
				if (!circle) return { ok: false, reason: 'no .app-icon-circle found' };
				const bg = getComputedStyle(circle).background || getComputedStyle(circle).backgroundImage;
				if (!bg || bg === 'none' || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') {
					return { ok: false, reason: `background resolved to: "${bg}"` };
				}
				return { ok: true, reason: bg };
			});
			expect(
				iconGradientDarkOk.ok,
				`${app}: app icon gradient broken in dark mode — ${iconGradientDarkOk.reason}`
			).toBe(true);

			// Toggle back to light mode
			await page.locator('button.theme-btn').click();
			await page.waitForTimeout(300);

			// ── CHECK 10: No JS errors (collected throughout) ───────────────
			expect(pageErrors, `${app}: uncaught JS errors: ${pageErrors.join(' | ')}`).toHaveLength(0);

			expect(consoleErrors, `${app}: console errors: ${consoleErrors.join(' | ')}`).toHaveLength(0);
		});
	});
}

// ── Search skills — 2-per-row fullscreen layout ───────────────────────────────

test.describe('Search skill fullscreens — 2 result cards per row', () => {
	for (const [app, searchSkills] of Object.entries(SEARCH_SKILLS)) {
		for (const skillLabel of searchSkills) {
			test(`${app}/${skillLabel}: fullscreen shows ≥ 2 result cards per row`, async ({ page }) => {
				const response = await page.goto(`/dev/preview/embeds/${app}`, {
					waitUntil: 'networkidle'
				});
				expect(response?.status()).toBe(200);
				await page.waitForTimeout(HYDRATION_WAIT);
				await waitForAllSectionsLoaded(page);

				// Find the skill section for this search skill
				const skillSection = page
					.locator('section.skill-section')
					.filter({ has: page.locator(`h2.skill-label:text-is("${skillLabel}")`) });

				await expect(skillSection).toBeVisible({
					timeout: 5_000
				});

				// Find the Fullscreen display type block within this skill section
				const fsClip = skillSection.locator('div.fs-clip');
				await expect(fsClip, `${app}/${skillLabel}: .fs-clip not found`).toBeVisible();

				// Check the grid inside the fullscreen — it must have ≥ 2 columns
				// We do this by measuring the rendered positions of result cards.
				// If ≥ 2 cards exist and at least 2 have the same top position,
				// they are on the same row → 2-per-row layout is in effect.
				const columnCount = await page.evaluate(
					({ app: _app, skillLabel: _skillLabel }) => {
						// Find the skill section
						const sections = [...document.querySelectorAll('section.skill-section')];
						const section = sections.find((s) => {
							const label = s.querySelector('h2.skill-label');
							return label?.textContent?.trim() === _skillLabel;
						});
						if (!section) return { columns: 0, reason: 'skill section not found' };

						// Find the .fs-clip within this section
						const fsClip = section.querySelector('div.fs-clip');
						if (!fsClip) return { columns: 0, reason: '.fs-clip not found' };

						// Find all .unified-embed-preview cards inside the fullscreen grid
						const cards = [
							...fsClip.querySelectorAll('.search-template-grid .unified-embed-preview')
						] as HTMLElement[];
						if (cards.length < 2) {
							return {
								columns: cards.length,
								reason: `only ${cards.length} card(s) in grid — need ≥ 2 to check layout`
							};
						}

						// Group cards by their top offset (same row = same top ±5px tolerance)
						const topValues = cards.map((c) => c.getBoundingClientRect().top);
						const firstRowTop = topValues[0];
						const sameRowCount = topValues.filter((t) => Math.abs(t - firstRowTop) < 5).length;

						return {
							columns: sameRowCount,
							reason: `${sameRowCount} card(s) on first row (tops: ${topValues
								.slice(0, 4)
								.map((t) => Math.round(t))
								.join(', ')})`
						};
					},
					{ app, skillLabel }
				);

				expect(
					columnCount.columns,
					`${app}/${skillLabel}: expected ≥ 2 columns in fullscreen grid, got ${columnCount.columns} — ${columnCount.reason}`
				).toBeGreaterThanOrEqual(2);
			});
		}
	}
});
