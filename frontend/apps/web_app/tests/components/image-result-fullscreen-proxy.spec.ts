import { expect, test } from '../helpers/cookie-audit';
import type { Locator } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const previewPath = '/dev/preview/embeds/images/ImageResultEmbedFullscreen';
const cardPreviewPath = '/dev/preview/embeds/images/ImageResultEmbedPreview';
const captureConfig = 'theme=light&background=%23dbeafe&width=390&chrome=0';

test.describe('Image result fullscreen preview', () => {
	// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
	test('loads external image bytes through the privacy proxy', async ({ page }) => {
		await page.setViewportSize({ width: 390, height: 844 });
		const fixture = await page.request.get('/images/examples/group1.jpg');
		expect(fixture.ok()).toBeTruthy();
		const fixtureBytes = await fixture.body();
		await page.route('**/api/v1/image?*', (route) =>
			route.fulfill({ status: 200, contentType: 'image/jpeg', body: fixtureBytes })
		);
		await page.goto(`${previewPath}?${captureConfig}`);
		await waitForComponentPreview(page);
		const image = page.getByTestId('image-result-fullscreen-image');
		await expect(image).toBeVisible({ timeout: 30_000 });
		await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth), {
			timeout: 30_000
		}).toBeGreaterThan(0);
		const source = new URL((await image.getAttribute('src')) || '', page.url());
		expect(source.pathname).toBe('/api/v1/image');
		expect(source.searchParams.get('max_width')).toBe('1024');
		expect(source.searchParams.get('url')).toBe(
			'https://images.unsplash.com/photo-1501594907352-04cda38ebc29'
		);
		await expect(page.getByTestId('image-result-fullscreen-placeholder')).toHaveCount(0);
		await expect(page.locator('.result-title')).toHaveText('Golden Gate Bridge at dusk');
		await expect(page.locator('.source-link')).toHaveAttribute('href', 'https://unsplash.com/photos/Cs99I6PYLlk');
		await expect(page.locator('.open-image-link')).toHaveAttribute(
			'href',
			'https://images.unsplash.com/photo-1501594907352-04cda38ebc29'
		);
		const imageBox = await image.boundingBox();
		expect(imageBox).not.toBeNull();
		expect(imageBox!.x).toBeGreaterThanOrEqual(0);
		expect(imageBox!.x + imageBox!.width).toBeLessThanOrEqual(390);
		const sectionBox = await page.locator('.image-section').boundingBox();
		expect(sectionBox).not.toBeNull();
		expect(sectionBox!.x + sectionBox!.width).toBeLessThanOrEqual(390);
	});

	// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
	test('shows the placeholder after full image and thumbnail both fail', async ({ page }) => {
		await page.goto(`${previewPath}?${captureConfig}&variant=failedImage`);
		await waitForComponentPreview(page);
		const placeholder = page.getByTestId('image-result-fullscreen-placeholder');
		await expect(placeholder).toBeVisible();
		await expect(placeholder).toHaveCSS('width', '200px');
		await expect(placeholder).toHaveCSS('height', '200px');
		await expect(page.getByTestId('image-result-fullscreen-image')).toHaveCount(0);
		await expect(page.locator('.source-link')).toHaveAttribute('href', 'https://unsplash.com/photos/Cs99I6PYLlk');
		await expect(page.locator('.open-image-link')).toHaveAttribute('href', 'data:image/png;base64,invalid-image');
	});
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('standalone image result preview loads through the same privacy proxy', async ({ page }) => {
	const fixture = await page.request.get('/images/examples/group1.jpg');
	expect(fixture.ok()).toBeTruthy();
	const fixtureBytes = await fixture.body();
	await page.route('**/api/v1/image?*', (route) =>
		route.fulfill({ status: 200, contentType: 'image/jpeg', body: fixtureBytes })
	);
	await page.goto(`${cardPreviewPath}?${captureConfig}`);
	await waitForComponentPreview(page);
	const image = page.getByTestId('image-result-preview-image');
	await expect(image).toBeVisible({ timeout: 30_000 });
	await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth), {
		timeout: 30_000
	}).toBeGreaterThan(0);
	const source = new URL((await image.getAttribute('src')) || '', page.url());
	expect(source.pathname).toBe('/api/v1/image');
	expect(source.searchParams.get('max_width')).toBe('520');
	expect(source.searchParams.get('url')).toBe(
		'https://images.unsplash.com/photo-1501594907352-04cda38ebc29'
	);
});

/** Resolve the expected surface from the active theme, as the component does. */
async function expectSurfaceColor(
	surface: Locator,
	expression: string,
	property: 'backgroundColor' | 'color' = 'backgroundColor',
) {
	await expect(surface).toBeVisible();
	await expect.poll(() => surface.evaluate((element, { background, property }) => {
		const style = getComputedStyle(element);
		const tokens = background.match(/--[a-z0-9-]+/g) || [];
		const tokensDefined = tokens.every((token) => style.getPropertyValue(token).trim().length > 0);
		const probe = document.createElement('span');
		probe.style[property] = background;
		element.appendChild(probe);
		const expected = getComputedStyle(probe)[property];
		probe.remove();
		return { tokensDefined, matches: style[property] === expected };
	}, { background: expression, property })).toEqual({ tokensDefined: true, matches: true });
}

for (const theme of ['light', 'dark'] as const) {
	// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
	test(`image result surfaces render with active ${theme} palette tokens`, async ({ page }, testInfo) => {
		test.setTimeout(90_000);
		await page.setViewportSize({ width: 390, height: 844 });
		const fixture = await page.request.get('/images/examples/group1.jpg');
		expect(fixture.ok()).toBeTruthy();
		const fixtureBytes = await fixture.body();
		let failImage = false;
		await page.route('**/api/v1/image?*', (route) => route.fulfill({
			status: 200,
			contentType: 'image/jpeg',
			body: failImage ? Buffer.from('invalid-image') : fixtureBytes,
		}));
		const config = `theme=${theme}&background=%23dbeafe&width=390&chrome=0`;
		const placeholderBackground = theme === 'dark'
			? 'var(--color-grey-20)'
			: 'color-mix(in srgb, var(--color-grey-20) 27.272727%, var(--color-grey-25))';
		const sectionBackground = theme === 'dark' ? 'var(--color-grey-0)' : 'var(--color-grey-5)';
		const attachSurface = async (state: string) => testInfo.attach(`image-result-${theme}-${state}`, {
			body: await page.getByTestId('component-preview-canvas').screenshot(),
			contentType: 'image/png',
		});

		await page.goto(`${cardPreviewPath}?${config}`);
		await waitForComponentPreview(page);
		await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
		const previewImage = page.getByTestId('image-result-preview-image');
		await expect(previewImage).toHaveCSS('opacity', '1');
		await expect.poll(() => previewImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
		await expectSurfaceColor(previewImage, placeholderBackground);
		await attachSurface('preview-loaded');

		failImage = true;
		await page.goto(`${cardPreviewPath}?${config}`);
		await waitForComponentPreview(page);
		await expectSurfaceColor(page.locator('.image-result-content .image-placeholder'), placeholderBackground);
		await expect(page.getByTestId('image-result-preview-image')).toHaveCount(0);
		await attachSurface('preview-placeholder');

		await page.goto(`${cardPreviewPath}?${config}&variant=processing`);
		await waitForComponentPreview(page);
		await expectSurfaceColor(page.locator('.skeleton-image'), placeholderBackground);
		await attachSurface('preview-processing');

		failImage = false;
		await page.goto(`${previewPath}?${config}`);
		await waitForComponentPreview(page);
		const fullscreenImage = page.getByTestId('image-result-fullscreen-image');
		await expect(fullscreenImage).toHaveCSS('opacity', '1');
		await expect.poll(() => fullscreenImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
		await expectSurfaceColor(page.locator('.image-section'), sectionBackground);
		await expectSurfaceColor(page.locator('.result-title'), 'var(--color-grey-90)', 'color');
		await attachSurface('fullscreen-loaded');

		await page.goto(`${previewPath}?${config}&variant=failedImage`);
		await waitForComponentPreview(page);
		await expectSurfaceColor(page.getByTestId('image-result-fullscreen-placeholder'), placeholderBackground);
		await expect(page.getByTestId('image-result-fullscreen-image')).toHaveCount(0);
		await expectSurfaceColor(page.locator('.image-section'), sectionBackground);
		await expectSurfaceColor(page.locator('.result-title'), 'var(--color-grey-90)', 'color');
		await attachSurface('fullscreen-placeholder');
	});
}
