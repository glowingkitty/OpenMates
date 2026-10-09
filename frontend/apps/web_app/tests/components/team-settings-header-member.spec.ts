// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: supporting surface=gui.web assertions=teams.chat.sender-identity-layout
test('member heading never renders a route translation placeholder while loading identity', async ({ page }) => {
  for (const variant of ['coldMemberLink', 'missingMemberTitle']) {
    await page.goto(`/dev/preview/settings/TeamSettingsHeader?chrome=0&width=323&variant=${variant}`);
    await waitForComponentPreview(page);
    const header = page.getByTestId('team-settings-header');
    await expect(header).not.toContainText('[T:');
    await expect(header.locator('.app-name')).toHaveText('Team member');
    await expect(header).toContainText('Studio team');
  }
});

// contract-test: supporting surface=gui.web assertions=teams.chat.sender-identity-layout
test('member heading shows the resolved identity with the existing settings banner', async ({ page }) => {
  await page.goto('/dev/preview/settings/TeamSettingsHeader?chrome=0&width=323');
  await waitForComponentPreview(page);
  const header = page.getByTestId('team-settings-header');
  await expect(header.locator('.app-name')).toHaveText('Alex');
  await expect(header.locator('.app-details-header')).toHaveCSS('background-image', /linear-gradient/);
  await expect(header).not.toContainText('[T:');
});
