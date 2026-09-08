/**
 * Public PDF metadata-only fallback regression.
 * The original public fixture omits private PDF screenshots and keys.
 * An unavailable thumbnail must still leave a visible view icon.
 * Uses a bare component preview and real CSS rather than private media.
 * Architecture: docs/architecture/embeds.md.
 */
import { expect, test } from '../helpers/cookie-audit';
// playwright-account: not_required reason=isolated_component_preview
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createVideoProofRuntime, defineVideoProof } = require('../helpers/video-proof');

const ASSERTION = 'public-example-chats.transcript.safe-rendering';
const PHONE_WIDTH = 390;
const DEVICE = Number(process.env.PLAYWRIGHT_VIDEO_WIDTH) === PHONE_WIDTH ? 'web-phone' : 'web-laptop';
const PROOF = defineVideoProof({
  id: 'pdf-view-missing-media-fallback',
  title: 'PDF preview without private page media',
  surface: 'web',
  devices: ['web-laptop', 'web-phone'],
  domain: 'app.dev.openmates.org',
  transcript: [{ id: 'fallback', text: 'When public page media is absent, the PDF view card retains its visible view icon and page information.', checkpoint: 'fallback', devices: ['web-laptop', 'web-phone'] }],
  assertions: [{ id: ASSERTION, checkpoint: 'fallback', visual: 'The PDF view card has a visible eye icon and page information, without a blank icon tile.', devices: ['web-laptop', 'web-phone'] }],
  tutorial: { readingWordsPerSecond: 2.5, minimumHoldMs: 1800, maximumHoldMs: 5000 },
});

// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('metadata-only PDF view retains a visible fallback icon', async ({ page }, testInfo) => {
  const proof = createVideoProofRuntime(PROOF, { device: DEVICE, attach: testInfo.attach.bind(testInfo) });
  const params = new URLSearchParams({ chrome: '0', width: DEVICE === 'web-phone' ? '390' : '420', props: JSON.stringify({ isMobile: DEVICE === 'web-phone' }) });
  await page.goto(`/dev/preview/embeds/pdf/PdfViewEmbedPreview?${params}`, { waitUntil: 'networkidle' });
  const card = page.getByTestId('embed-preview');
  const icon = page.getByTestId('pdf-view-fallback-icon');
  await expect(card).toBeVisible();
  await expect(card).toContainText('Page 1');
  await expect(icon).toBeVisible();
  await page.evaluate(() => {
    window.addEventListener('pdf-preview-fixture-open', () => document.documentElement.setAttribute('data-pdf-fixture-opened', 'true'), { once: true });
  });
  await card.hover();
  await card.focus();
  await expect(card).toBeFocused();
  await proof.assert(ASSERTION, async () => {
    const iconStyle = await icon.evaluate((node: HTMLElement) => ({
      background: getComputedStyle(node, '::after').backgroundImage,
      width: node.getBoundingClientRect().width,
      height: node.getBoundingClientRect().height,
    }));
    expect(iconStyle.background).toContain('visible');
    expect(iconStyle.width).toBeGreaterThan(0);
    expect(iconStyle.height).toBeGreaterThan(0);
    const iconBox = await icon.boundingBox();
    const detailsBox = await page.getByTestId('pdf-view-details').boundingBox();
    expect(iconBox).not.toBeNull();
    expect(detailsBox).not.toBeNull();
    // The fallback belongs inside the details area, clear of the app/status bar.
    expect(iconBox!.x).toBeGreaterThanOrEqual(detailsBox!.x);
    expect(iconBox!.y).toBeGreaterThanOrEqual(detailsBox!.y);
    expect(iconBox!.x + iconBox!.width).toBeLessThanOrEqual(detailsBox!.x + detailsBox!.width);
    expect(iconBox!.y + iconBox!.height).toBeLessThanOrEqual(detailsBox!.y + detailsBox!.height);

  });
  await proof.checkpoint('fallback');
  await page.waitForTimeout(PROOF.tutorial.minimumHoldMs);
  await card.press('Enter');
  await expect.poll(() => page.evaluate(() => document.documentElement.getAttribute('data-pdf-fixture-opened'))).toBe('true');
  await proof.attach();
});
