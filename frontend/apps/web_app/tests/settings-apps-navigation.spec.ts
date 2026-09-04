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
const INACTIVE_APP_IDS = ['plans', 'projects', 'tasks', 'workflows'];
const INACTIVE_APP_FEATURE_IDS = INACTIVE_APP_IDS.flatMap((appId) => [`platform:${appId}`, `app:${appId}`]);

async function mockInactiveWorkspaceApps(page: any): Promise<void> {
	await page.route('**/v1/features/availability', async (route: any) => {
		await route.fulfill({
			contentType: 'application/json',
			body: JSON.stringify({ disabled: INACTIVE_APP_FEATURE_IDS })
		});
	});
}

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
	await expect(settingsMenu.getByTestId('settings-page-content')).toHaveCount(1);
	await expect(settingsMenu.getByTestId('ai-settings')).toHaveCount(pageName === 'AI' ? 1 : 0);
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
	for (const appId of INACTIVE_APP_IDS) {
		await expect(settingsMenu.locator(`[data-testid="app-store-card"][data-app-id="${appId}"]`)).toHaveCount(0);
	}
}

// contract-test: direct surface=gui.web assertions=settings-ui.navigation.contextual-availability,settings-ui.shell.lifecycle-and-routing,workspace-shell.nav.released-surfaces-visible
test('guest settings routes replace AI after opening a dynamic provider page', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(120_000);
	await mockInactiveWorkspaceApps(page);

	const settingsMenu = await openSettings(page);

	await openTopLevelSettingsPage(settingsMenu, 'Apps');
	await expectAppsCatalogLoaded(settingsMenu);
	await backToSettingsRoot(settingsMenu);

	await openTopLevelSettingsPage(settingsMenu, 'AI');
	await settingsMenu.getByTestId('ai-provider-family-card').first().click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', /^ai\/provider\//, {
		timeout: SETTINGS_TIMEOUT
	});
	await expect(settingsMenu.getByTestId('ai-settings')).toHaveCount(0);
	await expect(settingsMenu.getByTestId('ai-provider-details')).toBeVisible({
		timeout: SETTINGS_TIMEOUT
	});

	await settingsMenu.getByTestId('banner-back-button').click();
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'ai', {
		timeout: SETTINGS_TIMEOUT
	});
	await backToSettingsRoot(settingsMenu);

	for (const pageName of ['Mates', 'Memories', 'Interface']) {
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

// contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
test('combined chat settings deep link hydrates chat context after reload', async ({
	page
}: {
	page: any;
}) => {
	await page.goto(
		getE2EDebugUrl('/#chat-id=example-artemis&settings=chats/example-artemis/tasks'),
		{ waitUntil: 'domcontentloaded' }
	);

	const settingsMenu = page.getByTestId('settings-menu');
	await expect(settingsMenu).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await expect(settingsMenu).toHaveAttribute('data-active-view', 'chats/example-artemis', {
		timeout: SETTINGS_TIMEOUT
	});

	const chatSettingsPage = settingsMenu.getByTestId('chat-settings-page');
	await expect(chatSettingsPage).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await expect(chatSettingsPage).not.toContainText(/Open a chat before viewing chat settings/i, {
		timeout: SETTINGS_TIMEOUT
	});
	await expect(settingsMenu.getByTestId('chat-settings-tabs')).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await expect(settingsMenu.getByTestId('chat-settings-tabpanel-tasks')).toBeVisible({
		timeout: SETTINGS_TIMEOUT
	});
});
