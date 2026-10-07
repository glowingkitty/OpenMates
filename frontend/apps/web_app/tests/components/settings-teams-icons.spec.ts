import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { expectCanonicalMask } from '../helpers/canonical-icon';

// playwright-account: not_required reason=isolated_component_preview

test.describe('Teams settings canonical icons', () => {
	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
	test('empty Teams overview has masked information icons and usable create controls', async ({
		page
	}) => {
		await page.route('**/v1/teams', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ teams: [] })
			})
		);
		await page.setViewportSize({ width: 402, height: 874 });
		await page.goto(
			'/dev/preview/settings/SettingsTeams?theme=light&background=%23dbeafe&width=323&chrome=0'
		);
		await waitForComponentPreview(page);
		const teams = page.getByTestId('teams-settings-page');
		await expect(
			teams.getByText('No teams yet. Create one to collaborate securely.', { exact: true })
		).toBeVisible();
		const icons = teams.locator('.settings-info-box.info .info-box-icon');
		await expect(icons).toHaveCount(1);
		for (const icon of await icons.all()) {
			await icon.scrollIntoViewIfNeeded();
			await expect(icon).toBeVisible();
			await expectCanonicalMask(icon, 'question');
			const bounds = await icon.boundingBox();
			expect(bounds?.width).toBe(20);
			expect(bounds?.height).toBe(20);
		}
		await expect(page.getByTestId('team-create-open')).toBeVisible();
		const geometry = await teams.evaluate((element) => ({
			width: element.clientWidth,
			scrollWidth: element.scrollWidth
		}));
		expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
	test('pending email and link invites show plain text rows with revoke controls', async ({ page }) => {
		await page.goto(
			'/dev/preview/settings/SettingsTeams?variant=members&theme=light&background=%23dbeafe&width=323&chrome=0'
		);
		await waitForComponentPreview(page);
		const rows = page.getByTestId('team-pending-invite-row');
		await expect(rows).toHaveCount(2);
		await expect(rows.nth(0)).toContainText('alex@example.org');
		await expect(rows.nth(1)).toContainText('Invite link');
		await expect(rows.locator('.settings-icon')).toHaveCount(0);
		await expect(rows.nth(0).getByTestId('team-invite-revoke-preview-invite')).toBeVisible();
		await expect(rows.nth(1).getByTestId('team-invite-revoke-preview-link-invite')).toBeVisible();
		const copyLinkIcon = page.getByTestId('team-copy-invite-link').locator('.settings-icon');
		await expect(copyLinkIcon).toBeVisible();
		await expectCanonicalMask(copyLinkIcon, 'copy', '::after');
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,settings-ui.parity.web-apple-shell
	test('allowed email domain row stays plain text beside the canonical domain control', async ({ page }) => {
		await page.goto(
			'/dev/preview/settings/SettingsTeams?variant=restrictedSecurity&theme=light&background=%23dbeafe&width=323&chrome=0'
		);
		await waitForComponentPreview(page);
		const row = page.getByTestId('team-security-domain-row');
		await expect(row).toHaveCount(1);
		await expect(row).toContainText('example.org');
		await expect(row.locator('.settings-icon')).toHaveCount(0);
		await expect(row.getByTestId('team-security-domain-remove-example.org')).toBeVisible();
		const toggleIcon = page.getByTestId('team-security-domain-toggle').locator('.settings-icon');
		await expect(toggleIcon).toBeVisible();
		await expectCanonicalMask(toggleIcon, 'mail', '::after');
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.parity.web-apple-shell
	test('Teams banner resolves the route alias to its canonical mask in both header states', async ({
		page
	}) => {
		await page.setViewportSize({ width: 402, height: 874 });
		for (const variant of ['', '&variant=collapsed']) {
			await page.goto(
				`/dev/preview/settings/AppDetailsHeader?theme=light&background=%23dbeafe&width=323&chrome=0${variant}`
			);
			await waitForComponentPreview(page);
			await expect(page.locator('.app-details-header')).toHaveCSS('opacity', '1');
			await expect(page.locator('.app-details-header')).toHaveCSS(
				'background-image',
				/linear-gradient.*rgb\(72, 103, 205\)/
			);
			await expect(page.getByText('Teams', { exact: true })).toBeVisible();
			const icon = page.locator('.banner-mask-icon');
			await expect(icon).toBeVisible();
			await expectCanonicalMask(icon, 'team');
			const bounds = await icon.boundingBox();
			expect(bounds?.width).toBe(variant ? 36 : 40);
			expect(bounds?.height).toBe(variant ? 36 : 40);
			const back = page.getByTestId('banner-back-button');
			await expect(back).toBeVisible();
			await expect(back).toBeEnabled();
			await back.click();
		}
	});
});
