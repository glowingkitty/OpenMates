import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

test.describe('AI model cache pricing preview', () => {
  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('shows separate read and write rates only for an active fixture', async ({ page }) => {
    await page.goto('/dev/preview/settings/AiAskModelDetails?variant=cache-active&theme=light&background=%23dbeafe&width=768&chrome=0');
    await waitForComponentPreview(page);

    await expect(page.getByTestId('ai-model-pricing-input-row')).toContainText('Uncached input');
    await expect(page.getByTestId('ai-model-pricing-cache-read-row')).toContainText('350');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('28');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Cache write (5 min)');
    await expect(page.getByTestId('ai-model-pricing-cache-write-1h-row')).toContainText('17');
    await expect(page.getByTestId('ai-model-pricing-output-row')).toContainText('Output (including thinking)');
    await expect(page.getByTestId('ai-model-pricing-cache-read-row')).not.toContainText('Unavailable');
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toContainText('Cache reads reuse earlier input at a lower price.');
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toContainText('Your receipt shows the usage charged.');
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('labels implicit cache writes without a fixed retention tier', async ({ page }) => {
    await page.goto('/dev/preview/settings/AiAskModelDetails?variant=cache-active-included&theme=light&background=%23dbeafe&width=768&chrome=0');
    await waitForComponentPreview(page);

    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Cache write');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Included in ordinary input');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).not.toContainText('5 min');
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toBeVisible();
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('does not advertise an expired cache tariff', async ({ page }) => {
    await page.goto('/dev/preview/settings/AiAskModelDetails?variant=cache-expired&theme=light&background=%23dbeafe&width=768&chrome=0');
    await waitForComponentPreview(page);

    await expect(page.getByTestId('ai-model-pricing-cache-read-row')).toContainText('Unavailable');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Unavailable');
    await expect(page.getByTestId('ai-model-pricing-cache-write-1h-row')).toHaveCount(0);
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toHaveCount(0);
  });
});
