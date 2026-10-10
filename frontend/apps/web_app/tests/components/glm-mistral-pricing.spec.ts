import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared proof helpers use CommonJS. */
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const proofContract = defineVideoProof({
  id: 'glm-mistral-pricing',
  title: 'GLM 5.3 Mistral hosting and cache pricing',
  surface: 'web',
  devices: ['web-laptop'],
  domain: 'app.dev.openmates.org',
  transcript: [{
    id: 'pricing', checkpoint: 'glm-pricing', devices: ['web-laptop'],
    text: 'GLM 5.3 uses Mistral hosting with discounted cache reads and cache writes included in ordinary input.',
  }],
  assertions: [{
    id: 'billing.surface.semantic-parity', checkpoint: 'glm-pricing', devices: ['web-laptop'],
    visual: 'GLM shows 238 input tokens, 2380 cached input tokens, and 75 output tokens per credit, with writes included.',
  }],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

// contract-test: supporting surface=gui.web assertions=billing.surface.semantic-parity,ai-model-routing.catalog.capability-recommendation-variants
test('GLM catalog shows Mistral as its host and active cache prices', async ({ page }, testInfo) => {
  const proof = createVideoProofRuntime(proofContract, {
    device: 'web-laptop', attach: testInfo.attach.bind(testInfo),
  });
  await page.goto('/dev/preview/settings/AiAskModelDetails?variant=catalog-glm&theme=light&width=768&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('ai-model-description')).toContainText('hosted by Mistral');
  await proof.assert('billing.surface.semantic-parity', async () => {
    await expect(page.getByTestId('ai-model-pricing-input-row')).toContainText('Uncached input');
    await expect(page.getByTestId('ai-model-pricing-input-row')).toContainText('238');
    await expect(page.getByTestId('ai-model-pricing-cache-read-row')).toContainText('2380');
    await expect(page.getByTestId('ai-model-pricing-cache-write-row')).toContainText('Included in ordinary input');
    await expect(page.getByTestId('ai-model-pricing-output-row')).toContainText('75');
    await expect(page.getByTestId('ai-model-cache-pricing-note')).toContainText('Your receipt shows the usage charged.');
  });
  await proof.checkpoint('glm-pricing');
  await expect(page.getByTestId('ai-model-provider-option-mistral')).toContainText('Mistral');
  await expect(page.getByTestId('ai-model-provider-option-mistral')).toContainText('EU');
  await proof.attach();
});
