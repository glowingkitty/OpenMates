/* eslint-disable @typescript-eslint/no-require-imports */
export {};

/**
 * Apps workspace navigation regression.
 *
 * Guards the guest Apps flow after runtime app metadata loads. The
 * live API returns provider metadata objects, while app cards historically
 * expected provider-name strings; remounting Apps after visiting other settings
 * pages could leave the Apps page blank and prevent app details from opening.
 */

const { test, expect } = require('./console-monitor');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { enterRuntimeAppsCatalog, expectRuntimeAppsCatalogIds } = require('./helpers/apps-catalog-readiness');

const SETTINGS_TIMEOUT = 15_000;
const EXCLUDED_APP_IDS = ['openmates', 'plans', 'projects', 'tasks', 'workflows'];
const EMPTY_APP_IDS = ['health', 'home', 'models3d', 'travel', 'events', 'fitness', 'hosting', 'shopping', 'tv', 'ideabucket'];
const RETAINED_APP_IDS = ['web', 'weather', 'jobs', 'docs', 'mindmaps', 'diagrams', 'electronics'];

async function enableAllWorkspaceFeatures(page: any): Promise<void> {
	await page.route('**/v1/features/availability', async (route: any) => {
		await route.fulfill({
			contentType: 'application/json',
			body: JSON.stringify({ disabled: [] })
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

async function expectAppsCatalogLoaded(page: any): Promise<void> {
	await expect(page.getByTestId('apps-workspace')).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await expect(page.getByTestId('apps-all-items-grid').locator('[data-app-id]').first()).toBeVisible({
		timeout: SETTINGS_TIMEOUT
	});
	for (const appId of RETAINED_APP_IDS) {
		await expect(page.getByTestId('apps-all-items-grid').locator(`[data-app-id="${appId}"]`)).toBeVisible();
	}
	for (const appId of [...EXCLUDED_APP_IDS, ...EMPTY_APP_IDS]) {
		await expect(page.getByTestId('apps-all-items-grid').locator(`[data-app-id="${appId}"]`)).toHaveCount(0);
	}
}

// contract-test: direct surface=gui.web assertions=settings-ui.navigation.contextual-availability,settings-ui.shell.lifecycle-and-routing,workspace-shell.nav.released-surfaces-visible,apps.discovery.public-catalog
test('guest settings routes replace AI after opening a dynamic provider page', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(120_000);
	await enableAllWorkspaceFeatures(page);

	const settingsMenu = await openSettings(page);

	await expect(settingsMenu.getByRole('menuitem', { name: /^Apps$/i })).toHaveCount(0);

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

	// Legacy Settings catalog links forward to Apps. Shared Settings rendering
	// is covered by apps-catalog-availability; retain the supported full route.
	const forwardedIds = await enterRuntimeAppsCatalog(page, 'forwarded-settings', () =>
		page.goto(getE2EDebugUrl('/#settings/apps/all'), { waitUntil: 'domcontentloaded' }));
	await expect(page).toHaveURL(/#apps\/all(?:&|$)/, { timeout: SETTINGS_TIMEOUT });
	await expectAppsCatalogLoaded(page);
  await page.goto(getE2EDebugUrl('/#apps/all'), { waitUntil: 'domcontentloaded' });
  await expectRuntimeAppsCatalogIds(page, 'direct-apps', forwardedIds);
	await expectAppsCatalogLoaded(page);
	await expect(page).toHaveURL(/#apps\/all(?:&|$)/);
	const reloadedIds = await enterRuntimeAppsCatalog(page, 'reloaded-apps', () =>
		page.reload({ waitUntil: 'domcontentloaded' }));
	await expectAppsCatalogLoaded(page);
	expect(reloadedIds).toEqual(forwardedIds);
	await expect(page).toHaveURL(/#apps\/all(?:&|$)/);

	const webAppCard = page.getByTestId('apps-all-items-grid').locator('[data-app-id="web"]').first();
	await expect(webAppCard).toBeVisible({ timeout: SETTINGS_TIMEOUT });
	await webAppCard.click();

	await expect(page).toHaveURL(/#apps\/web(?:&|$)/, { timeout: SETTINGS_TIMEOUT });
	await expect(page.getByTestId('apps-detail-fullscreen')).toContainText(/web/i, {
		timeout: SETTINGS_TIMEOUT
	});
});

// contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
test('combined chat settings deep link hydrates chat context after reload', async ({
	page
}: {
	page: any;
}) => {
	test.setTimeout(120_000);
	await loginToTestAccount(page);
	await page.goto(
		getE2EDebugUrl('/#chat-id=example-gigantic-airplanes&settings=chats/example-gigantic-airplanes/tasks'),
		{ waitUntil: 'domcontentloaded' }
	);

	for (const reload of [false, true]) {
		if (reload) await page.reload({ waitUntil: 'domcontentloaded' });
		const settingsMenu = page.getByTestId('settings-menu');
		await expect(settingsMenu).toBeVisible({ timeout: SETTINGS_TIMEOUT });
		await expect(settingsMenu).toHaveAttribute('data-active-view', 'chats/example-gigantic-airplanes', {
			timeout: SETTINGS_TIMEOUT
		});

		const chatSettingsPage = settingsMenu.getByTestId('chat-settings-page');
		await expect(chatSettingsPage).toBeVisible({ timeout: SETTINGS_TIMEOUT });
		await expect(chatSettingsPage).not.toContainText(/Open a chat before viewing chat settings/i, {
			timeout: SETTINGS_TIMEOUT
		});
		await expect(settingsMenu.getByTestId('chat-settings-tabs')).toBeVisible({ timeout: SETTINGS_TIMEOUT });
		// Curated examples intentionally limit Settings to Share (and available
		// Files/Usage). A Tasks deep link must hydrate context and fall back to Share.
		await expect(settingsMenu.getByTestId('chat-settings-tabpanel-share')).toBeVisible({
			timeout: SETTINGS_TIMEOUT
		});
		await expect(settingsMenu.getByTestId('chat-settings-tabpanel-tasks')).toHaveCount(0);
	}
});
