import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/shared/EmbedVersionTimeline?theme=light&background=%23dbeafe&width=520&chrome=0';

// contract-test: direct surface=gui.web assertions=storage.versions.metadata-and-payload
test('shows the newest bounded version page and loads older metadata on request', async ({ page }, testInfo) => {
  let requests = 0;
  await page.route('**/v1/embeds/preview-embed/versions?**', async (route) => {
    requests += 1;
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    const start = cursor ? 968 : 1000;
    const versions = Array.from({ length: 32 }, (_, index) => ({
      version_number: start - index,
      created_at: 1760000000 + start - index,
      has_snapshot: (start - index) % 32 === 0,
      has_patch: true,
    }));
    await route.fulfill({
      status: 200, contentType: 'application/json',
      headers: { 'access-control-allow-origin': 'http://localhost:5173', 'access-control-allow-credentials': 'true' },
      body: JSON.stringify({ embed_id: 'preview-embed', current_version: 1000, versions,
        next_cursor: cursor ? 937 : 969, readonly: false }),
    });
  });
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  const timeline = page.getByTestId('embed-version-timeline');
  await expect(timeline).toBeVisible();
  await expect(timeline.getByTestId('embed-version-load-more')).toBeVisible();
  await expect(timeline.locator('[data-testid^="version-dot-"]')).toHaveCount(32);
  await expect(timeline).toContainText('32 of 1000 versions');
  expect(requests).toBe(1);
  await timeline.getByTestId('embed-version-load-more').click();
  await expect(timeline.locator('[data-testid^="version-dot-"]')).toHaveCount(64);
  await expect(timeline).toContainText('64 of 1000 versions');
  expect(requests).toBe(2);
  await testInfo.attach('embed-version-timeline-paged', { body: await timeline.screenshot(), contentType: 'image/png' });
});
