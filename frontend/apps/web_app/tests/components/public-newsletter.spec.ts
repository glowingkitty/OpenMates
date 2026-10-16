import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (name: string, width: number, variant?: string) =>
  `/dev/preview/landing/${name}?${new URLSearchParams({ theme: 'dark', background: '#161616', width: String(width), chrome: '0', ...(variant ? { variant } : {}) })}`;

for (const width of [390, 1440]) {
  // contract-test: direct surface=gui.web assertions=newsletter.lifecycle.double-opt-in,newsletter.privacy.identity-and-token-boundary,newsletter.categories.default-and-migration
  test(`newsletter keeps selected categories pending until email confirmation (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    let submitted: { categories: Record<string, boolean>; language: string; darkmode: boolean; email: string } | undefined;
    let release: (() => void) | undefined;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/v1/newsletter/subscribe', async route => {
      submitted = route.request().postDataJSON();
      expect(route.request().headers()['cookie']).toBeUndefined();
      await pending;
      await route.fulfill({ status: 200, json: { success: true, message: 'If confirmation is needed, please check your email.' } });
    });
    await page.goto(preview('NewsletterSignup', width), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    const form = page.getByTestId('landing-newsletter');
    const events = form.getByRole('checkbox', { name: 'OpenMates events', exact: true });
    const software = form.getByRole('checkbox', { name: 'Software updates', exact: true });
    const beta = form.getByRole('checkbox', { name: /Apple app beta updates/ });
    await expect(events).toBeChecked(); await expect(software).toBeChecked(); await expect(beta).not.toBeChecked();
    await software.uncheck(); await beta.check();
    await form.getByLabel('Email address').fill('fictional-reader@example.com');
    await form.getByRole('button', { name: 'Subscribe', exact: true }).click();
    await expect(form.getByRole('button')).toBeDisabled();
    await expect.poll(() => submitted?.categories).toEqual({ openmates_events: true, software_updates: false, apple_beta_updates: true });
    expect(submitted?.language).toBe('en'); expect(submitted?.darkmode).toBe(true);
    release!();
    await expect(form.getByTestId('newsletter-requested')).toContainText(/check your email/i);
    await expect(form.getByRole('link', { name: /Signal/ })).toHaveCount(0);
    expect(await page.evaluate(() => Object.values(localStorage).some(value => String(value).includes('fictional-reader@example.com')))).toBe(false);
    expect(await form.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  });

  for (const success of [true, false]) {
    // contract-test: direct surface=gui.web assertions=newsletter.surface.standalone-confirmation,newsletter.lifecycle.double-opt-in
    test(`newsletter confirmation ${success ? 'success' : 'expired token'} requires acceptance (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      let confirmations = 0;
      await page.route('**/v1/newsletter/confirm/preview-token', async route => {
        confirmations += 1;
        await route.fulfill({ status: success ? 200 : 400, json: { success, message: success ? 'Confirmed' : 'This link is invalid or expired.' } });
      });
      await page.goto(preview('NewsletterConfirmation', width), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page, 30_000);
      const confirmation = page.getByTestId('newsletter-confirmation');
      await expect(confirmation.getByRole('heading')).toBeVisible();
      await expect(page.getByTestId('newsletter-confirm-button')).toBeVisible();
      expect(confirmations).toBe(0);
      await expect(page.getByTestId('newsletter-signal-link')).toHaveCount(0);
      await page.getByTestId('newsletter-confirm-button').click();
      await expect.poll(() => confirmations).toBe(1);
      if (success) {
        await expect(confirmation.getByRole('status')).toContainText(/confirmed/i);
        const signal = page.getByTestId('newsletter-signal-link');
        await expect(signal).toBeVisible();
        await expect(signal).toHaveAttribute('target', '_blank');
        await expect(signal).toHaveAttribute('referrerpolicy', 'no-referrer');
      } else {
        await expect(confirmation.getByRole('alert')).toContainText(/invalid|expired/i);
        await expect(page.getByTestId('newsletter-signal-link')).toHaveCount(0);
      }
    });
  }
}

// contract-test: direct surface=gui.web assertions=newsletter.lifecycle.double-opt-in,newsletter.surface.semantic-parity
test('German newsletter error is readable and retains choices for retry', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/v1/newsletter/subscribe', route => route.fulfill({ status: 429, json: { success: false } }));
  await page.goto(preview('NewsletterSignup', 390, 'German'), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page, 30_000);
  const form = page.getByTestId('landing-newsletter');
  await form.getByLabel('E-Mail-Adresse', { exact: true }).fill('fictional-reader@example.com');
  await form.getByRole('checkbox', { name: /Apple/ }).check();
  await form.getByRole('button').click();
  await expect(form.getByRole('alert')).toBeVisible();
  await expect(form.getByRole('checkbox', { name: /Apple/ })).toBeChecked();
  await expect(form.getByLabel('E-Mail-Adresse', { exact: true })).toHaveValue('fictional-reader@example.com');
  await expect(form.getByRole('button')).toBeEnabled();
});
