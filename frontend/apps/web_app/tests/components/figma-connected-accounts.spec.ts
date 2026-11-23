// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// The Design (Figma) app page only lists accounts and links to Connected accounts.
const preview = (variant: string) =>
	`/dev/preview/settings/AppDetails?theme=light&width=420&chrome=0&variant=${variant}`;

test.describe('Figma connected accounts on the Design app page', () => {
	// contract-test: direct surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke
	test('shows one line and the add link with no account', async ({ page }, testInfo) => {
		await page.goto(preview('designNotConnected'));
		await waitForComponentPreview(page);
		const section = page.getByTestId('figma-connected-accounts-section');
		await expect(section).toBeVisible();
		await expect(section.getByTestId('app-connected-accounts-empty')).toContainText('No account connected');
		await expect(section.getByTestId('app-connected-accounts-manage-link')).toContainText('Add account in Connected accounts');
		await expect(page.getByTestId('figma-connect-button')).toHaveCount(0);
		await testInfo.attach('design-no-account-420', { body: await section.screenshot(), contentType: 'image/png' });
	});

	// contract-test: direct surface=gui.web assertions=connected-accounts.lifecycle.reconnect-revoke
	test('lists a connected Figma account and a manage link without account buttons', async ({ page }, testInfo) => {
		await page.goto(preview('designConnected'));
		await waitForComponentPreview(page);
		const section = page.getByTestId('figma-connected-accounts-section');
		await expect(section.getByTestId('app-connected-account-item')).toHaveCount(1);
		await expect(section.getByTestId('app-connected-account-item')).toContainText('dana@example.org');
		await expect(section.getByTestId('app-connected-accounts-manage-link')).toContainText('Manage connected accounts');
		await expect(page.getByTestId('figma-disconnect-button')).toHaveCount(0);
		await expect(section.getByRole('button', { name: 'Reconnect' })).toHaveCount(0);
		await testInfo.attach('design-connected-420', { body: await section.screenshot(), contentType: 'image/png' });
	});
});
