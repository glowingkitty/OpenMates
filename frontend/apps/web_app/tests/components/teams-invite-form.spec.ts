import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = (variant = 'default') =>
  `/dev/preview/settings/TeamInviteForm?theme=light&background=%23dbeafe&width=323&chrome=0&variant=${variant}`;

test.describe('Team invite form', () => {
  // contract-test: direct surface=gui.web assertions=teams.invites.fragment-key-web-flow,settings-ui.composition.canonical-and-accessible
  test('requires an email and dispatches accept and decline through keyboard controls', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview());
    await waitForComponentPreview(page);
    await page.evaluate(() => window.addEventListener('team-invite-preview-action', event => {
      document.body.dataset.inviteAction = (event as CustomEvent<string>).detail;
    }));
    const email = page.getByTestId('team-invite-recipient-email');
    const accept = page.getByTestId('team-invite-accept');
    const decline = page.getByTestId('team-invite-decline');
    await expect(email).toHaveValue('mira@example.com');
    await email.fill('');
    await expect(accept).toBeDisabled();
    await expect(decline).toBeDisabled();
    await email.fill('mira@example.com');
    await email.focus();
    await expect(email).toBeFocused();
    await email.press('Tab');
    await expect(decline).toBeFocused();
    await decline.press('Enter');
    await expect(page.locator('body')).toHaveAttribute('data-invite-action', 'decline');
    await accept.focus();
    await accept.press('Enter');
    await expect(page.locator('body')).toHaveAttribute('data-invite-action', 'accept');
    const geometry = await page.locator('.settings-page-container').evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
  });

  // contract-test: direct surface=gui.web assertions=teams.invites.fragment-key-web-flow
  test('shows missing key, pending, joined and error states clearly', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const [variant, resultTestId] of [
      ['missing', 'team-invite-missing-key'],
      ['pending', 'team-invite-result'],
      ['joined', 'team-invite-result'],
      ['error', 'team-invite-error'],
      ['strong-auth', 'team-invite-error'],
    ] as const) {
      await page.goto(preview(variant));
      await waitForComponentPreview(page);
      await expect(page.getByTestId(resultTestId)).toBeVisible();
      if (variant === 'missing' || variant === 'pending' || variant === 'joined') {
        await expect(page.getByTestId('team-invite-accept')).toHaveCount(0);
      }
      if (variant === 'strong-auth') {
        await expect(page.getByTestId('team-invite-error')).toContainText('passkey or a 2FA app');
        await expect(page.getByTestId('team-invite-error')).not.toContainText('TEAM_STRONG_AUTH_REQUIRED');
        await expect(page.getByTestId('team-invite-accept')).toBeEnabled();
        await expect(page.getByTestId('team-invite-decline')).toBeEnabled();
        const geometry = await page.locator('.settings-page-container').evaluate(element => ({ width: element.clientWidth, scrollWidth: element.scrollWidth }));
        expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.width + 1);
      }
      if (variant === 'error') {
        await expect(page.getByTestId('team-invite-accept')).toBeEnabled();
        await expect(page.getByTestId('team-invite-error')).toContainText('verified email address');
      }
    }
  });
});
