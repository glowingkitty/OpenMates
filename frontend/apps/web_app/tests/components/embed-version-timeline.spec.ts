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

// contract-test: direct surface=gui.web assertions=storage.versions.bounded-reconstruction
test('shows an error when the content response belongs to another version', async ({ page }) => {
  await page.route('**/v1/embeds/preview-embed/versions?**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    headers: { 'access-control-allow-origin': 'http://localhost:5173', 'access-control-allow-credentials': 'true' },
    body: JSON.stringify({ embed_id: 'preview-embed', current_version: 1000, readonly: false,
      versions: [1000, 999].map((version_number) => ({ version_number, created_at: 1760000000,
        has_snapshot: true, has_patch: false })), next_cursor: null }),
  }));
  await page.route('**/v1/embeds/preview-embed/versions/999?**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    headers: { 'access-control-allow-origin': 'http://localhost:5173', 'access-control-allow-credentials': 'true' },
    body: JSON.stringify({ embed_id: 'preview-embed', version_number: 998, current_version: 1000,
      rows: [{ version_number: 998, encrypted_snapshot: 'unrelated-ciphertext' }], readonly: false }),
  }));
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  const timeline = page.getByTestId('embed-version-timeline');
  await timeline.getByTestId('version-dot-999').click();
  await expect(timeline).toContainText('Version response does not match the selected version');
});

// contract-test: direct surface=gui.web assertions=storage.cold.shared-team-authorized,storage.versions.metadata-and-payload
test('keeps shared Project context when paging and selecting historical content', async ({ page }) => {
  const requests: URL[] = [];
  await page.route('**/v1/embeds/preview-embed/versions**', async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const exact = url.pathname.endsWith('/versions/1');
    const older = url.searchParams.has('cursor');
    await route.fulfill({
      status: 200, contentType: 'application/json',
      headers: { 'access-control-allow-origin': 'http://localhost:5173', 'access-control-allow-credentials': 'true' },
      body: JSON.stringify(exact
        ? { embed_id: 'preview-embed', version_number: 1, current_version: 2, content: 'original source', readonly: true }
        : { embed_id: 'preview-embed', current_version: 2, readonly: true, next_cursor: older ? null : 2,
            versions: [{ version_number: older ? 1 : 2, created_at: 1760000000, has_snapshot: true, has_patch: false }] }),
    });
  });
  const props = encodeURIComponent(JSON.stringify({ projectId: 'project-1', teamId: 'team-7', currentVersion: 2 }));
  await page.goto(`${PREVIEW}&props=${props}`);
  await waitForComponentPreview(page);
  const timeline = page.getByTestId('embed-version-timeline');
  await timeline.getByTestId('embed-version-load-more').click();
  await timeline.getByTestId('version-dot-1').click();
  await expect(timeline.getByTestId('embed-version-changes-toggle')).toBeVisible();
  await timeline.getByTestId('embed-version-changes-toggle').click();
  await expect(timeline.getByTestId('embed-version-changes-view')).toContainText('original source');
  expect(requests).toHaveLength(3);
  for (const url of requests) {
    expect(url.searchParams.get('project_id')).toBe('project-1');
    expect(url.searchParams.get('team_id')).toBe('team-7');
    expect(url.searchParams.has('chat_id')).toBe(false);
  }
  await expect(timeline.getByTestId('embed-version-readonly')).toBeVisible();
  await expect(timeline.getByTestId('restore-version-btn')).toHaveCount(0);
});
