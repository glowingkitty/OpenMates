import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=billing.models.active-price-consistency
// The same mounted page crosses the inclusive UTC expiry without a rebuild.
test('open Argon details switch to regular rates at the next UTC day', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-11-30T12:00:00Z') });
  await page.goto('/dev/preview/settings/AiAskModelDetails?variant=catalog-argon&theme=light&width=768&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('ai-model-pricing-input-row')).toContainText('160');
  await expect(page.getByTestId('ai-model-pricing-output-row')).toContainText('30');
  await expect(page.getByTestId('ai-model-temporary-price-note')).toContainText('2026-11-30 (UTC)');
  await page.clock.pauseAt(new Date('2026-11-30T23:59:59Z'));
  await page.clock.runFor(2000);
  await expect(page.getByTestId('ai-model-pricing-input-row')).toContainText('80');
  await expect(page.getByTestId('ai-model-pricing-output-row')).toContainText('15');
  await expect(page.getByTestId('ai-model-temporary-price-note')).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=billing.models.active-price-consistency
test('an undated promotion never presents its minimum guarantee as an expiry', async ({ page }) => {
  await page.goto('/dev/preview/settings/AiAskModelDetails?variant=promotion-undated&theme=dark&width=390&chrome=0');
  await waitForComponentPreview(page);
  const note = page.getByTestId('ai-model-temporary-price-note');
  await expect(note).toContainText('No end date has been announced');
  await expect(note).not.toContainText('2026-10-20');
});

// contract-test: direct surface=gui.web assertions=billing.models.active-price-consistency
test('Google Pro ordinary long-context prices remain visible while caching is pending', async ({ page }) => {
  await page.goto('/dev/preview/settings/AiAskModelDetails?variant=catalog-google-pro&theme=light&width=768&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('ai-model-long-context-explanation')).toContainText('200,000');
  await expect(page.getByTestId('ai-model-long-context-input-row')).toContainText('85');
  await expect(page.getByTestId('ai-model-long-context-output-row')).toContainText('20');
  await expect(page.getByTestId('ai-model-long-context-cache-read-row')).toContainText('Unavailable');
  await expect(page.getByTestId('ai-model-long-context-cache-write-row')).toContainText('Unavailable');
});
