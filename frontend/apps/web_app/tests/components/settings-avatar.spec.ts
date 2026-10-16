import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { expectCanonicalMask } from '../helpers/canonical-icon';

// playwright-account: not_required reason=isolated_component_preview

const preview = (variant: string) =>
	`/dev/preview/settings/elements/SettingsAvatar?theme=light&background=%23dbeafe&width=323&chrome=0&variant=${variant}`;

test.describe('Settings avatar', () => {
	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,teams.membership.role-gated
	test('renders team-key-decrypted generated metadata with canonical settings avatar', async ({
		page
	}) => {
		await page.goto(preview('generated'));
		await waitForComponentPreview(page);
		const avatar = page.getByLabel('Alex team avatar');
		await expect(avatar).toBeVisible();
		await expect(avatar).toHaveCSS('background-color', 'rgb(139, 98, 201)');
		const icon = avatar.locator('.generated-avatar-icon');
		await expect(icon).toBeVisible();
		await expectCanonicalMask(icon, 'mate');
		await page.goto(preview('default'));
		await waitForComponentPreview(page);
		await expect(page.getByLabel('Account avatar').locator('.avatar-placeholder')).toBeVisible();
	});

	// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
	test('falls back to a bundled icon and token color for malformed metadata', async ({ page }) => {
		await page.goto(preview('unsafe'));
		await waitForComponentPreview(page);
		const avatar = page.getByLabel('Fallback team avatar');
		await expectCanonicalMask(avatar.locator('.generated-avatar-icon'), 'mate');
		await expect(avatar).toHaveCSS('background-color', 'rgb(72, 103, 205)');
	});
});
