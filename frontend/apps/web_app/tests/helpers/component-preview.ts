import { expect, type Locator, type Page } from '@playwright/test';

/** Wait for the chrome-free preview route to finish client-side mounting. */
export async function waitForComponentPreview(page: Page, timeout = 30_000) {
	const canvas = page.getByTestId('component-preview-canvas');
	await expect(canvas, 'component preview should finish mounting').toHaveAttribute(
		'data-preview-ready',
		'true',
		{ timeout }
	);
	return canvas;
}

/** Wait for an opening surface to finish its own motion before measuring geometry. */
export async function waitForComponentMotion(surface: Locator, timeout = 5_000) {
	await expect(surface).toBeVisible({ timeout });
	await expect
		.poll(
			async () =>
				surface.evaluate((element) => {
					const style = getComputedStyle(element);
					const transform =
						style.transform === 'none' ? new DOMMatrix() : new DOMMatrix(style.transform);
					return {
						moving: element
							.getAnimations()
							.some((animation) => animation.pending || animation.playState === 'running'),
						opacity: style.opacity,
						identity: transform.isIdentity
					};
				}),
			{ message: 'surface should finish opening before measuring its layout', timeout }
		)
		.toEqual({ moving: false, opacity: '1', identity: true });
}
