/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Settings Apps navigation regression.
 *
 * Guards the guest Settings > Apps flow after runtime app metadata loads. The
 * live API returns provider metadata objects, while app cards historically
 * expected provider-name strings; remounting Apps after visiting other settings
 * pages could leave the Apps page blank and prevent app details from opening.
 */

const { test, expect } = require('./console-monitor');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

const SETTINGS_TIMEOUT = 15_000;

async function openSettings(page: any): Promise<any> {
	await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
	await page.waitForLoadState('networkidle');

	const settingsToggle = page.getByTestId('profile-container');
	await expect(settingsToggle).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await settingsToggle.click();

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'main');
	return settingsMenu;
}

async function openTopLevelSettingsPage(settingsMenu: any, pageName: string): Promise<void> {
	await settingsMenu.getByRole('menuitem', { name: new RegExp(`^${pageName}$`, 'i') }).click();
	await expect(settingsMenu).toHaveAttribute(
		'data-active-view',
		pageName.toLowerCase() === 'memories' ? 'settings_memories' : pageName.toLowerCase(),
		{ timeout: SETTINGS_TIMEOUT }
	);
}

async function backToSettingsRoot(settingsMenu: any): Promise<void> {
	await settingsMenu.getByTestId('banner-back-button').click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'main', {
		timeout: SETTINGS_TIMEOUT
	});
}

async function expectAppsCatalogLoaded(settingsMenu: any): Promise<void> {
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'apps', {
		timeout: SETTINGS_TIMEOUT
	});
	await expect(settingsMenu.getByRole('menuitem', { name: /show all apps/i })).toBeVisible({
		timeout: SETTINGS_TIMEOUT
	});
	await expect(settingsMenu.getByTestId('app-store-card').first()).toBeVisible({
		timeout: SETTINGS_TIMEOUT
	});
}

test('guest Apps catalog survives settings navigation and opens app details', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(120_000);

	const settingsMenu = await openSettings(page);

	await openTopLevelSettingsPage(settingsMenu, 'Apps');
	await expectAppsCatalogLoaded(settingsMenu);
	await backToSettingsRoot(settingsMenu);

	for (const pageName of ['AI', 'Memories', 'Interface']) {
		await openTopLevelSettingsPage(settingsMenu, pageName);
		await backToSettingsRoot(settingsMenu);
	}

	await openTopLevelSettingsPage(settingsMenu, 'Apps');
	await expectAppsCatalogLoaded(settingsMenu);

	const webAppCard = settingsMenu.locator('[data-testid="app-store-card"][data-app-id="web"]').first();
	await expect(webAppCard).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await webAppCard.click();

	await expect(settingsMenu).toHaveAttribute('data-active-view', 'apps/web', {
		timeout: SETTINGS_TIMEOUT
	});
	await expect(settingsMenu.getByTestId('settings-banner-shell')).toContainText(/web/i, {
		timeout: SETTINGS_TIMEOUT
	});
});
