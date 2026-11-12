import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const preview = (variant: string) => `/dev/preview/settings/AppSkillModelDetails?variant=${variant}&theme=light&background=%23dbeafe&width=768&chrome=0`;

test.describe('App skill model long-context pricing preview', () => {
  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('Haiku catalog shows standard and over-100k prices with five-minute writes', async ({ page }) => {
    await page.goto(preview('catalog-haiku'));
    await waitForComponentPreview(page);

    await expect(page.getByTestId('app-model-pricing-cache-read-row')).toContainText('66670');
    await expect(page.locator('.pricing-tier-title').first()).toContainText('Standard');
    await expect(page.getByTestId('app-model-pricing-cache-write-row')).toContainText('5335');
    await expect(page.getByTestId('app-model-pricing-cache-write-1h-row')).toHaveCount(0);
    const tier = page.getByTestId('app-model-long-context-tier');
    await expect(tier).toContainText('Over 100,000 input tokens');
    await expect(tier).toContainText('13335');
    await expect(tier).toContainText('1070');
    await expect(tier).toContainText('270');
    await expect(tier).toContainText('whole request');
  });
  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('shows the active long-context rates and included cache writes', async ({ page }) => {
    await page.goto(preview('long-context-active'));
    await waitForComponentPreview(page);

    await expect(page.getByTestId('app-model-pricing-cache-read-row')).toContainText('6670');
    await expect(page.getByTestId('app-model-pricing-cache-write-row')).toContainText('Included in ordinary input');
    await expect(page.getByTestId('app-model-pricing-cache-write-row')).not.toContainText('5 min');
    await expect(page.getByTestId('app-model-cache-pricing-note')).toContainText('Your receipt shows the usage charged.');
    await expect(page.getByTestId('app-model-cache-pricing-note')).toContainText('Billing for workflows and orchestrated subchats remains unchanged.');
    const tier = page.getByTestId('app-model-long-context-tier');
    await expect(tier).toContainText('Over 272,000 input tokens');
    await expect(tier).toContainText('Total input includes cached input.');
    await expect(tier).toContainText('170');
    await expect(tier).toContainText('3335');
    await expect(tier).toContainText(/\b45\b/);
    await expect(tier).toContainText('Included in ordinary input');
    await expect(page.getByTestId('app-model-automatic-summary')).toContainText('billed separately only when needed');
    await expect(page.getByTestId('app-model-automatic-summary')).toContainText('normal authenticated personal and team chats');
    await expect(page.getByTestId('app-model-summary-primary-input')).toContainText('2225');
    await expect(page.getByTestId('app-model-summary-primary-output')).toContainText('270');
    await expect(page.getByTestId('app-model-summary-fallback-input')).toContainText('4445');
    await expect(page.getByTestId('app-model-summary-fallback-output')).toContainText('1115');
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('does not advertise cache or long-context rates while disabled', async ({ page }) => {
    await page.goto(preview('long-context-inactive'));
    await waitForComponentPreview(page);

    await expect(page.getByTestId('app-model-pricing-cache-read-row')).toContainText('Unavailable');
    await expect(page.getByTestId('app-model-pricing-cache-write-row')).toContainText('Unavailable');
    await expect(page.getByTestId('app-model-cache-pricing-note')).toHaveCount(0);
    await expect(page.getByTestId('app-model-long-context-tier')).toHaveCount(0);
    await expect(page.getByTestId('app-model-automatic-summary')).toHaveCount(0);
  });
});
