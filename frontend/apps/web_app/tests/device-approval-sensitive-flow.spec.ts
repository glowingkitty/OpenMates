/* eslint-disable @typescript-eslint/no-require-imports */
export {};

const { test, expect } = require('./console-monitor');
const { getIsolatedTestAccount, generateTotp } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipWithoutCredentials } = require('./helpers/env-guard');

const { email, password, otpKey } = getIsolatedTestAccount('device-approval-sensitive-flow.spec.ts');
const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || 'http://localhost:8000';

// contract-test: direct surface=gui.web assertions=auth.sensitive-actions.recent-verification,sdk.auth.approved-api-key-device
test('API-key device approval retries against the server after same-session TOTP proof', async ({ page, request }: { page: any; request: any }) => {
  test.slow();
  test.setTimeout(180000);
  skipWithoutCredentials(test, email, password, otpKey);
  const log = (_message: string) => {};
  const screenshot = async (_page: any, _label: string) => {};
  await loginToTestAccount(page, log, screenshot, { waitForEditor: false });
  const loginTotpStep = generateTotp(otpKey);

  const openSettings = page.getByRole('button', { name: /open settings menu/i }).first();
  if (await openSettings.isVisible({ timeout: 2000 }).catch(() => false)) await openSettings.click();
  const menu = page.getByTestId('settings-menu');
  await expect(menu).toBeVisible();
  await menu.getByRole('menuitem', { name: /developers/i }).first().click();
  await expect(menu).toHaveAttribute('data-active-view', 'developers');
  await menu.getByRole('menuitem', { name: /create and manage api keys/i }).click();
  await expect(page.getByTestId('api-key-create-button')).toBeVisible();

  await page.getByTestId('api-key-create-button').click();
  await page.getByTestId('api-key-name-input').fill(`E2E-Device-Proof-${Date.now()}`);
  const createdResponse = page.waitForResponse((response: any) =>
    response.request().method() === 'POST' && response.url().endsWith('/v1/settings/api-keys') && response.ok());
  await page.getByTestId('api-key-create-confirm').click();
  const createModal = page.getByTestId('auth-modal');
  let createProofCode = '';
  if (await createModal.isVisible({ timeout: 3000 }).catch(() => false)) {
    const useTotp = page.getByTestId('auth-use-2fa');
    if (await useTotp.isVisible({ timeout: 1000 }).catch(() => false)) await useTotp.click();
    createProofCode = generateTotp(otpKey);
    await page.getByTestId('tfa-input').fill(createProofCode);
    await expect(createModal).toHaveCount(0);
  }
  const created = await (await createdResponse).json();
  const keyId = created.id;
  let cleanupError: unknown = null;
  try {
    const credential = (await page.getByTestId('api-key-created-value').textContent())?.trim();
    const rawKey = credential?.split('.')[0];
    expect(rawKey).toMatch(/^sk-api-[A-Za-z0-9]+$/);
    const blocked = await request.get(`${apiUrl}/v1/sdk/chats?limit=1`, { headers: { Authorization: `Bearer ${rawKey}` } });
    expect(blocked.status()).toBe(403);
    await page.getByTestId('api-key-done-button').click();
    await expect(menu).toHaveAttribute('data-active-view', 'developers/api-keys', { timeout: 10000 });
    const confirmDevice = page.getByTestId('api-key-confirm-device-link').first();
    await expect(confirmDevice).toBeVisible({ timeout: 10000 });
    await confirmDevice.click({ timeout: 10000 });
    await expect(menu).toHaveAttribute('data-active-view', 'developers/devices', { timeout: 10000 });

    const deviceResponse = await page.request.get(`${apiUrl}/v1/settings/api-key-devices`);
    expect(deviceResponse.ok()).toBe(true);
    const devices = (await deviceResponse.json()).devices || [];
    const pending = devices.find((device: any) => device.api_key_id === keyId && !device.approved_at);
    expect(pending).toBeTruthy();
    const rows = page.getByTestId('device-row').filter({ hasText: /Pending/i });
    let found = false;
    for (let index = 0; index < await rows.count(); index++) {
      await rows.nth(index).click();
      if (await page.getByText(keyId, { exact: true }).isVisible()) { found = true; break; }
      await page.getByTestId('device-detail-back-button').click();
    }
    expect(found).toBe(true);

    // The one intercepted response represents an expired proof. The proof endpoint and retry stay real.
    let intercepted = false;
    await page.route(`**/v1/settings/api-key-devices/${pending.id}/approve`, async (route: any) => {
      if (route.request().method() === 'OPTIONS') return route.continue();
      if (intercepted) return route.continue();
      intercepted = true;
      const origin = route.request().headers().origin || new URL(page.url()).origin;
      await route.fulfill({ status: 401, contentType: 'application/json', headers: {
        'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true',
        'access-control-allow-methods': 'POST, OPTIONS', 'access-control-allow-headers': 'content-type',
      }, body: JSON.stringify({ detail: 'Recent verification required' }) });
    });
    await page.getByTestId('device-approve-button').click();
    await expect(page.getByTestId('auth-modal')).toBeVisible();
    const useTotp = page.getByTestId('auth-use-2fa');
    if (await useTotp.isVisible({ timeout: 1000 }).catch(() => false)) await useTotp.click();
    const verified = page.waitForResponse((response: any) => response.url().endsWith('/v1/auth/sensitive/totp/verify') && response.ok());
    // TOTP steps are one-use across login and sensitive actions for this account.
    await expect.poll(() => generateTotp(otpKey), { timeout: 35000 }).not.toBe(createProofCode || loginTotpStep);
    await page.getByTestId('tfa-input').fill(generateTotp(otpKey));
    await verified;
    await expect(page.getByTestId('device-approve-button')).toHaveCount(0);
    const after = await page.request.get(`${apiUrl}/v1/settings/api-key-devices`);
    expect((await after.json()).devices.some((device: any) => device.id === pending.id && device.approved_at)).toBe(true);
    expect(intercepted).toBe(true);
  } finally {
    try {
      await page.request.delete(`${apiUrl}/v1/settings/api-keys/${keyId}`, { timeout: 10000 });
    } catch (error) {
      cleanupError = error;
    }
  }
  if (cleanupError) throw cleanupError;
});
