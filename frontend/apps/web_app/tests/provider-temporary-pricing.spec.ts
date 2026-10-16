import { expect, test } from './helpers/cookie-audit';
import { waitForComponentPreview } from './helpers/component-preview';

// playwright-account: not_required reason=public_model_catalog_and_component_preview
// contract-test: direct surface=gui.web assertions=billing.models.active-price-consistency,ai-model-routing.catalog.public-read-only
// The isolated runner has no provider credentials. Public discovery must retain
// availability filtering; configured-route tariff serialization is covered by
// test_public_current_promotions_use_real_provider_yaml_and_live_config_resolver.
test('key-free public catalog filters unavailable models and generated details show Mistral promotion', async ({ page }) => {
  // Verify the reviewed tariff while its separate cache policy is current.
  await page.clock.install({ time: new Date('2026-10-14T12:00:00Z') });
  const apiUrl = process.env.PLAYWRIGHT_TEST_API_URL || process.env.OPENMATES_E2E_API_URL;
  if (!apiUrl) throw new Error('The isolated API URL is required.');
  const response = await page.request.get(`${apiUrl}/v1/models`);
  expect(response.status()).toBe(200);
  const payload = await response.json();
  expect(payload.object).toBe('list');
  const modelIds = payload.data.map((model: { id: string }) => model.id);
  for (const id of ['google/gemini-4-argon', 'mistral/mistral-large-4']) {
    expect(modelIds).not.toContain(id);
    const detail = await page.request.get(`${apiUrl}/v1/models/${id}`);
    expect(detail.status()).toBe(404);
  }
  await page.goto('/dev/preview/settings/AiAskModelDetails?variant=catalog-mistral-large&theme=light&width=768&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('ai-model-pricing-input-row')).toContainText('490');
  await expect(page.getByTestId('ai-model-pricing-cache-read-row')).toContainText('4760');
  await expect(page.getByTestId('ai-model-pricing-output-row')).toContainText('158');
  await expect(page.getByTestId('ai-model-temporary-price-note')).toContainText('No end date has been announced');
});

