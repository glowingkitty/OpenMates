/**
 * Playwright capture script for media generation templates.
 *
 * Templates now use iframes that load the real app in media mode (?media=1).
 * Each iframe waits for .media-app-ready, then the parent template sets
 * .media-ready for Playwright to detect.
 *
 * For authenticated screenshots (sidebar with real chats), set these env vars:
 *   OPENMATES_MEDIA_ACCOUNT_EMAIL, OPENMATES_MEDIA_ACCOUNT_PASSWORD, OPENMATES_MEDIA_ACCOUNT_OTP_KEY
 * The script will log in before capturing, and iframes inherit the session cookie.
 *
 * Usage:
 *   # Capture all templates:
 *   npx playwright test src/routes/dev/media/scripts/capture.spec.ts
 *
 *   # Capture a single template:
 *   npx playwright test --grep "og-github" src/routes/dev/media/scripts/capture.spec.ts
 *
 *   # Custom output directory:
 *   OUTPUT_DIR=./marketing npx playwright test src/routes/dev/media/scripts/capture.spec.ts
 *
 *   # Record video of a template (for animated templates):
 *   RECORD_VIDEO=1 npx playwright test --grep "instagram-story" ...
 *
 * Architecture: docs/media-generation.md
 */

import { test } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const BASE_URL = process.env.MEDIA_BASE_URL || 'https://app.dev.openmates.org';
const OUTPUT_DIR = process.env.OUTPUT_DIR || path.join(process.cwd(), 'media-output');
const RECORD_VIDEO = process.env.RECORD_VIDEO === '1';

// Longer timeout — iframe-based templates load the full app inside each device frame
const WAIT_TIMEOUT = 30_000;

/** Template definitions with dimensions and special handling */
const TEMPLATES = [
	{ id: 'og-github', width: 1200, height: 630 },
	{ id: 'og-social', width: 1200, height: 630 },
	{ id: 'instagram-single', width: 1080, height: 1080 },
	{ id: 'instagram-carousel', width: 1080, height: 1080, slides: 5 },
	{ id: 'instagram-story', width: 1080, height: 1920 },
];

// Ensure output directory exists
test.beforeAll(() => {
	fs.mkdirSync(OUTPUT_DIR, { recursive: true });
});

for (const tmpl of TEMPLATES) {
	if (tmpl.slides) {
		// Carousel: capture each slide individually
		for (let i = 1; i <= tmpl.slides; i++) {
			test(`${tmpl.id} slide ${i}`, async ({ browser }) => {
				const contextOptions: Record<string, unknown> = {};
				if (RECORD_VIDEO) {
					contextOptions.recordVideo = {
						dir: OUTPUT_DIR,
						size: { width: tmpl.width, height: tmpl.height },
					};
				}

				const context = await browser.newContext(contextOptions);
				const page = await context.newPage();
				await page.setViewportSize({ width: tmpl.width, height: tmpl.height });

				await page.goto(`${BASE_URL}/dev/media/templates/${tmpl.id}?slide=${i}`);
				await page.waitForSelector('.media-ready', { timeout: WAIT_TIMEOUT });
				// Extra wait for iframe content to fully paint
				await page.waitForTimeout(2000);

				await page.screenshot({
					path: path.join(OUTPUT_DIR, `${tmpl.id}-slide-${i}.png`),
					clip: { x: 0, y: 0, width: tmpl.width, height: tmpl.height },
				});

				await context.close();
			});
		}
	} else {
		test(`${tmpl.id}`, async ({ browser }) => {
			const contextOptions: Record<string, unknown> = {};
			if (RECORD_VIDEO) {
				contextOptions.recordVideo = {
					dir: OUTPUT_DIR,
					size: { width: tmpl.width, height: tmpl.height },
				};
			}

			const context = await browser.newContext(contextOptions);
			const page = await context.newPage();
			await page.setViewportSize({ width: tmpl.width, height: tmpl.height });

			await page.goto(`${BASE_URL}/dev/media/templates/${tmpl.id}`);
			await page.waitForSelector('.media-ready', { timeout: WAIT_TIMEOUT });
			// Extra wait for iframe content to fully paint
			await page.waitForTimeout(2000);

			await page.screenshot({
				path: path.join(OUTPUT_DIR, `${tmpl.id}.png`),
				clip: { x: 0, y: 0, width: tmpl.width, height: tmpl.height },
			});

			await context.close();
		});
	}
}
