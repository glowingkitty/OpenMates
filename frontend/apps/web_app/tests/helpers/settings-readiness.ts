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

/**
 * Opens one app's settings the way a user does: the app page in the Apps
 * workspace, then its settings button. Legacy `#settings/apps/...` links now
 * forward to the app page instead of the settings menu.
 */
export async function openAppSettings(page: Page, appUrl: string, appId: string) {
	await page.goto(appUrl, { waitUntil: 'domcontentloaded' });
	await expect(page.getByTestId('apps-detail-fullscreen')).toBeVisible({ timeout: 30_000 });
	await page.getByTestId('apps-settings-open').click();
	const menu = page.locator(`[data-testid="settings-menu"][data-active-view="apps/${appId}"]`);
	await expect(menu).toBeVisible({ timeout: 15_000 });
	return menu;
}
