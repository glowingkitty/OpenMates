// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// Baseline ("before") captures of the connected-account surfaces; assertions stay minimal.
test.setTimeout(120_000);

const widths = { desktop: { width: 1100, height: 900 }, mobile: { width: 390, height: 844 } };
const base = (path: string, variant: string, width: number) =>
	`/dev/preview/${path}?theme=light&width=${Math.min(width, 520)}&chrome=0&variant=${variant}`;

const surfaces = [
	{ name: 'calendar-not-connected', path: 'settings/AppDetails', variant: 'calendarNotConnected', testid: 'calendar-connected-accounts-section' },
	{ name: 'calendar-connected', path: 'settings/AppDetails', variant: 'calendarConnectedGenericLabel', testid: 'calendar-connected-accounts-section' },
	{ name: 'calendar-connected-email-label', path: 'settings/AppDetails', variant: 'calendarConnectedEmailLabel', testid: 'calendar-connected-accounts-section' },
	{ name: 'privacy-connected-accounts', path: 'settings/account/SettingsConnectedAccounts', variant: 'googleCalendarAndFigma', testid: null }
];

test.describe('Connected accounts baseline', () => {
	for (const surface of surfaces) {
		for (const [size, viewport] of Object.entries(widths)) {
			// contract-test: supporting surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke
			test(`${surface.name} at ${size} width`, async ({ page }, testInfo) => {
				await page.setViewportSize(viewport);
				await page.goto(base(surface.path, surface.variant, viewport.width));
				const canvas = await waitForComponentPreview(page);
				if (surface.testid) await expect(page.getByTestId(surface.testid)).toBeVisible();
				await page.waitForTimeout(1000);
				await testInfo.attach(`before-${surface.name}-${size}`, { body: await canvas.screenshot(), contentType: 'image/png' });
			});
		}
	}
});
