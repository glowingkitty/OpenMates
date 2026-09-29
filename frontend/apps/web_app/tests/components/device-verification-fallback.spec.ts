import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = '/dev/preview/VerifyDevicePasskey?theme=light&width=390&chrome=0';

// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
test('passkey risk challenge offers password and one-use email code on this device', async ({ page }) => {
  let requestCount = 0;
  let verifyCount = 0;
  await page.route('**/v1/auth/sensitive/email/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = route.request().postDataJSON();
    expect(payload.purpose).toBe('device_approval');
    if (path.endsWith('/request')) {
      requestCount++;
      expect(payload.email).toBe('device-preview@example.test');
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, challenge_id: 'x'.repeat(32), expires_in: 600, password_challenge_id: 'device-password-challenge', password_nonce: 'ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8' }) });
    } else {
      verifyCount++;
      expect(payload.challenge_id).toBe('x'.repeat(32));
      expect(payload.code).toBe('123456');
      expect(payload.lookup_hash).toBeUndefined();
      expect(payload.password_challenge_id).toBe('device-password-challenge');
      expect(payload.password_proof).toMatch(/^[A-Za-z0-9_-]{43}$/);
      expect(payload.hashed_email).toMatch(/^[A-Za-z0-9+/]+=*$/);
      expect(payload.session_id).toBeTruthy();
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, expires_in: 300 }) });
    }
  });

  await page.goto(preview);
  const canvas = await waitForComponentPreview(page);
  await expect(page.getByTestId('location-change-notice')).toBeVisible();
  await expect(page.getByTestId('verify-device-passkey-button')).toBeVisible();
  await page.getByTestId('device-password-fallback').click();
  await page.getByTestId('device-password-input').fill('correct horse battery staple');
  await page.getByTestId('device-request-email-code').click();
  await expect(page.getByTestId('device-email-code-input')).toBeVisible();
  await page.getByTestId('device-email-code-input').fill('123456');
  await page.getByTestId('device-verify-email-code').click();
  expect(requestCount).toBe(1);
  expect(verifyCount).toBe(1);
  const geometry = await canvas.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
});

// contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
test('passkey-only device challenge does not offer a password fallback', async ({ page }) => {
  await page.goto(`${preview}&variant=passkey_only`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('verify-device-passkey-button')).toBeVisible();
  await expect(page.getByTestId('device-password-fallback')).toHaveCount(0);
});
