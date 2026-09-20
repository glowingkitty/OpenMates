import { expect, type Page } from '@playwright/test';

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
