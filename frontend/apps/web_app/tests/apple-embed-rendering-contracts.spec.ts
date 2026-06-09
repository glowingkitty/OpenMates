/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Web-rendered embed UI contract extraction for Apple parity tests.
 * Drives /dev/preview/embeds/<app> on the deployed web app and writes sanitized
 * screenshot/style artifacts that the native Apple parity workflow pairs with
 * simulator screenshots. Spec source: docs/specs/apple-embed-rendering-parity/spec.yml
 */
export {};

const fs = require('fs');
const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');

const CONTRACT_SCHEMA_VERSION = 1;
const OUTPUT_DIR = path.resolve(process.cwd(), 'test-results', 'apple-ui-contracts', 'embeds');

const VIEWPORTS = [
	{ id: 'iphone', width: 390, height: 844 },
	{ id: 'ipad', width: 1024, height: 1366 }
] as const;

const ALL_APPS = [
	'audio',
	'code',
	'docs',
	'electronics',
	'events',
	'health',
	'home',
	'images',
	'mail',
	'maps',
	'math',
	'music',
	'news',
	'nutrition',
	'pdf',
	'reminder',
	'sheets',
	'shopping',
	'social_media',
	'travel',
	'videos',
	'weather',
	'web'
] as const;

const STYLE_PROPERTIES = [
	'display',
	'position',
	'align-items',
	'justify-content',
	'gap',
	'padding-top',
	'padding-right',
	'padding-bottom',
	'padding-left',
	'border-radius',
	'background-color',
	'color',
	'font-family',
	'font-size',
	'font-weight',
	'line-height',
	'box-shadow',
	'opacity'
];

function roundNumber(value: number | undefined): number | null {
	if (typeof value !== 'number' || Number.isNaN(value)) return null;
	return Math.round(value * 100) / 100;
}

async function waitForAllSectionsLoaded(page: any): Promise<void> {
	await expect(async () => {
		const loadingCount = await page.getByTestId('section-loading').count();
		expect(loadingCount).toBe(0);
	}).toPass({ timeout: 20_000 });
}

async function captureElement(locator: any, semanticId: string, testId: string): Promise<Record<string, unknown>> {
	await expect(locator).toBeVisible({ timeout: 20_000 });
	const box = await locator.boundingBox();
	const data = await locator.evaluate((element: HTMLElement, styleProperties: string[]) => {
		const computed = window.getComputedStyle(element);
		const computedStyle: Record<string, string> = {};
		for (const property of styleProperties) {
			computedStyle[property] = computed.getPropertyValue(property);
		}
		const childTestIds = Array.from(element.querySelectorAll('[data-testid]'))
			.map((child) => child.getAttribute('data-testid'))
			.filter((value): value is string => Boolean(value));
		return {
			tagName: element.tagName.toLowerCase(),
			text: element.textContent?.replace(/\s+/g, ' ').trim().slice(0, 500) ?? '',
			childTestIds,
			computedStyle
		};
	}, STYLE_PROPERTIES);

	return {
		semanticId,
		testId,
		required: true,
		severity: 'fail',
		exists: true,
		structure: {
			tagName: data.tagName,
			childTestIds: data.childTestIds
		},
		visibleText: data.text,
		computedStyle: data.computedStyle,
		boundingBox: box
			? {
					x: roundNumber(box.x),
					y: roundNumber(box.y),
					width: roundNumber(box.width),
					height: roundNumber(box.height)
				}
			: null
	};
}

test.describe('Apple embed rendering web contracts', () => {
	for (const viewport of VIEWPORTS) {
		test(`captures embed contracts for ${viewport.id}`, async ({ page }) => {
			test.setTimeout(180_000);
			await page.setViewportSize({ width: viewport.width, height: viewport.height });
			fs.mkdirSync(OUTPUT_DIR, { recursive: true });

			const states = [];
			const apps = [];

			for (const app of ALL_APPS) {
				const response = await page.goto(`/dev/preview/embeds/${app}`, { waitUntil: 'networkidle' });
				expect(response?.status(), `${app}: preview page status`).toBe(200);
				await waitForAllSectionsLoaded(page);
				expect(await page.getByTestId('section-error').count(), `${app}: section errors`).toBe(0);

				const sections = page.getByTestId('skill-section');
				const sectionCount = await sections.count();
				expect(sectionCount, `${app}: expected at least one skill section`).toBeGreaterThan(0);

				const appDir = path.join(OUTPUT_DIR, viewport.id, app);
				fs.mkdirSync(appDir, { recursive: true });
				const pageScreenshot = path.join(appDir, 'page.png');
				await page.getByTestId('showcase-body').screenshot({ path: pageScreenshot });

				const sectionSummaries = [];
				for (let index = 0; index < sectionCount; index++) {
					const section = sections.nth(index);
					const label = (await section.getByTestId('skill-label').textContent())?.trim() ?? `section-${index}`;
					const headings = await section
						.getByTestId('dt-heading')
						.evaluateAll((nodes: HTMLElement[]) => nodes.map((node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''));
					for (const heading of ['Inline Link', 'Quote Block', 'Group — Small', 'Fullscreen']) {
						expect(headings.some((value: string) => value.includes(heading)), `${app}/${label}: missing ${heading}`).toBe(true);
					}

					const sectionScreenshot = path.join(appDir, `section-${index + 1}.png`);
					await section.screenshot({ path: sectionScreenshot });
					sectionSummaries.push({
						index,
						label,
						headings,
						screenshotPath: sectionScreenshot
					});
				}

				const elements = [
					await captureElement(page.getByTestId('showcase-body'), `${app}:showcase-body`, 'showcase-body'),
					await captureElement(sections.first(), `${app}:skill-section`, 'skill-section'),
					await captureElement(sections.first().getByTestId('fs-clip').first(), `${app}:fullscreen`, 'fs-clip')
				];

				states.push({
					id: `${viewport.id}-${app}`,
					description: `${app} embed showcase at ${viewport.width}x${viewport.height}`,
					elements
				});
				apps.push({ appId: app, sectionCount, screenshotPath: pageScreenshot, sections: sectionSummaries });
			}

			const contract = {
				schemaVersion: CONTRACT_SCHEMA_VERSION,
				surface: 'embeds',
				generatedAt: new Date().toISOString(),
				viewport: { width: viewport.width, height: viewport.height, id: viewport.id },
				apps,
				states
			};
			const outputPath = path.join(OUTPUT_DIR, `embeds.${viewport.id}.generated.json`);
			fs.writeFileSync(outputPath, `${JSON.stringify(contract, null, 2)}\n`, 'utf8');
			expect(states).toHaveLength(ALL_APPS.length);
			expect(outputPath).toContain(`embeds.${viewport.id}.generated.json`);
		});
	}
});
