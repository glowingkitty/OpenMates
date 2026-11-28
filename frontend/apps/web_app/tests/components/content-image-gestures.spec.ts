import { expect, test } from '../helpers/cookie-audit';
import type { Locator } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const previewPath = '/dev/preview/embeds/images/ImageResultEmbedFullscreen';
const cardPreviewPath = '/dev/preview/embeds/images/ImageResultEmbedPreview';
const captureConfig = 'theme=light&background=%23dbeafe&width=390&chrome=0';

test.describe('Touch zoom stays inside rendered images', () => {
	test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });

	// contract-test: supporting surface=gui.web assertions=chats.rendering.image-gestures,design-embroidery.result.view-and-download
	test('pinches, pans, and double-taps images without moving or reloading the app', async ({ page, context, browserName }, testInfo) => {
		test.skip(browserName !== 'chromium', 'Uses Chromium mobile touch input through CDP');
		test.setTimeout(120_000);
		const fixture = await page.request.get('/images/examples/group1.jpg');
		expect(fixture.ok()).toBeTruthy();
		const photo = await fixture.body();
		await page.route('**/api/v1/image?*', route => route.fulfill({ contentType: 'image/jpeg', body: photo }));
		const session = await context.newCDPSession(page);
		const touch = (type: 'touchStart' | 'touchMove' | 'touchEnd', ...touchPoints: { x: number; y: number; id: number }[]) =>
			session.send('Input.dispatchTouchEvent', { type, touchPoints });

		async function proveImageZoom(image: Locator, name: string) {
			await expect(image).toBeVisible();
			await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
			await image.scrollIntoViewIfNeeded();
			const { x, y } = await image.evaluate(element => {
				const box = element.getBoundingClientRect();
				return { x: box.left + box.width / 2, y: (Math.max(0, box.top) + Math.min(innerHeight, box.bottom)) / 2 };
			});
			const pageState = () => page.evaluate(() => ({
				url: location.href,
				timeOrigin: performance.timeOrigin,
				scale: visualViewport?.scale,
				width: document.documentElement.clientWidth,
				viewportTags: document.querySelectorAll('meta[name="viewport"]').length,
			}));
			const before = await pageState();
			expect(before.scale).toBe(1);
			expect(before.viewportTags).toBe(1);

			await touch('touchStart', { x: x - 20, y, id: 1 }, { x: x + 20, y, id: 2 });
			await touch('touchMove', { x: x - 44, y, id: 1 }, { x: x + 44, y, id: 2 });
			await touch('touchEnd');
			await expect(image).toHaveAttribute('data-content-zoomed', '');
			await expect.poll(() => image.evaluate(element => Number(getComputedStyle(element).scale))).toBeGreaterThan(1.5);
			expect(await pageState()).toEqual(before);

			const initialTranslation = await image.evaluate(element => getComputedStyle(element).translate);
			await touch('touchStart', { x, y, id: 1 });
			await touch('touchMove', { x: x + 32, y: y + 10, id: 1 });
			await touch('touchEnd');
			await expect.poll(() => image.evaluate(element => getComputedStyle(element).translate)).not.toBe(initialTranslation);
			expect(await pageState()).toEqual(before);
			await testInfo.attach(`${name}-pinched-and-panned`, { body: await page.screenshot(), contentType: 'image/png' });

			await page.touchscreen.tap(x, y);
			await page.touchscreen.tap(x, y);
			await expect(image).not.toHaveAttribute('data-content-zoomed', '');
			await page.touchscreen.tap(x, y);
			await page.touchscreen.tap(x, y);
			await expect(image).toHaveAttribute('data-content-zoomed', '');
			expect(await pageState()).toEqual(before);
		}

		for (const [path, id, name] of [
			[previewPath, 'image-result-fullscreen-image', 'image'],
			[cardPreviewPath, 'image-result-preview-image', 'image-preview'],
		]) {
			await page.goto(`${path}?${captureConfig}`);
			await waitForComponentPreview(page);
			await proveImageZoom(page.getByTestId(id), name);
		}
		for (const [path, name] of [
			['web/WebsiteEmbedFullscreen', 'website'],
			['news/NewsArticleEmbedFullscreen', 'news'],
		]) {
			await page.goto(`/dev/preview/embeds/${path}?${captureConfig}&variant=withSnippets`);
			await waitForComponentPreview(page);
			await proveImageZoom(page.getByTestId('result-embed-content').getByRole('img', { name: /svelte/i }), name);
		}

		await page.goto(`/dev/preview/embeds/design/DesignEmbroideryEmbedFullscreen?${captureConfig}&variant=finished`);
		await waitForComponentPreview(page);
		const embroidery = page.getByTestId('design-embroidery-image');
		await expect(embroidery).toHaveAttribute('data-view', 'stitches');
		await proveImageZoom(embroidery, 'embroidery-stitches');
		await page.getByTestId('design-embroidery-view-graphic').click();
		await expect(embroidery).toHaveAttribute('data-view', 'graphic');
		await expect(embroidery).not.toHaveAttribute('data-content-zoomed', '');
		await proveImageZoom(embroidery, 'embroidery-graphic');
	});

	// contract-test: supporting surface=gui.web assertions=chats.rendering.embed-zoom-view
	test('uses each canvas zoom control for double-tap and pinch', async ({ page, context, browserName }, testInfo) => {
		test.skip(browserName !== 'chromium', 'Uses Chromium mobile touch input through CDP');
		test.setTimeout(120_000);
		const session = await context.newCDPSession(page);
		for (const [path, canvas, zoom] of [
			['docs/DocsEmbedFullscreen', page.getByRole('region', { name: 'Document viewer' }), page.getByRole('button', { name: 'Reset zoom', exact: true })],
			['diagrams/MermaidDiagramEmbedFullscreen', page.getByTestId('mermaid-rendered-panel'), page.getByTestId('mermaid-fit')],
			['mindmaps/MindMapEmbedFullscreen', page.getByTestId('mindmap-fullscreen-canvas'), page.getByTestId('mindmap-zoom-reset')],
			['diagrams/DiagramHtmlEmbedFullscreen', page.getByTestId('diagram-html-canvas'), page.getByTestId('diagram-html-zoom-fit')],
		] as const) {
			await page.goto(`/dev/preview/embeds/${path}?${captureConfig}`);
			await waitForComponentPreview(page);
			await canvas.scrollIntoViewIfNeeded();
			await expect(zoom).toHaveText(/\d+%/);
			await zoom.click();
			const fit = Number.parseInt((await zoom.textContent())!, 10);
			const view = await canvas.boundingBox();
			expect(view).not.toBeNull();
			const x = view!.x + view!.width / 2;
			const y = Math.max(0, view!.y) + 80;
			const timeOrigin = await page.evaluate(() => performance.timeOrigin);
			await page.touchscreen.tap(x, y);
			await page.touchscreen.tap(x, y);
			await expect.poll(async () => Number.parseInt((await zoom.textContent())!, 10)).toBeGreaterThan(fit);
			await testInfo.attach(`${path.split('/')[1]}-zoomed`, { body: await page.screenshot(), contentType: 'image/png' });
			await page.touchscreen.tap(x, y);
			await page.touchscreen.tap(x, y);
			await expect(zoom).toHaveText(`${fit}%`);

			await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x - 18, y, id: 1 }, { x: x + 18, y, id: 2 }] });
			await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x - 34, y, id: 1 }, { x: x + 34, y, id: 2 }] });
			await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
			await expect.poll(async () => Number.parseInt((await zoom.textContent())!, 10)).toBeGreaterThan(fit);
			expect(await page.evaluate(() => [performance.timeOrigin, visualViewport?.scale])).toEqual([timeOrigin, 1]);
		}
	});
});
