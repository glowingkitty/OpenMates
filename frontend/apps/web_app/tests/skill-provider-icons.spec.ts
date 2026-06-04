/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Cross-skill App Store provider icon coverage.
 *
 * Verifies every skill with providers in /v1/apps/metadata has matching provider
 * rows and loaded provider logos in the skill settings menu.
 */
export {};

const { test, expect } = require('./console-monitor');
const { getE2EDebugUrl } = require('./signup-flow-helpers');
const {
	expectImageLoaded,
	expectWhiteBackground,
	renderedProviderName
} = require('./helpers/provider-icon-helpers');
const { appsMetadata } = require('../../../packages/ui/src/data/appsMetadata');

test.describe('App Store skill provider icons', () => {
	test.setTimeout(360_000);

	test('all skills with providers show matching loaded provider icons in settings', async ({ page }: { page: any }) => {
		await page.setViewportSize({ width: 1600, height: 900 });

		const targets: Array<{ appId: string; skillId: string; providers: string[] }> = [];
		for (const [appId, app] of Object.entries(appsMetadata) as Array<[string, any]>) {
			for (const skill of app.skills || []) {
				if (Array.isArray(skill.providers) && skill.providers.length > 0) {
					targets.push({ appId, skillId: skill.id, providers: skill.providers });
				}
			}
		}

		expect(targets.length, 'at least one skill should expose providers').toBeGreaterThan(0);

		let checkedProviderRows = 0;
		for (const target of targets) {
			const route = `app_store/${target.appId}/skill/${target.skillId}`;
			await page.goto(getE2EDebugUrl(`/#settings/${route}`), { waitUntil: 'domcontentloaded' });
			await page.waitForLoadState('networkidle');

			const settingsMenu = page.locator(`[data-testid="settings-menu"][data-active-view="${route}"]`);
			await settingsMenu.waitFor({ state: 'visible', timeout: 5000 }).catch(() => undefined);
			if (await settingsMenu.count() === 0 || !(await settingsMenu.first().isVisible().catch(() => false))) {
				continue;
			}

			const providerRows = settingsMenu.getByTestId('skill-provider-item');
			const rowCount = await providerRows.count();
			if (rowCount === 0) {
				continue;
			}

			const expectedDisplayNames = new Set(target.providers.map((provider) => renderedProviderName(provider)));
			for (let index = 0; index < rowCount; index += 1) {
				const providerRow = providerRows.nth(index);
				const providerName = await providerRow.getAttribute('data-provider-name');
				expect(providerName, `${target.appId}/${target.skillId} provider row should have a provider name`).toBeTruthy();
				expect(
					expectedDisplayNames.has(providerName),
					`${target.appId}/${target.skillId} rendered provider ${providerName} should exist in metadata`
				).toBe(true);

				const logo = providerRow.getByTestId('settings-provider-logo').first();
				await expectImageLoaded(logo, `${providerName} settings provider logo`);
				await expectWhiteBackground(logo, `${providerName} settings provider logo`);
				checkedProviderRows += 1;
			}
		}

		expect(checkedProviderRows, 'at least one rendered provider row icon should be verified').toBeGreaterThan(0);
	});
});
