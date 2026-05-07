/*
Purpose: Regression coverage for reconnecting a 2FA app from the signup one-time-codes step.
Scenario: The profile still has tfa_enabled=true while a new reconnect setup is active.
Bug covered: OPE-492 / issue 7fb8eca4-9a43-4686-a4fd-be4ca8381c1a hid setup actions and OTP input.
Architecture: Uses the dev component preview to render the real signup one-time-code components with deterministic stores.
Tests: Run with scripts/run_tests.py --spec signup-2fa-reconnect-preview.spec.ts.
*/
import { expect, test } from './helpers/cookie-audit';

test('2FA reconnect preview shows setup actions and OTP input while profile 2FA is enabled', async ({
    page,
    context
}) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);

    const response = await page.goto(
        '/dev/preview/signup/steps/onetimecodes/OneTimeCodesReconnectPreview',
        { waitUntil: 'networkidle' }
    );
    expect(response?.status()).toBe(200);

    await expect(page.getByTestId('preview-toolbar')).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('one-time-codes-reconnect-preview')).toBeVisible({ timeout: 10000 });

    await expect(page.getByTestId('signup-2fa-reconnect')).toBeHidden();
    await expect(page.getByTestId('signup-2fa-scan-qr')).toBeVisible();
    await expect(page.getByTestId('signup-2fa-copy-secret')).toBeVisible();
    await expect(page.getByTestId('signup-2fa-otp-input')).toBeVisible();

    await page.getByTestId('signup-2fa-copy-secret').click();
    await expect(page.getByTestId('signup-2fa-secret-input')).toHaveValue('JBSWY3DPEHPK3PXP');
});
