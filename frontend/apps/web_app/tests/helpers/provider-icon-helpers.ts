/* eslint-disable @typescript-eslint/no-require-imports */
/* eslint-disable @typescript-eslint/no-explicit-any */

const { expect } = require('../console-monitor');

function renderedProviderName(providerName: string): string {
	const aliases: Record<string, string> = {
		BFL: 'Black Forest Labs',
		Brave: 'Brave Search',
		'FlixBus / FlixTrain': 'Flix',
		Mistral: 'Mistral AI',
		ProtonMail: 'Proton Mail'
	};
	return aliases[providerName] || providerName;
}

async function expectImageLoaded(locator: any, label = 'image'): Promise<void> {
	await expect(locator).toBeVisible({ timeout: 15_000 });
	await expect(async () => {
		const loaded = await locator.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0);
		expect(loaded, `${label} should finish loading`).toBe(true);
	}).toPass({ timeout: 15_000 });
}

async function expectWhiteBackground(locator: any, label = 'logo tile'): Promise<void> {
	await expect(locator).toBeVisible({ timeout: 15_000 });
	const background = await locator.evaluate((element: HTMLElement) => getComputedStyle(element).backgroundColor);
	expect(background, `${label} should use a white background`).toBe('rgb(255, 255, 255)');
}

async function expectSettingsProviderIcons(settingsMenu: any, providerNames: string[]): Promise<void> {
	for (const providerName of providerNames) {
		const displayName = renderedProviderName(providerName);
		const item = settingsMenu.locator(`[data-testid="skill-provider-item"][data-provider-name="${displayName}"]`).first();
		await expect(item, `${displayName} provider row should be visible`).toBeVisible({ timeout: 15_000 });

		const logo = settingsMenu.locator(`[data-testid="settings-provider-logo"][data-provider-name="${displayName}"]`).first();
		await expectImageLoaded(logo, `${displayName} settings provider logo`);
		await expectWhiteBackground(logo, `${displayName} settings provider logo`);
	}
}

async function expectSkillCardProviderIcons(skillCard: any, providerNames: string[]): Promise<void> {
	await expect(skillCard).toBeVisible({ timeout: 15_000 });
	const iconImages = skillCard.locator('[data-testid="provider-icon-image"]');
	const expectedVisibleCount = Math.min(providerNames.length, 4);
	await expect(iconImages, 'skill card provider icon images').toHaveCount(expectedVisibleCount, { timeout: 15_000 });

	for (let index = 0; index < expectedVisibleCount; index += 1) {
		const providerName = providerNames[index];
		const displayName = renderedProviderName(providerName);
		const wrapper = skillCard.locator(`[data-testid="provider-icon"][data-provider-name="${displayName}"]`).first();
		const image = skillCard.locator(`[data-testid="provider-icon-image"][data-provider-name="${displayName}"]`).first();
		await expectImageLoaded(image, `${displayName} skill card provider logo`);
		await expectWhiteBackground(wrapper, `${displayName} skill card provider logo tile`);
	}

	if (providerNames.length > expectedVisibleCount) {
		await expect(skillCard.getByTestId('skill-providers-remaining')).toContainText(`+${providerNames.length - expectedVisibleCount}`);
	}
}

module.exports = {
	expectImageLoaded,
	expectSettingsProviderIcons,
	expectSkillCardProviderIcons,
	expectWhiteBackground,
	renderedProviderName
};
