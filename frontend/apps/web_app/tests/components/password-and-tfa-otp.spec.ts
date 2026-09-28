import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=auth.login.method-convergence
test('accepts a formatted OTP paste and reconciles browser autofill', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto('/dev/preview/PasswordAndTfaOtp?variant=otp&theme=light&background=%23dbeafe&width=420&chrome=0');
    await waitForComponentPreview(page);

    const password = page.locator('#login-password-input');
    const otp = page.getByTestId('login-otp-input');
    const submit = page.getByTestId('login-submit-button');
    await expect(password).toBeVisible();
    await expect(otp).toBeVisible();
    await expect(submit).toBeDisabled();
    await password.fill('preview-password');

    await page.evaluate(() => navigator.clipboard.writeText('123 456'));
    await otp.focus();
    await otp.press('ControlOrMeta+V');
    await expect(otp).toHaveValue('123456');
    await expect(submit).toBeEnabled();

    await otp.fill('');
    await expect(submit).toBeDisabled();
    // Model a password manager setting the DOM value without an input event.
    await otp.evaluate((element: HTMLInputElement) => { element.value = '12 34 56'; });
    await password.focus();
    await expect(otp).toHaveValue('123456');
    await expect(submit).toBeEnabled();
});
