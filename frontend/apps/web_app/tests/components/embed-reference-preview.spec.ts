// Focused browser regression for shared event reference rendering.
// Fixtures use the historical event_result content type without private data.
// Verifies a readable event card and terminal missing-reference feedback.
// All captures use the bare component preview with URL-selected state.
// Architecture: docs/architecture/embeds.md
// playwright-account: not_required reason=isolated_component_preview

import { test, expect } from '../helpers/cookie-audit';
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const devices = ['web-laptop', 'web-phone'];
const device = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === 390 ? 'web-phone' : 'web-laptop';
const proofContract = defineVideoProof({
  id: 'shared-event-reference-preview', title: 'Shared event previews', surface: 'web', devices,
  domain: 'app.dev.openmates.org',
  transcript: [
    { id: 'event', text: 'An event reference opens its event card with the title and date.', checkpoint: 'event', devices },
    { id: 'missing', text: 'If a reference is unavailable, loading ends with a clear message.', checkpoint: 'missing', devices },
  ],
  assertions: [
    { id: 'event-card', checkpoint: 'event', visual: 'The event card shows Community workshop without a loading placeholder.', devices },
    { id: 'bounded-loading', checkpoint: 'missing', visual: 'Preview unavailable replaces Loading preview.', devices },
  ],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

const previewUrl = (variant?: string) => `/dev/preview/embeds/EmbedReferencePreview?${new URLSearchParams({
  chrome: '0', theme: 'light', width: device === 'web-phone' ? '360' : '600',
  ...(variant ? { variant } : {}),
})}`;

// contract-test: direct surface=gui.web assertions=chat-share-settings.shared-link-open,chats.rendering.assistant-document-convergence
test('renders historical event references and ends missing-reference loading', async ({ page }, testInfo) => {
  const proof = createVideoProofRuntime(proofContract, { device, attach: testInfo.attach.bind(testInfo) });
  await page.goto(previewUrl());
  await proof.assert('event-card', async () => {
    const card = page.getByTestId('embed-preview');
    await expect(card).toHaveAttribute('data-app-id', 'events');
    await expect(card).toHaveAttribute('data-skill-id', 'event');
    await expect(card).toContainText('Community workshop');
    await expect(card).toBeInViewport({ ratio: 1 });
    await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
    await card.hover();
  });
  await proof.checkpoint('event');
  await page.waitForTimeout(proofContract.tutorial.minimumHoldMs);
  await page.goto(previewUrl('missing'));
  await proof.assert('bounded-loading', async () => {
    await expect(page.getByText('Preview unavailable', { exact: true })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Loading preview...', { exact: true })).toHaveCount(0);
  });
  await proof.checkpoint('missing');
  await proof.attach();
});
