// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// Supports the shared rule against silently switching the requested provider;
// full registered-skill validation is exercised by the real CLI check.
// contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated
test('CCC transcript shows its title and provider without YouTube metadata requests', async ({ page }, testInfo) => {
  const youtubeRequests: string[] = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname === '/api/v1/youtube' || url.hostname === 'youtube.com' || url.hostname.endsWith('.youtube.com')) {
      youtubeRequests.push(request.url());
    }
  });
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    const params = new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), variant: 'mediaCCC' });
    await page.goto(`/dev/preview/embeds/videos/VideoTranscriptEmbedPreview?${params}`);
    const canvas = await waitForComponentPreview(page);
    await expect(canvas.getByTestId('transcript-title')).toHaveText('A post-American, enshittification-resistant internet');
    await expect(canvas.getByTestId('transcript-subtitle')).toContainText('via media.ccc.de:');
    await expect(canvas.getByTestId('transcript-subtitle')).toContainText('4 words');
    expect(youtubeRequests).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`ccc-transcript-${width}.png`), animations: 'disabled' });
  }
});
