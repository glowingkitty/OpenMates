/**
 * Documentation Screenshot Generator
 *
 * Captures standardized screenshots from /dev/preview/embeds/<app> routes
 * for use in user-guide documentation. Outputs 1000x400px JPG images
 * following the existing naming convention:
 *   docs/images/user-guide/apps/{app}/previews/{skill_slug}/{state}.jpg
 *
 * Usage:
 *   npx playwright test docs-screenshot-generator --project=chromium
 *
 * Prerequisites:
 *   - Dev server running (preview routes are public, no auth needed)
 *   - PLAYWRIGHT_TEST_BASE_URL set to the dev server URL
 *
 * Architecture context: docs/contributing/guides/docs-writing-guidelines.md
 */

import { expect, test } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// ── Configuration ────────────────────────────────────────────────────────────

/** Root output directory for generated screenshots */
const DOCS_IMAGES_ROOT = path.resolve(__dirname, '../../../../docs/images/user-guide/apps');

/** Target screenshot dimensions (matches existing convention) */
const SCREENSHOT_WIDTH = 1000;
const SCREENSHOT_HEIGHT = 400;

/** Viewport width for consistent rendering */
const VIEWPORT_WIDTH = 1200;
const VIEWPORT_HEIGHT = 900;

/** How long to wait for all sections to finish loading (ms) */
const SECTION_LOAD_TIMEOUT = 20_000;

/** How long to wait for SvelteKit hydration after navigation (ms) */
const HYDRATION_WAIT = 3_000;

/**
 * Apps and their skill sections to screenshot.
 * Key = app slug (URL path), Value = array of { label, slug } pairs.
 * - label: the skill section heading text on the showcase page
 * - slug: the folder name used in the output path
 */
const SCREENSHOT_APPS: Record<string, Array<{ label: string; slug: string }>> = {
	mail: [
		{ label: 'Email', slug: 'email' },
		{ label: 'Search', slug: 'search' }
	],
	news: [{ label: 'Search', slug: 'search' }],
	travel: [
		{ label: 'Search', slug: 'search' },
		{ label: 'Stays Search', slug: 'stays_search' },
		{ label: 'Connections', slug: 'connections' }
	],
	shopping: [{ label: 'Search', slug: 'search' }],
	health: [
		{ label: 'Search', slug: 'search' },
		{ label: 'Appointments', slug: 'appointments' }
	],
	events: [{ label: 'Search', slug: 'search' }],
	maps: [
		{ label: 'Search', slug: 'search' },
		{ label: 'View', slug: 'view' }
	],
	reminder: [{ label: 'Reminders', slug: 'reminders' }],
	math: [
		{ label: 'Calculate', slug: 'calculate' },
		{ label: 'Plot', slug: 'plot' }
	],
	pdf: [
		{ label: 'Read', slug: 'read' },
		{ label: 'Search', slug: 'search' }
	],
	audio: [{ label: 'Transcribe', slug: 'transcribe' }]
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Wait until all `.section-loading` elements disappear from the page.
 * Reuses the same pattern as embed-showcase.spec.ts.
 */
async function waitForAllSectionsLoaded(page: import('@playwright/test').Page) {
	await expect(async () => {
		const loadingCount = await page.locator('p.section-loading').count();
		expect(loadingCount).toBe(0);
	}).toPass({ timeout: SECTION_LOAD_TIMEOUT });
}

/**
 * Ensure the output directory exists for a given app/skill.
 */
function ensureOutputDir(app: string, skillSlug: string): string {
	const dir = path.join(DOCS_IMAGES_ROOT, app, 'previews', skillSlug);
	fs.mkdirSync(dir, { recursive: true });
	return dir;
}

// ── Screenshot generation ────────────────────────────────────────────────────

for (const [app, skills] of Object.entries(SCREENSHOT_APPS)) {
	test.describe(`Screenshot generator — ${app}`, () => {
		test(`${app}: capture embed preview screenshots`, async ({ page }) => {
			// Set consistent viewport
			await page.setViewportSize({ width: VIEWPORT_WIDTH, height: VIEWPORT_HEIGHT });

			// Navigate to the embed showcase page
			const response = await page.goto(`/dev/preview/embeds/${app}`, {
				waitUntil: 'networkidle'
			});
			expect(response?.status()).toBe(200);

			// Wait for hydration and all sections to load
			await page.waitForTimeout(HYDRATION_WAIT);
			await waitForAllSectionsLoaded(page);

			// Wait for images to load
			await page.waitForTimeout(2_000);

			// Process each skill section
			const skillSections = page.locator('section.skill-section');
			const sectionCount = await skillSections.count();

			for (const skill of skills) {
				// Find the matching section by skill label
				let targetSection = null;
				for (let i = 0; i < sectionCount; i++) {
					const section = skillSections.nth(i);
					const labelEl = section.locator('h2.skill-label, h3.skill-label');
					const labelText = await labelEl.textContent();
					if (labelText?.trim() === skill.label) {
						targetSection = section;
						break;
					}
				}

				if (!targetSection) {
					console.warn(`${app}: skill section "${skill.label}" not found, skipping`);
					continue;
				}

				const outputDir = ensureOutputDir(app, skill.slug);

				// Screenshot the "Preview — Large" display type (.large-container)
				const largeContainer = targetSection.locator('.large-container').first();
				if ((await largeContainer.count()) > 0) {
					await largeContainer.scrollIntoViewIfNeeded();
					await page.waitForTimeout(500);

					const box = await largeContainer.boundingBox();
					if (box) {
						// Center-crop to 1000x400 from the container
						const clipX = Math.max(0, box.x + (box.width - SCREENSHOT_WIDTH) / 2);
						const clipY = box.y;
						const clipHeight = Math.min(SCREENSHOT_HEIGHT, box.height);

						await page.screenshot({
							path: path.join(outputDir, 'finished.jpg'),
							type: 'jpeg',
							quality: 85,
							clip: {
								x: clipX,
								y: clipY,
								width: Math.min(SCREENSHOT_WIDTH, box.width),
								height: clipHeight
							}
						});
					}
				}

				// Screenshot the "Fullscreen" display type (.fs-clip)
				const fsClip = targetSection.locator('.fs-clip').first();
				if ((await fsClip.count()) > 0) {
					await fsClip.scrollIntoViewIfNeeded();
					await page.waitForTimeout(500);

					const box = await fsClip.boundingBox();
					if (box) {
						const clipX = Math.max(0, box.x + (box.width - SCREENSHOT_WIDTH) / 2);
						const clipY = box.y;

						await page.screenshot({
							path: path.join(outputDir, 'chat_example.jpg'),
							type: 'jpeg',
							quality: 85,
							clip: {
								x: clipX,
								y: clipY,
								width: Math.min(SCREENSHOT_WIDTH, box.width),
								height: Math.min(SCREENSHOT_HEIGHT, box.height)
							}
						});
					}
				}

				// Screenshot the "Group — Small" display type for processing state
				const groupSmall = targetSection.locator('.dt-body--group-small .group-scroll-item').first();
				if ((await groupSmall.count()) > 0) {
					await groupSmall.scrollIntoViewIfNeeded();
					await page.waitForTimeout(500);

					const box = await groupSmall.boundingBox();
					if (box) {
						await page.screenshot({
							path: path.join(outputDir, 'processing.jpg'),
							type: 'jpeg',
							quality: 85,
							clip: {
								x: box.x,
								y: box.y,
								width: Math.min(SCREENSHOT_WIDTH, box.width),
								height: Math.min(SCREENSHOT_HEIGHT, box.height)
							}
						});
					}
				}

				console.log(`✓ ${app}/${skill.slug}: screenshots captured`);
			}
		});
	});
}
