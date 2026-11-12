// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: supporting surface=gui.web assertions=app-skills.progress.live-status
test('a processing app skill embed shows live progress and updates on later frames', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 900, height: 700 });
  const query = new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: '700' });
  await page.goto(`/dev/preview/embeds/EmbedProgressFixture?${query}`);
  await waitForComponentPreview(page);

  const card = page.getByTestId('embed-preview');
  const progress = card.getByTestId('embed-progress');
  await expect(card).toHaveAttribute('data-status', 'processing');
  const expectNotClipped = async () => {
    const clipped = await progress.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(clipped).toBe(false);
  };

  // First frame: 4 sources, nothing done, no results yet -> no results part.
  await expect(progress).toHaveText('0/4 sources');
  await expect(progress).toHaveAttribute('title', '0/4 sources');
  await expectNotClipped();
  await expect(progress).toHaveAttribute('data-sources-total', '4');
  await expect(progress).toHaveAttribute('data-sources-done', '0');
  await expect(progress).toHaveAttribute('data-result-count', '0');
  await testInfo.attach('progress-first-frame', { body: await card.screenshot(), contentType: 'image/png' });

  // A later frame replaces the earlier one while the card stays processing.
  await page.getByTestId('send-frame-second').click();
  await expect(progress).toHaveText('2/4 · 17 results');
  await expect(progress).toHaveAttribute('data-sources-done', '2');
  await expectNotClipped();
  await expect(progress).toHaveAttribute('data-result-count', '17');
  await expect(card).toHaveAttribute('data-status', 'processing');
  await testInfo.attach('progress-second-frame', { body: await card.screenshot(), contentType: 'image/png' });

  // A frame with a lower seq is ignored.
  await page.getByTestId('send-frame-stale').click();
  await page.waitForTimeout(500);
  await expect(progress).toHaveAttribute('data-sources-done', '2');
  await expect(progress).toHaveAttribute('data-result-count', '17');

  // A single source reads "Searching…" with the results so far.
  await page.getByTestId('send-frame-single').click();
  await expect(progress).toHaveText('17 results');
  await expectNotClipped();
  await expect(progress).toHaveAttribute('data-sources-total', '1');
  await testInfo.attach('progress-single-source', { body: await card.screenshot(), contentType: 'image/png' });
});
