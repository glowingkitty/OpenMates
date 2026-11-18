// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant: string) =>
	`/dev/preview/settings/connected_accounts/FigmaConnectedAccounts?theme=light&background=%23dbeafe&width=420&chrome=0&variant=${variant}`;

test.describe('Figma connected accounts', () => {
	// contract-test: supporting surface=gui.web assertions=design-figma.connection.minimal-scopes,design-figma.surface.parity
	test('shows connect controls and the variables toggle with no accounts', async ({ page }, testInfo) => {
		await page.goto(preview('noAccounts'));
		await waitForComponentPreview(page);
		const section = page.getByTestId('figma-connected-accounts-section');
		await expect(section).toBeVisible();
		await expect(section.getByText('Figma', { exact: true }).first()).toBeVisible();
		await expect(section).toContainText('read-only');
		await expect(page.getByTestId('figma-connect-button')).toBeVisible();
		await expect(page.getByTestId('figma-connect-button')).toContainText('Connect Figma');
		await expect(page.getByTestId('figma-connect-button')).toBeEnabled();
		await expect(page.getByTestId('figma-account-row')).toHaveCount(0);
		await expect(page.getByTestId('figma-not-configured')).toHaveCount(0);
		const toggle = page.getByTestId('figma-variables-toggle');
		await expect(toggle).toBeVisible();
		await expect(section).toContainText('Variables (Figma Enterprise only)');
		await toggle.click();
		await toggle.click();
		await testInfo.attach('no-accounts-420', { body: await section.screenshot(), contentType: 'image/png' });
	});

	// contract-test: supporting surface=gui.web assertions=design-figma.execution.token-lifecycle,design-figma.surface.parity
	test('lists a connected account with reconnect, disconnect and revoke note', async ({ page }, testInfo) => {
		await page.goto(preview('connected'));
		await waitForComponentPreview(page);
		const row = page.getByTestId('figma-account-row');
		await expect(row).toHaveCount(1);
		await expect(row).toContainText('Dana Designer');
		await expect(row.getByTestId('figma-disconnect-button')).toBeVisible();
		await expect(row.getByRole('button', { name: 'Reconnect' })).toBeVisible();
		await expect(row).toContainText('Figma has no API to revoke access');
		await testInfo.attach('connected-420', {
			body: await page.getByTestId('figma-connected-accounts-section').screenshot(),
			contentType: 'image/png'
		});
	});

	// contract-test: supporting surface=gui.web assertions=design-figma.connection.oauth
	test('shows the not-configured state', async ({ page }, testInfo) => {
		await page.goto(preview('notConfigured'));
		await waitForComponentPreview(page);
		await expect(page.getByTestId('figma-not-configured')).toContainText('not configured');
		await expect(page.getByTestId('figma-connect-button')).toBeDisabled();
		await testInfo.attach('not-configured-420', {
			body: await page.getByTestId('figma-connected-accounts-section').screenshot(),
			contentType: 'image/png'
		});
	});
});
