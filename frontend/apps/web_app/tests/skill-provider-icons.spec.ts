/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Cross-skill App Store provider icon coverage.
 *
 * Verifies every skill with providers in /v1/apps/metadata has matching provider
 * rows and loaded provider logos in the skill settings menu.
 */
export {};

const { test, expect } = require('./console-monitor');
const { deriveApiUrl } = require('./helpers/cli-test-helpers');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const { expectSettingsProviderIcons } = require('./helpers/provider-icon-helpers');

test.describe('App Store skill provider icons', () => {
	test.setTimeout(360_000);

	let apiUrl: string;

	test.beforeAll(() => {
		apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
	});

	test('all skills with providers show matching loaded provider icons in settings', async ({ page, request }: { page: any; request: any }) => {
		await page.setViewportSize({ width: 1600, height: 900 });

		const response = await request.get(`${apiUrl}/v1/apps/metadata`);
		expect(response.ok()).toBeTruthy();
		const data = await response.json();

		const targets: Array<{ appId: string; skillId: string; providers: string[] }> = [];
		for (const [appId, app] of Object.entries(data.apps || {}) as Array<[string, any]>) {
			for (const skill of app.skills || []) {
				if (Array.isArray(skill.providers) && skill.providers.length > 0) {
					targets.push({ appId, skillId: skill.id, providers: skill.providers });
				}
			}
		}

		expect(targets.length, 'at least one skill should expose providers').toBeGreaterThan(0);

		for (const target of targets) {
			const route = `app_store/${target.appId}/skill/${target.skillId}`;
			await page.goto(getE2EDebugUrl(`/#settings/${route}`), { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');

			const settingsMenu = page.locator(`[data-testid="settings-menu"][data-active-view="${route}"]`);
			await expect(settingsMenu, `${target.appId}/${target.skillId} settings should be visible`).toBeVisible({ timeout: 15_000 });
			await expectSettingsProviderIcons(settingsMenu, target.providers);
		}
	});
});
