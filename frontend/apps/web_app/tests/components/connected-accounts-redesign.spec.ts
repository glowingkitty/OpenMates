// playwright-account: not_required reason=isolated_component_preview
import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.setTimeout(120_000);

const widths = { desktop: { width: 1100, height: 900 }, mobile: { width: 390, height: 844 } };
const preview = (variant: string, width: number) =>
	`/dev/preview/settings/AppDetails?theme=light&width=${Math.min(width, 520)}&chrome=0&variant=${variant}`;

const variants = [
	{ name: 'calendarNotConnected', section: 'calendar-connected-accounts-section', items: 0 },
	{ name: 'calendarConnectedGenericLabel', section: 'calendar-connected-accounts-section', items: 1 },
	{ name: 'calendarConnectedEmailLabel', section: 'calendar-connected-accounts-section', items: 1 },
	{ name: 'calendarNeedsReconnect', section: 'calendar-connected-accounts-section', items: 1 },
	{ name: 'mailNotConnected', section: 'mail-connected-accounts-section', items: 0 },
	{ name: 'mailConnectedEmailLabel', section: 'mail-connected-accounts-section', items: 1 }
];

async function open(page: Page, variant: string, size: keyof typeof widths) {
	await page.setViewportSize(widths[size]);
	await page.goto(preview(variant, widths[size].width));
	return waitForComponentPreview(page);
}

test.describe('App page connected accounts', () => {
	for (const size of Object.keys(widths) as Array<keyof typeof widths>) {
		for (const variant of variants) {
			// contract-test: direct surface=gui.web assertions=connected-accounts.settings.app-page-summary
			test(`${variant.name} at ${size} width`, async ({ page }, testInfo) => {
				await open(page, variant.name, size);
				const section = page.getByTestId(variant.section);
				await expect(section).toBeVisible();
				await expect(section.getByTestId('app-connected-account-item')).toHaveCount(variant.items);
				const link = section.getByTestId('app-connected-accounts-manage-link');
				if (variant.items === 0) {
					await expect(section.getByTestId('app-connected-accounts-empty')).toContainText('No account connected');
					await expect(link).toContainText('Add account in Connected accounts');
				} else {
					await expect(link).toContainText('Manage connected accounts');
				}
				if (variant.name.endsWith('EmailLabel')) await expect(section).toContainText('test.user@example.org');
				if (variant.name.endsWith('GenericLabel')) await expect(section).toContainText('Email not saved');
				if (variant.name === 'calendarNeedsReconnect') await expect(section).toContainText('Needs reconnect');
				for (const gone of ['connect-google-calendar-button', 'connect-gmail-button', 'connected-account-manage', 'connected-account-reconnect', 'connected-account-disconnect', 'calendar-capability-toggles']) {
					await expect(page.getByTestId(gone)).toHaveCount(0);
				}
				// The only action left on an app page is the link to the central page.
				await expect(section.getByRole('button', { name: /^(Connect|Reconnect|Disconnect)/ })).toHaveCount(0);
				await expect(
					section
						.locator(':is(button, [role=button], a):not([data-testid="app-connected-accounts-manage-link"])')
						.filter({ hasText: /Manage/ })
				).toHaveCount(0);
				await section.scrollIntoViewIfNeeded();
				await testInfo.attach(`after-${variant.name}-${size}`, { body: await section.screenshot(), contentType: 'image/png' });
			});
		}
	}

	// contract-test: direct surface=gui.web assertions=connected-accounts.settings.app-page-summary
	test('privacy page lists the connected accounts', async ({ page }, testInfo) => {
		await page.goto('/dev/preview/settings/account/SettingsConnectedAccounts?theme=light&width=520&chrome=0&variant=googleCalendarAndFigma');
		const canvas = await waitForComponentPreview(page);
		await expect(page.getByTestId('connected-account-entry').first()).toBeVisible();
		await testInfo.attach('after-privacy-connected-accounts-desktop', { body: await canvas.screenshot(), contentType: 'image/png' });
	});
});
