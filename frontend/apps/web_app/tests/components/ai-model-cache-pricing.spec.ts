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
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toContainText('normal authenticated personal and team chats');
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toContainText('Billing for workflows and orchestrated subchats remains unchanged.');
    await expect(page.getByTestId('ai-model-automatic-summary')).toContainText('billed separately only when needed');
    await expect(page.getByTestId('ai-model-automatic-summary')).toContainText('normal authenticated personal and team chats');
    await expect(page.getByTestId('ai-model-automatic-summary')).toContainText('If no summary runs, there is no summary charge.');
    await expect(page.getByTestId('ai-model-summary-primary-input')).toContainText('Gemini 3.5 Flash-Lite');
    await expect(page.getByTestId('ai-model-summary-primary-input')).toContainText('1100');
    await expect(page.getByTestId('ai-model-summary-primary-output')).toContainText('130');
    await expect(page.getByTestId('ai-model-summary-fallback-input')).toContainText('GPT-OSS-120b');
    await expect(page.getByTestId('ai-model-summary-fallback-input')).toContainText('2200');
    await expect(page.getByTestId('ai-model-summary-fallback-output')).toContainText('550');
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('shows the active long-context tier and labels implicit writes without a fixed retention tier', async ({ page }) => {
    await page.goto('/dev/preview/settings/AiAskModelDetails?variant=cache-active-included&theme=light&background=%23dbeafe&width=768&chrome=0');
    await waitForComponentPreview(page);

    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Cache write');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Included in ordinary input');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).not.toContainText('5 min');
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toBeVisible();
    await expect(page.getByTestId('ai-model-pricing-section')).toContainText('Standard');
    await expect(page.getByTestId('ai-model-long-context-tier')).toContainText('Over 272,000 input tokens');
    await expect(page.getByTestId('ai-model-long-context-input-row')).toContainText('82.5');
    await expect(page.getByTestId('ai-model-long-context-cache-read-row')).toContainText('1650');
    await expect(page.getByTestId('ai-model-long-context-cache-write-row')).toContainText('Included in ordinary input');
    await expect(page.getByTestId('ai-model-long-context-output-row')).toContainText('20');
    await expect(page.getByTestId('ai-model-long-context-explanation')).toContainText('Total input includes cached input.');
    await expect(page.getByTestId('ai-model-long-context-explanation')).toContainText('whole request');
  });

  // contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity
  test('does not advertise an expired cache tariff', async ({ page }) => {
    await page.goto('/dev/preview/settings/AiAskModelDetails?variant=cache-expired&theme=light&background=%23dbeafe&width=768&chrome=0');
    await waitForComponentPreview(page);

    await expect(page.getByTestId('ai-model-pricing-cache-read-row')).toContainText('Unavailable');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Unavailable');
    await expect(page.getByTestId('ai-model-pricing-cache-write-1h-row')).toHaveCount(0);
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toHaveCount(0);
    await expect(page.getByTestId('ai-model-long-context-tier')).toHaveCount(0);
    await expect(page.getByTestId('ai-model-automatic-summary')).toHaveCount(0);
  });
});
