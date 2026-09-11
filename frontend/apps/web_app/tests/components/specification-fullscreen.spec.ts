/**
 * Focused Specification reading preview: sections, proof and disclosure.
 * Uses synthetic Teams data with explicit illustrative evidence labels.
 * Verifies keyboard access and responsive content without account/API fixtures.
 * Contract: feature.specifications; this does not prove backend Spec storage.
 */
import { test, expect } from '../helpers/cookie-audit';
// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const device = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390 ? 'web-phone' : 'web-laptop';
const proofSpec = defineVideoProof({
  id: 'specification-fullscreen-reading', title: 'Read a Specification', surface: 'web',
  devices: ['web-phone', 'web-laptop'], domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'outcome', text: 'Outcome and boundaries introduce the Teams Specification. Proof states are illustrative.', checkpoint: 'outcome', devices: ['web-phone', 'web-laptop'] },
    { id: 'requirements', text: 'Custom sections group requirements with their applicable interfaces and Check evidence.', checkpoint: 'requirements', devices: ['web-phone', 'web-laptop'] },
    { id: 'flow', text: 'Open a user flow in its fullscreen view, then return to the Specification.', checkpoint: 'flow', devices: ['web-phone', 'web-laptop'] },
    { id: 'model', text: 'Open a relevant model to inspect its fields in context.', checkpoint: 'model', devices: ['web-phone', 'web-laptop'] },
  ],
  assertions: [
    { id: 'contracts.ui.human-readable-default', checkpoint: 'outcome', visual: 'The document begins with readable outcome and scope, not raw YAML.', devices: ['web-phone', 'web-laptop'] },
    { id: 'contracts.flows.rich-content-inline', checkpoint: 'flow', visual: 'The parent-owned user flow opens in the shared fullscreen reader.', devices: ['web-phone', 'web-laptop'] },
    { id: 'contracts.models.global-contextual', checkpoint: 'model', visual: 'The canonical model fields appear beneath its reference.', devices: ['web-phone', 'web-laptop'] },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

// contract-test: direct surface=gui.web assertions=contracts.ui.human-readable-default,contracts.flows.rich-content-inline,contracts.models.global-contextual
test('read custom sections, inspect proof, and open flow fullscreen and inspect model details', async ({ page }, testInfo) => {
  const proof = createVideoProofRuntime(proofSpec, { device, attach: testInfo.attach.bind(testInfo) });
  await page.goto('/dev/preview/embeds/specifications/SpecificationEmbedFullscreen?chrome=0&theme=light');
  const root = page.getByTestId('specification-fullscreen');
  await expect(root).toBeVisible();
  await expect(page.getByText('Design preview · proof states are illustrative')).toBeVisible();
  await proof.assert('contracts.ui.human-readable-default', async () => {
    await expect(page.getByRole('heading', { name: 'Outcome', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Scope & boundaries', exact: true })).toBeAttached();
    await expect(page.getByTestId('spec-chapter')).toHaveCount(2);
    await expect(page.getByTestId('spec-requirement')).toHaveCount(3);
  });
  await proof.checkpoint('outcome');
  await page.waitForTimeout(2400);

  await page.getByRole('heading', { name: 'Team creation & deletion' }).scrollIntoViewIfNeeded();
  const firstProof = page.getByTestId('spec-proof').first();
  await firstProof.locator('summary').click();
  await expect(firstProof).toContainText('No current Check Run has been verified');
  await proof.checkpoint('requirements');
  await page.waitForTimeout(2400);

  const flow = page.getByTestId('spec-flow-create-team');
  await flow.getByRole('button').focus();
  await page.keyboard.press('Enter');
  await proof.assert('contracts.flows.rich-content-inline', async () => {
    const flowView = page.getByTestId('spec-flow-fullscreen');
    await expect(flowView).toBeVisible();
    await expect(flowView.locator('ol li')).toHaveCount(5);
    await expect(flowView.getByText('Select the Team in the context switcher.')).toBeVisible();
  });
  await proof.checkpoint('flow');
  await page.waitForTimeout(2400);

  await page.getByTestId('spec-flow-close').click();
  await expect(root).toBeVisible();
  const model = page.getByTestId('spec-model-TeamRecord');
  await model.locator('summary').focus();
  await page.keyboard.press('Enter');
  await proof.assert('contracts.models.global-contextual', async () => {
    await expect(model).toHaveAttribute('open', '');
    await expect(model.locator('dt').first()).toContainText('team_id');
  });
  await proof.checkpoint('model');
  await page.waitForTimeout(2400);
  expect(await root.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
});
