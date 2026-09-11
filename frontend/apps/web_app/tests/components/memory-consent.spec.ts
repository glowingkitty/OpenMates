/**
 * Component proof for memory-consent count and legacy-history convergence.
 * Uses fictional URL-configured fixtures and never confirms remote consent.
 * Both phone and laptop recordings cover known/unknown counts and selection.
 * Request persistence is separately verified through real dev REST/WebSocket.
 * Architecture: docs/plans/memory-consent-convergence/plan.yml
 */
import { expect, test } from '../helpers/cookie-audit';
// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');
const devices = ['web-laptop', 'web-phone'];
const device = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390 ? 'web-phone' : 'web-laptop';
const proofContract = defineVideoProof({
  id: 'memory-consent-convergence', title: 'One memory permission request', surface: 'web', devices, domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'known', text: 'The permission card shows one available writing style.', checkpoint: 'known', devices },
    { id: 'unknown', text: 'An unknown count is not shown as zero.', checkpoint: 'unknown', devices },
    { id: 'merged', text: 'Duplicate historical requests become one permission dialog with the known count.', checkpoint: 'merged', devices },
    { id: 'selection', text: 'You can change the selection before giving permission.', checkpoint: 'selection', devices },
  ],
  assertions: [
    { id: 'known-count', checkpoint: 'known', visual: 'The writing-style card shows 1/1 entry.', devices },
    { id: 'unknown-count', checkpoint: 'unknown', visual: 'The writing-style card has no fabricated zero count.', devices },
    { id: 'one-request', checkpoint: 'merged', visual: 'One permission dialog shows 1/1 entry in either history order.', devices },
    { id: 'selection-control', checkpoint: 'selection', visual: 'The category can be deselected and reselected before the Include action.', devices },
  ], tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});
const preview = (component: string, variant?: string) => `/dev/preview/${component}?${new URLSearchParams({ chrome: '0', theme: 'light', width: device === 'web-phone' ? '390' : '900', ...(variant ? { variant } : {}) })}`;

// contract-test: direct surface=gui.web assertions=app-memories.conversation.request-convergence,app-memories.conversation.explicit-approval
test('shows honest counts and merges legacy requests without granting consent', async ({ page }, testInfo) => {
  const proof = createVideoProofRuntime(proofContract, { device, attach: testInfo.attach.bind(testInfo) });
  await page.goto(preview('AppSettingsMemoriesPermissionDialog'));
  await proof.assert('known-count', async () => { await expect(page.getByTestId('memory-category-count')).toContainText('1/1'); });
  await proof.checkpoint('known');
  await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);
  await page.goto(preview('AppSettingsMemoriesPermissionDialog', 'unknown'));
  await proof.assert('unknown-count', async () => {
    await expect(page.getByTestId('app-settings-memories-permission-card')).toBeVisible();
    await expect(page.getByTestId('memory-category-count')).toHaveCount(0);
  });
  await proof.checkpoint('unknown');
  await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);
  for (const variant of [undefined, 'reversed']) {
    await page.goto(preview('MemoryConsentHistoryPreview', variant));
    await expect(page.getByTestId('app-settings-memories-permission-dialog')).toHaveCount(1);
    await expect(page.getByTestId('memory-category-count')).toContainText('1/1');
    const dialog = page.getByTestId('app-settings-memories-permission-dialog');
    await expect(dialog).toBeInViewport({ ratio: 1 });
    const bounds = await dialog.boundingBox();
    expect(bounds?.height).toBeGreaterThan(100);
    const hostBounds = await page.getByTestId('memory-history-proof-host').boundingBox();
    expect(hostBounds?.height).toBeGreaterThan(400);
  }
  await proof.assert('one-request', async () => {
    await expect(page.getByTestId('app-settings-memories-permission-dialog')).toBeVisible();
    await expect(page.getByTestId('memory-category-count')).toContainText('1/1');
  });
  await proof.checkpoint('merged');
  await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);
  const toggle = page.getByTestId('memory-category-toggle-mail-writing_styles');
  await toggle.hover();
  await toggle.click();
  await expect(page.getByTestId('btn-include')).toBeDisabled();
  await toggle.click();
  await page.getByTestId('btn-include').focus();
  await proof.assert('selection-control', async () => {
    await expect(page.getByTestId('btn-include')).toBeEnabled();
    await expect(page.getByTestId('btn-include')).toBeFocused();
  });
  await proof.checkpoint('selection');
  await proof.attach();
});
