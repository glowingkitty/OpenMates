// playwright-account: not_required reason=isolated_component_preview
import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.setTimeout(120_000);

const sizes = { desktop: { width: 1100, height: 900 }, phone: { width: 390, height: 844 } };
const previewUrl = (variant: string, width: number) =>
	`/dev/preview/settings/account/SettingsConnectedAccounts?theme=light&width=${Math.min(width, 520)}&chrome=0&variant=${variant}`;

async function open(page: Page, variant: string, size: keyof typeof sizes) {
	await page.setViewportSize(sizes[size]);
	await page.goto(previewUrl(variant, sizes[size].width));
	return waitForComponentPreview(page);
}

async function attach(testInfo: import('@playwright/test').TestInfo, name: string, page: Page) {
	await testInfo.attach(name, {
		body: await page.getByTestId('component-preview-canvas').screenshot(),
		contentType: 'image/png'
	});
}

test.describe('Central connected accounts page', () => {
	for (const size of Object.keys(sizes) as Array<keyof typeof sizes>) {
		// contract-test: direct surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke,connected-accounts.settings.central-page
		test(`lists every account with email and last used at ${size} width`, async ({ page }, testInfo) => {
			await open(page, 'twoGoogleOneFigma', size);
			await expect(page.getByTestId('connected-accounts-add-button')).toBeVisible();
			await expect(page.getByTestId('connected-account-entry')).toHaveCount(3);
			const google = page.getByTestId('connected-account-entry-preview-google-account');
			await expect(google).toContainText('test.user@example.org');
			await expect(google).toContainText('Last used');
			// Each entry shows its provider's logo, never an empty icon box.
			await expect(google.locator('.item-image img')).toBeVisible();
			await expect(page.getByTestId('connected-account-entry-preview-figma-account').locator('.icon.app, .icon.account')).toBeVisible();
			const legacy = page.getByTestId('connected-account-entry-preview-google-legacy-account');
			await expect(legacy).toContainText('Email not saved');
			await expect(legacy).toContainText('Needs reconnect');
			await expect(page.getByTestId('connected-account-entry-preview-figma-account')).toContainText('Never used');
			await attach(testInfo, `list-${size}`, page);
		});
	}

	// contract-test: direct surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke,connected-accounts.settings.central-page
	test('empty state at phone width', async ({ page }, testInfo) => {
		await open(page, 'empty', 'phone');
		await expect(page.getByTestId('connected-accounts-empty')).toBeVisible();
		await expect(page.getByTestId('connected-accounts-add-button')).toBeVisible();
		await attach(testInfo, 'empty-phone', page);
	});

	// contract-test: direct surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke,connected-accounts.settings.central-page
	test('add account offers Google access choices and Figma', async ({ page }) => {
		await open(page, 'empty', 'phone');
		await page.getByTestId('connected-accounts-add-button').click();
		await page.getByTestId('connected-accounts-add-google').click();
		await expect(page.getByTestId('connected-accounts-add-toggle-calendar')).toBeVisible();
		await expect(page.getByTestId('connected-accounts-add-toggle-gmail')).toBeVisible();
		await expect(page.getByTestId('connected-accounts-add-figma')).toBeVisible();
	});

	// contract-test: direct surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke,connected-accounts.settings.central-page
	test('opens detail, toggles a permission and confirms disconnect', async ({ page }, testInfo) => {
		await open(page, 'twoGoogleOneFigma', 'phone');
		await page.getByTestId('connected-account-entry-preview-google-account').click();
		const detail = page.getByTestId('connected-account-detail');
		await expect(detail).toBeVisible();
		await expect(detail).toContainText('test.user@example.org');
		// The page is headed by the provider's logo (Google), not the calendar app icon.
		// Header shows the provider's logo image (Vite may inline it as a data URI), not the calendar icon mask.
		const headerLogo = detail.getByTestId('settings-section-heading-image').locator('img');
		await expect(headerLogo).toBeVisible();
		await expect(headerLogo).toHaveAttribute('alt', 'Google account');
		expect(await headerLogo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
		await expect(page.getByTestId('connected-account-app-permissions-calendar')).toBeVisible();
		await expect(page.getByTestId('connected-account-app-permissions-mail')).toBeVisible();
		await expect(page.getByTestId('connected-account-app-permissions-mail')).toContainText('Read emails');
		await expect(page.getByTestId('connected-account-app-permissions-calendar')).toContainText('Read events');
		await expect(page.getByTestId('connected-account-detail-last-used')).toContainText('ago');
		await attach(testInfo, 'detail-phone', page);

		await page.getByTestId('connected-account-permission-mail-draft').click();
		await page.getByTestId('connected-account-detail-back').click();
		await page.getByTestId('connected-account-entry-preview-google-account').click();
		await expect(page.getByTestId('connected-account-app-permissions-mail')).toBeVisible();

		await page.getByTestId('connected-account-disconnect').click();
		await expect(page.getByTestId('connected-account-disconnect-confirm')).toBeVisible();
		await page.getByTestId('connected-account-disconnect-cancel').click();
		await expect(page.getByTestId('connected-account-disconnect')).toBeVisible();
		await page.getByTestId('connected-account-disconnect').click();
		await page.getByTestId('connected-account-disconnect-confirm-button').click();
		await expect(page.getByTestId('connected-account-entry-preview-google-account')).toHaveCount(0);
		await expect(page.getByTestId('connected-account-entry')).toHaveCount(2);
		await expect(page.getByTestId('connected-accounts-add-button')).toBeEnabled();
		await attach(testInfo, 'after-disconnect-phone', page);
	});
});
