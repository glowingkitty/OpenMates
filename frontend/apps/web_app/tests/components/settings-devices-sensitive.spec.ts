import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import type { Route } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview

const preview = '/dev/preview/settings/developers/SettingsDevices?theme=light&background=%23dbeafe&width=390&chrome=0&testApi=1';
const device = {
  id: 'preview-device-1', api_key_id: 'preview-key', anonymized_ip: '192.0.2.0',
  access_type: 'rest_api', city: 'Preview City', first_access_at: '2026-01-01T00:00:00Z',
};
const otherDevice = { ...device, id: 'preview-device-2', api_key_id: 'other-key', city: 'Other City' };

async function json(route: Route, body: unknown, status = 200) {
  const origin = route.request().headers().origin || 'http://localhost:5173';
  await route.fulfill({ status, contentType: 'application/json', headers: {
    'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'content-type',
  }, body: JSON.stringify(body) });
}

async function openDevice(page: import('@playwright/test').Page) {
  await page.goto(preview);
  const canvas = await waitForComponentPreview(page);
  await page.getByTestId('device-row').filter({ hasText: device.city }).click();
  await expect(page.getByTestId('device-approve-button')).toBeVisible();
  const widths = await canvas.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client + 1);
}

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification,sdk.auth.approved-api-key-device
test('device approval verifies the session and retries the captured action once', async ({ page }) => {
  let approved = false;
  let approveRequests = 0;
  let otherApproveRequests = 0;
  let proofs = 0;
  await page.route('**/v1/settings/api-key-devices', (route) => json(route, { devices: [{ ...device, approved_at: approved ? '2026-01-01T00:01:00Z' : null }, otherDevice] }));
  await page.route('**/v1/settings/api-key-devices/preview-device-1/approve', async (route) => {
    if (route.request().method() === 'OPTIONS') return json(route, {});
    approveRequests++;
    await json(route, approveRequests === 1 ? { detail: 'Recent verification required' } : { success: true }, approveRequests === 1 ? 401 : 200);
    if (approveRequests === 2) approved = true;
  });
  await page.route('**/v1/settings/api-key-devices/preview-device-2/approve', async (route) => {
    if (route.request().method() === 'OPTIONS') return json(route, {});
    otherApproveRequests++;
    await json(route, { success: true });
  });
  await page.route('**/v1/auth/methods', (route) => json(route, { has_passkey: false, has_password: false, has_2fa: true }));
  await page.route('**/v1/auth/sensitive/totp/verify', async (route) => {
    if (route.request().method() === 'OPTIONS') return json(route, {});
    expect(route.request().postDataJSON()).toEqual({ purpose: 'api_key_manage', code: '123456' });
    proofs++;
    await json(route, { success: true, expires_in: 300 });
  });
  await openDevice(page);
  await expect(page.getByText('preview-key', { exact: true })).toBeVisible();
  await page.getByTestId('device-approve-button').click();
  await expect(page.getByTestId('auth-modal')).toBeVisible();
  await page.getByTestId('tfa-input').fill('123456');
  await expect(page.getByTestId('auth-modal')).toHaveCount(0);
  await expect(page.getByTestId('device-approve-button')).toHaveCount(0);
  await expect(page.getByText('Approved').first()).toBeVisible();
  expect({ approveRequests, otherApproveRequests, proofs }).toEqual({ approveRequests: 2, otherApproveRequests: 0, proofs: 1 });
});

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification
test('cancelled verification leaves the selected device pending', async ({ page }) => {
  let approveRequests = 0;
  await page.route('**/v1/settings/api-key-devices', (route) => json(route, { devices: [device] }));
  await page.route('**/v1/settings/api-key-devices/preview-device-1/approve', async (route) => {
    if (route.request().method() === 'OPTIONS') return json(route, {});
    approveRequests++;
    await json(route, { detail: 'Recent verification required' }, 401);
  });
  await page.route('**/v1/auth/methods', (route) => json(route, { has_passkey: false, has_password: false, has_2fa: true }));
  await openDevice(page);
  await page.getByTestId('device-approve-button').click();
  await expect(page.getByTestId('auth-modal')).toBeVisible();
  await page.getByTestId('auth-modal').getByRole('button', { name: 'Close' }).click();
  await expect(page.getByTestId('auth-modal')).toHaveCount(0);
  await expect(page.getByTestId('device-approve-button')).toBeVisible();
  expect(approveRequests).toBe(1);
});

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification
test('ordinary errors are shown without opening verification', async ({ page }) => {
  await page.route('**/v1/settings/api-key-devices', (route) => json(route, { devices: [device] }));
  await page.route('**/v1/settings/api-key-devices/preview-device-1/approve', (route) => json(route, { detail: 'Device unavailable' }, 409));
  await openDevice(page);
  await page.getByTestId('device-approve-button').click();
  await expect(page.getByText('Device unavailable')).toBeVisible();
  await expect(page.getByTestId('auth-modal')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification
test('unrelated session 401 stays an error and does not request proof', async ({ page }) => {
  let methodRequests = 0;
  let approveRequests = 0;
  await page.route('**/v1/settings/api-key-devices', (route) => json(route, { devices: [device] }));
  await page.route('**/v1/settings/api-key-devices/preview-device-1/approve', async (route) => {
    if (route.request().method() === 'OPTIONS') return json(route, {});
    approveRequests++;
    await json(route, { detail: 'Current session required' }, 401);
  });
  await page.route('**/v1/auth/methods', async (route) => {
    methodRequests++;
    await json(route, { has_2fa: true });
  });
  await openDevice(page);
  await page.getByTestId('device-approve-button').click();
  await expect(page.getByText('Current session required')).toBeVisible();
  await expect(page.getByTestId('auth-modal')).toHaveCount(0);
  expect({ approveRequests, methodRequests }).toEqual({ approveRequests: 1, methodRequests: 0 });
});

// contract-test: supporting surface=gui.web assertions=auth.sensitive-actions.recent-verification,sdk.auth.approved-api-key-device
test('revoke confirmation is not repeated after proof, and denied retries stop', async ({ page }) => {
  let revokeRequests = 0;
  let confirmations = 0;
  await page.route('**/v1/settings/api-key-devices', (route) => json(route, { devices: [{ ...device, approved_at: '2026-01-01T00:01:00Z' }] }));
  await page.route('**/v1/settings/api-key-devices/preview-device-1/revoke', async (route) => {
    if (route.request().method() === 'OPTIONS') return json(route, {});
    revokeRequests++;
    await json(route, { detail: 'Recent verification required' }, 401);
  });
  await page.route('**/v1/auth/methods', (route) => json(route, { has_passkey: false, has_password: false, has_2fa: true }));
  await page.route('**/v1/auth/sensitive/totp/verify', (route) => json(route, { success: true, expires_in: 300 }));
  page.on('dialog', async (dialog) => { confirmations++; await dialog.accept(); });
  await page.goto(preview);
  await waitForComponentPreview(page);
  await page.getByTestId('device-row').click();
  await page.getByTestId('device-revoke-button').click();
  await expect(page.getByTestId('auth-modal')).toBeVisible();
  await page.getByTestId('tfa-input').fill('123456');
  await expect(page.getByText('Recent verification required')).toBeVisible();
  await expect(page.getByTestId('auth-modal')).toHaveCount(0);
  expect({ revokeRequests, confirmations }).toEqual({ revokeRequests: 2, confirmations: 1 });
});
