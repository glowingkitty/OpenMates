/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Browser-rendered embed surface contracts for Apple parity.
 * Drives the existing app showcase routes and emits one sanitized manifest entry
 * per preview, fullscreen, grouped, inline, quote, and exposed status surface.
 * Captures phone, tablet, desktop, light/dark, and RTL dimensions.
 * Spec source: docs/specs/apple-chat-history-full-parity/spec.yml
 */
export {};

const fs = require('fs');
const path = require('path');
const { test, expect } = require('./helpers/cookie-audit');
const {
	EMBED_PREVIEW_COMPONENTS,
	EMBED_FULLSCREEN_COMPONENTS
} = require('../../../packages/ui/src/data/embedRegistry.generated');

const CONTRACT_SCHEMA_VERSION = 1;
const OUTPUT_DIR = path.resolve(process.cwd(), 'test-results', 'apple-ui-contracts', 'embeds');

const DIMENSIONS = [
	{
		id: 'iphone-light-ltr',
		device: 'iphone',
		width: 390,
		height: 844,
		theme: 'light',
		direction: 'ltr'
	},
	{
		id: 'iphone-dark-rtl',
		device: 'iphone',
		width: 390,
		height: 844,
		theme: 'dark',
		direction: 'rtl'
	},
	{
		id: 'ipad-light-ltr',
		device: 'ipad',
		width: 1024,
		height: 1366,
		theme: 'light',
		direction: 'ltr'
	},
	{
		id: 'ipad-dark-rtl',
		device: 'ipad',
		width: 1024,
		height: 1366,
		theme: 'dark',
		direction: 'rtl'
	},
	{
		id: 'macos-light-ltr',
		device: 'macos',
		width: 1440,
		height: 900,
		theme: 'light',
		direction: 'ltr'
	},
	{
		id: 'macos-dark-rtl',
		device: 'macos',
		width: 1440,
		height: 900,
		theme: 'dark',
		direction: 'rtl'
	}
] as const;

const ALL_APPS = [
	'audio',
	'code',
	'docs',
	'electronics',
	'events',
	'fitness',
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

const REQUIRED_SURFACE_HEADINGS = ['Inline Link', 'Quote Block', 'Group — Small', 'Fullscreen'];
const STYLE_PROPERTIES = [
	'display',
	'position',
	'width',
	'min-width',
	'max-width',
	'height',
	'min-height',
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
	'overflow',
	'direction',
	'opacity'
];

function slugify(value: string): string {
	return value
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/(^-|-$)/g, '');
}

async function waitForAllSectionsLoaded(page: any): Promise<void> {
	await expect(async () => {
		expect(await page.getByTestId('section-loading').count()).toBe(0);
	}).toPass({ timeout: 30_000 });
}

async function applyAppearance(
	page: any,
	theme: 'light' | 'dark',
	direction: 'ltr' | 'rtl'
): Promise<void> {
	const body = page.getByTestId('showcase-body');
	await expect(body).toBeVisible({ timeout: 30_000 });
	await body.evaluate((element: HTMLElement, requestedDirection: string) => {
		element.ownerDocument.documentElement.dir = requestedDirection;
	}, direction);
	const currentTheme = await body.evaluate(
		(element: HTMLElement) => element.ownerDocument.documentElement.dataset.theme ?? 'light'
	);
	if (currentTheme !== theme) {
		await page.getByTestId('theme-toggle-btn').click();
	}
	await expect
		.poll(() =>
			body.evaluate(
				(element: HTMLElement) => element.ownerDocument.documentElement.dataset.theme ?? 'light'
			)
		)
		.toBe(theme);
}

async function captureLocator(
	locator: any,
	semanticId: string,
	testId: string
): Promise<Record<string, unknown>> {
	await expect(locator).toBeVisible({ timeout: 30_000 });
	return locator.evaluate(
		(
			element: HTMLElement,
			options: { semanticId: string; testId: string; styleProperties: string[] }
		) => {
			const round = (value: number) => Math.round(value * 100) / 100;
			const computed = window.getComputedStyle(element);
			const computedStyle: Record<string, string> = {};
			for (const property of options.styleProperties) {
				computedStyle[property] = computed.getPropertyValue(property);
			}
			const rect = element.getBoundingClientRect();
			const descendants = Array.from(element.getElementsByTagName('*'));
			return {
				semanticId: options.semanticId,
				testId: options.testId,
				tagName: element.tagName.toLowerCase(),
				role: element.getAttribute('role'),
				ariaLabel: element.getAttribute('aria-label'),
				visibleText: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 500),
				childTestIds: descendants
					.map((child) => child.getAttribute('data-testid'))
					.filter((value): value is string => Boolean(value)),
				data: Object.fromEntries(
					Array.from(element.attributes)
						.filter((attribute) => attribute.name.startsWith('data-'))
						.map((attribute) => [attribute.name, attribute.value])
				),
				computedStyle,
				boundingBox: {
					x: round(rect.x),
					y: round(rect.y),
					width: round(rect.width),
					height: round(rect.height)
				}
			};
		},
		{ semanticId, testId, styleProperties: STYLE_PROPERTIES }
	);
}

async function applyGenericPreviewAppearance(
	page: any,
	theme: 'light' | 'dark',
	direction: 'ltr' | 'rtl'
): Promise<void> {
	const statusBar = page.getByTestId('preview-status-bar');
	await expect(statusBar).toBeVisible({ timeout: 30_000 });
	await statusBar.evaluate(
		(element: HTMLElement, appearance: { theme: string; direction: string }) => {
			element.ownerDocument.documentElement.dir = appearance.direction;
			element.ownerDocument.documentElement.dataset.theme = appearance.theme;
		},
		{ theme, direction }
	);
}

async function captureRegistrySurface(
	page: any,
	dimensionDir: string,
	registryKey: string,
	surface: 'preview' | 'fullscreen',
	componentPath: string,
	theme: 'light' | 'dark',
	direction: 'ltr' | 'rtl'
): Promise<Record<string, unknown>> {
	const routePath = componentPath.replace(/\.svelte$/, '');
	const response = await page.goto(`/dev/preview/embeds/${routePath}`, {
		waitUntil: 'networkidle'
	});
	await applyGenericPreviewAppearance(page, theme, direction);
	const renderError = page.getByTestId('render-error');
	const target =
		surface === 'fullscreen'
			? page.getByTestId('embed-fullscreen-overlay')
			: page
					.getByTestId('embed-preview')
					.or(page.getByTestId('recording-preview'))
					.or(page.getByTestId('focus-mode-bar'));
	const exists =
		(await target.count()) > 0 &&
		(await target
			.first()
			.isVisible()
			.catch(() => false));
	const screenshotPath = path.join(
		dimensionDir,
		'registry',
		`${slugify(registryKey)}-${surface}.png`
	);
	fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
	if (exists) {
		await target.first().screenshot({ path: screenshotPath });
	} else {
		await page.screenshot({ path: screenshotPath, fullPage: true });
	}
	const targetTestId = exists ? await target.first().getAttribute('data-testid') : null;
	return {
		registryKey,
		surface,
		componentPath,
		status: response?.status() ?? null,
		renderError: (await renderError.count()) > 0,
		exists,
		capture: exists
			? await captureLocator(target.first(), `${registryKey}:${surface}`, targetTestId ?? surface)
			: null,
		screenshotPath
	};
}

test.describe('Apple complete embed rendering web contracts', () => {
	for (const dimension of DIMENSIONS) {
		test(`captures every embed surface for ${dimension.id}`, async ({ page }) => {
			test.setTimeout(600_000);
			await page.setViewportSize({ width: dimension.width, height: dimension.height });
			fs.mkdirSync(OUTPUT_DIR, { recursive: true });
			const surfaces = [];
			const apps = [];
			const registrySurfaces = [];
			const registryKeys = Array.from(
				new Set([
					...Object.keys(EMBED_PREVIEW_COMPONENTS),
					...Object.keys(EMBED_FULLSCREEN_COMPONENTS)
				])
			).sort();
			const dimensionDir = path.join(OUTPUT_DIR, dimension.id);

			for (const registryKey of registryKeys) {
				const previewComponent = EMBED_PREVIEW_COMPONENTS[registryKey];
				const fullscreenComponent = EMBED_FULLSCREEN_COMPONENTS[registryKey];
				if (previewComponent) {
					registrySurfaces.push(
						await captureRegistrySurface(
							page,
							dimensionDir,
							registryKey,
							'preview',
							previewComponent,
							dimension.theme,
							dimension.direction
						)
					);
				} else {
					registrySurfaces.push({
						registryKey,
						surface: 'preview',
						exists: false,
						reason: 'missing registry component'
					});
				}
				if (fullscreenComponent) {
					registrySurfaces.push(
						await captureRegistrySurface(
							page,
							dimensionDir,
							registryKey,
							'fullscreen',
							fullscreenComponent,
							dimension.theme,
							dimension.direction
						)
					);
				} else {
					registrySurfaces.push({
						registryKey,
						surface: 'fullscreen',
						exists: false,
						reason: 'missing registry component'
					});
				}
			}

			for (const app of ALL_APPS) {
				const response = await page.goto(`/dev/preview/embeds/${app}`, {
					waitUntil: 'networkidle'
				});
				expect(response?.status(), `${app}: preview page status`).toBe(200);
				await waitForAllSectionsLoaded(page);
				await applyAppearance(page, dimension.theme, dimension.direction);
				expect(await page.getByTestId('section-error').count(), `${app}: section errors`).toBe(0);

				const sections = page.getByTestId('skill-section');
				const sectionCount = await sections.count();
				expect(sectionCount, `${app}: expected at least one skill section`).toBeGreaterThan(0);
				const appDir = path.join(OUTPUT_DIR, dimension.id, app);
				fs.mkdirSync(appDir, { recursive: true });
				const pageScreenshot = path.join(appDir, 'page.png');
				await page.getByTestId('showcase-body').screenshot({ path: pageScreenshot });

				const sectionSummaries = [];
				for (let index = 0; index < sectionCount; index++) {
					const section = sections.nth(index);
					const label =
						(await section.getByTestId('skill-label').textContent())?.trim() ??
						`section-${index + 1}`;
					const surfaceKey = `${app}:${slugify(label)}:${index + 1}`;
					const headings = await section
						.getByTestId('dt-heading')
						.evaluateAll((nodes: HTMLElement[]) =>
							nodes.map((node) => (node.textContent ?? '').replace(/\s+/g, ' ').trim())
						);
					for (const heading of REQUIRED_SURFACE_HEADINGS) {
						expect(
							headings.some((value: string) => value.includes(heading)),
							`${surfaceKey}: missing ${heading}`
						).toBe(true);
					}

					const previews = section.getByTestId('embed-preview');
					const previewCount = await previews.count();
					expect(previewCount, `${surfaceKey}: missing dedicated previews`).toBeGreaterThan(0);
					const fullscreen = section.getByTestId('fs-clip');
					await expect(fullscreen, `${surfaceKey}: missing dedicated fullscreen`).toBeVisible({
						timeout: 30_000
					});

					const sectionScreenshot = path.join(
						appDir,
						`${index + 1}-${slugify(label)}-all-surfaces.png`
					);
					await section.screenshot({ path: sectionScreenshot });
					const fullscreenScreenshot = path.join(
						appDir,
						`${index + 1}-${slugify(label)}-fullscreen.png`
					);
					await fullscreen.screenshot({ path: fullscreenScreenshot });

					const previewContracts = [];
					for (let previewIndex = 0; previewIndex < previewCount; previewIndex++) {
						const preview = previews.nth(previewIndex);
						const previewScreenshot = path.join(
							appDir,
							`${index + 1}-${slugify(label)}-preview-${previewIndex + 1}.png`
						);
						await preview.screenshot({ path: previewScreenshot });
						previewContracts.push({
							capture: await captureLocator(
								preview,
								`${surfaceKey}:preview:${previewIndex + 1}`,
								'embed-preview'
							),
							screenshotPath: previewScreenshot
						});
					}

					const statusVariants = Array.from(
						new Set(
							previewContracts
								.map((entry: any) => entry.capture.data?.['data-status'])
								.filter(
									(value: unknown): value is string => typeof value === 'string' && value.length > 0
								)
						)
					).sort();
					const manifestEntry = {
						key: surfaceKey,
						appId: app,
						skillLabel: label,
						sources: {
							inline: headings.some((value: string) => value.includes('Inline Link')),
							quote: headings.some((value: string) => value.includes('Quote Block')),
							groupSmall: headings.some((value: string) => value.includes('Group — Small')),
							groupLarge: headings.some((value: string) => value.includes('Group — Large')),
							preview: previewCount > 0,
							fullscreen: true
						},
						statusVariants,
						headings,
						section: await captureLocator(section, `${surfaceKey}:section`, 'skill-section'),
						previews: previewContracts,
						fullscreen: await captureLocator(fullscreen, `${surfaceKey}:fullscreen`, 'fs-clip'),
						artifacts: { section: sectionScreenshot, fullscreen: fullscreenScreenshot }
					};
					surfaces.push(manifestEntry);
					sectionSummaries.push({ key: surfaceKey, label, previewCount, statusVariants });
				}
				apps.push({
					appId: app,
					sectionCount,
					screenshotPath: pageScreenshot,
					sections: sectionSummaries
				});
			}

			const contract = {
				schemaVersion: CONTRACT_SCHEMA_VERSION,
				surface: 'embeds',
				dimension,
				apps,
				surfaces,
				registrySurfaces
			};
			const outputPath = path.join(OUTPUT_DIR, `embeds.${dimension.id}.generated.json`);
			fs.writeFileSync(outputPath, `${JSON.stringify(contract, null, 2)}\n`, 'utf8');
			expect(apps).toHaveLength(ALL_APPS.length);
			expect(surfaces.length).toBeGreaterThan(ALL_APPS.length);
			expect(
				registrySurfaces.filter((entry: any) => !entry.exists),
				'Every generated registry key must render dedicated preview and fullscreen content.'
			).toEqual([]);
			expect(outputPath).toContain(`embeds.${dimension.id}.generated.json`);
		});
	}
});
