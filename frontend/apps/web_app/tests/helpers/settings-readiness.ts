import { expect, type Page, type TestInfo } from '@playwright/test';

/** Desktop drawers remain mounted while clipped; DOM visibility is not closed state. */
export async function closeSettingsPanel(page: Page, testInfo: TestInfo): Promise<void> {
	const toggle = page.getByTestId('profile-container');
	const menu = page.getByTestId('settings-menu');
	try {
		await page.getByTestId('icon-button-close').click();
		await expect(toggle).toHaveAttribute('data-action', 'open-settings');
		await expect(menu).toHaveCSS('opacity', '0');
	} catch (error) {
		await testInfo.attach('settings-close-state', {
			body: JSON.stringify({ toggleAction: await toggle.getAttribute('data-action'), menuBounds: await menu.boundingBox() }),
			contentType: 'application/json'
		});
		throw error;
	}
}

/** A restored settings route can appear before its asynchronous data is ready. */
export async function waitForSettingsView(
	page: Page,
	testInfo: TestInfo,
	view: string,
	readyTestId: string
): Promise<void> {
	const menu = page.getByTestId('settings-menu');
	const ready = page.getByTestId(readyTestId);
	try {
		await expect(menu).toHaveAttribute('data-active-view', view, { timeout: 30_000 });
		await expect(ready).toBeVisible({ timeout: 30_000 });
	} catch (error) {
		await testInfo.attach('settings-readiness', {
			body: JSON.stringify({
				expectedView: view,
				activeView: await menu.getAttribute('data-active-view').catch(() => null),
				readyTestId,
				readyElementCount: await ready.count()
			}),
			contentType: 'application/json'
		});
		throw error;
	}
}
