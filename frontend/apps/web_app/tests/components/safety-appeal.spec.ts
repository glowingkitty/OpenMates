import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const SUSPENDED = '/dev/preview/safety/AccountSuspended?chrome=0&theme=light&background=%23dbeafe';
const FORM = '/dev/preview/safety/SafetyAppealForm?chrome=0&theme=light&background=%23dbeafe';
test.use({ trace: 'retain-on-failure' });

// contract-test: supporting surface=gui.web assertions=safety-strikes.appeal-consented-review
test('suspended screen shows the reason with Appeal and Download my data, then the form', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${SUSPENDED}&width=360`);
  await waitForComponentPreview(page);
  const screen = page.getByTestId('account-suspended');
  await expect(page.getByTestId('account-suspended-reason')).toContainText('suspended');
  await expect(page.getByTestId('account-suspended-download')).toBeVisible();
  expect(await screen.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await testInfo.attach('suspended-mobile', { body: await screen.screenshot(), contentType: 'image/png' });
  await page.getByTestId('account-suspended-appeal').click();
  await expect(page.getByTestId('safety-appeal-form')).toBeVisible();
  await testInfo.attach('suspended-appeal-open', { body: await screen.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=safety-strikes.appeal-consented-review
test('appeal form limits the explanation to 1,000 characters and shares requests only with consent', async ({ page }, testInfo) => {
  await page.goto(`${FORM}&width=420`);
  await waitForComponentPreview(page);
  const submit = page.getByTestId('safety-appeal-submit');
  await expect(submit).toBeDisabled();
  await page.getByTestId('safety-appeal-explanation').fill('x'.repeat(1200));
  await expect(page.getByTestId('safety-appeal-counter')).toHaveText('1000/1000');
  await expect(page.getByTestId('safety-appeal-flagged')).toBeHidden();
  await page.getByTestId('safety-appeal-consent').check();
  await expect(page.getByTestId('safety-appeal-flagged')).toContainText('Example flagged request text');
  await expect(page.getByTestId('safety-appeal-photo-button')).toBeVisible();
  await expect(page.getByTestId('safety-appeal-photo-button')).toHaveText(/Add a photo/);
  await expect(page.getByTestId('safety-appeal-photo')).toHaveCount(1);
  await testInfo.attach('appeal-form-consent', { body: await page.getByTestId('safety-appeal-form').screenshot(), contentType: 'image/png' });
});
