import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/videos/VideoGenerateEmbedFullscreen?chrome=0&background=%23dbeafe';
test.use({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 2, trace: 'retain-on-failure' });

async function open(page: Page, variant: string, width = 900, theme: 'light' | 'dark' = 'light') {
  await page.setViewportSize({ width: Math.max(width, 320), height: width < 500 ? 844 : 900 });
  await page.goto(`${PREVIEW}&variant=${variant}&theme=${theme}&width=${width}`);
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const video = page.getByTestId('video-generate-fullscreen-video');
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.readyState)).toBeGreaterThanOrEqual(1);
  await video.evaluate((el: HTMLVideoElement) => el.pause());
  return video;
}

/**
 * Records what the result follow-up sends; the isolated preview has no backend.
 * The texts are read from the request event, which is delivered before
 * waitForRequest resolves; the route only answers.
 */
function recordFollowups(page: Page) {
  const texts: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/v1/apps/workspace/interpret')) texts.push((request.postDataJSON() as { text: string }).text);
  });
  void page.route('**/v1/apps/workspace/interpret', (route) =>
    route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  return texts;
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const timeline = page.getByTestId('video-timeline');
  // Screenshots taken after this check show the timeline, not only the player above it.
  await timeline.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  const box = (await timeline.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
}

// contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video,videos-generate.result.video-with-timeline
for (const [variant, kind, parts, subtitle] of [
  ['composed', 'composed', 7, 'Composed video · 20 s · 1280 x 720'],
  ['generative', 'generative', 1, 'Generated video · 8 s · 1280 x 720'],
] as const) {
  test(`shows the ${kind} video's timeline directly below the player`, async ({ page }, testInfo) => {
    const video = await open(page, variant);
    const timeline = page.getByTestId('video-timeline');
    await expect(timeline).toBeVisible();
    await expect(timeline).toHaveAttribute('data-made-by', kind);
    await expect(timeline.getByTestId('video-timeline-part')).toHaveCount(parts);
    await expect(page.getByText(subtitle, { exact: false }).first()).toBeVisible();
    const player = (await video.boundingBox())!;
    const bar = (await timeline.boundingBox())!;
    expect(bar.y).toBeGreaterThanOrEqual(player.y + player.height - 1);
    expect(bar.y - (player.y + player.height)).toBeLessThan(48);
    // Parts are listed in time order on the main track.
    const xs = await timeline.locator('[data-track-kind="visual"] [data-testid="video-timeline-part"]').evaluateAll(
      (els) => els.map((el) => el.getBoundingClientRect().x));
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
    await expect(timeline.getByTestId('video-timeline-playhead')).toBeVisible();
    await testInfo.attach(`${variant}-900`, { body: await page.screenshot(), contentType: 'image/png' });
  });
}

// contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video
test('an older video without a stored timeline gets one clip from its length', async ({ page }, testInfo) => {
  await open(page, 'legacy');
  const timeline = page.getByTestId('video-timeline');
  await expect(timeline.getByTestId('video-timeline-part')).toHaveCount(1);
  await expect(timeline.getByTestId('video-timeline-extend-end')).toHaveCount(0);
  await expect(page.getByText('Generated video · 8 s', { exact: false }).first()).toBeVisible();
  await testInfo.attach('legacy-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video
test('a click on the timeline seeks the video and moves the playhead', async ({ page }) => {
  const video = await open(page, 'composed');
  const bar = page.getByTestId('video-timeline').locator('[data-track-kind="visual"]');
  // The follow-up field floats over the lower edge; bring the track to the middle first.
  await bar.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  const box = (await bar.boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.25, box.y + box.height / 2);
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThan(4);
  const playhead = page.getByTestId('video-timeline-playhead');
  const left = await playhead.evaluate((el) => parseFloat((el as HTMLElement).style.left));
  expect(left).toBeGreaterThan(20);
  expect(left).toBeLessThan(30);
  await page.mouse.click(box.x + box.width * 0.05, box.y + box.height / 2);
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeLessThan(2);
});

// contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video
test('parts are keyboard reachable and arrow keys move between them', async ({ page }) => {
  await open(page, 'composed');
  const first = page.getByTestId('video-timeline').locator('[data-part-id="scene-1"]');
  await first.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"]')).toBeFocused();
  await page.keyboard.press('ArrowLeft');
  await expect(first).toBeFocused();
});

// contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video,videos-generate.change.extend-generated-clip
test('extend buttons exist only for generative videos whose model allows the side', async ({ page }) => {
  test.setTimeout(120_000);
  const expected: Record<string, [number, number]> = {
    composed: [0, 0], generative: [1, 1], generativeNoExtend: [0, 0], generativeEndOnly: [0, 1], legacy: [0, 0],
  };
  for (const [variant, [start, end]] of Object.entries(expected)) {
    await open(page, variant);
    await expect(page.getByTestId('video-timeline-extend-start'), `${variant} start`).toHaveCount(start);
    await expect(page.getByTestId('video-timeline-extend-end'), `${variant} end`).toHaveCount(end);
  }
});

// contract-test: direct surface=gui.web assertions=videos-generate.change.extend-generated-clip
test('an extension without a description is not sent and Escape closes the field', async ({ page }, testInfo) => {
  const sent = recordFollowups(page);
  await open(page, 'generative');
  const plus = page.getByTestId('video-timeline-extend-end');
  await plus.click();
  const input = page.getByTestId('video-extend-input');
  await expect(input).toBeFocused();
  await page.getByTestId('video-extend-send').click();
  await expect(page.getByTestId('video-extend-hint')).toBeVisible();
  await input.fill('   ');
  await page.getByTestId('video-extend-send').click();
  await expect(page.getByTestId('video-extend-hint')).toBeVisible();
  await testInfo.attach('extend-empty-hint-900', { body: await page.screenshot(), contentType: 'image/png' });
  await page.waitForTimeout(300);
  expect(sent).toHaveLength(0);
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('video-extend-field')).toHaveCount(0);
  await expect(plus).toBeFocused();
});

// contract-test: direct surface=gui.web assertions=videos-generate.change.extend-generated-clip
test('Send asks the assistant to extend the video with the exact marker line', async ({ page }) => {
  const sent = recordFollowups(page);
  await open(page, 'generative');
  await page.getByTestId('video-timeline-extend-end').click();
  await page.getByTestId('video-extend-input').fill('waves roll onto the shore');
  const request = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('video-extend-send').click();
  await request;
  expect(sent).toEqual(['Extend this video at the end: waves roll onto the shore']);

  await page.getByTestId('video-timeline-extend-start').click();
  await page.getByTestId('video-extend-input').fill('the sun is still below the ridge');
  const second = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.keyboard.press('Enter');
  await second;
  expect(sent[1]).toBe('Extend this video at the start: the sun is still below the ridge');
});

// contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
test('edit mode collects a text change and a shortened part and applies them as one request', async ({ page }, testInfo) => {
  const sent = recordFollowups(page);
  await open(page, 'composed');
  const toggle = page.getByTestId('video-edit-button');
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId('video-edit-hint')).toBeVisible();
  await expect(page.getByTestId('video-edit-pending-count')).toHaveText('Pending changes: 0');
  await expect(page.getByTestId('video-edit-apply')).toBeDisabled();

  await page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"]').click();
  const inspector = page.getByTestId('video-edit-inspector');
  await expect(inspector).toContainText('Budget vote');
  await inspector.getByTestId('video-edit-text-headline').fill('Council rejects the budget');
  await inspector.getByTestId('video-edit-shorten-end-more').click();
  await inspector.getByTestId('video-edit-shorten-end-more').click();
  await expect(inspector.getByTestId('video-edit-shorten-end-value')).toHaveText('1 s');
  await expect(page.getByTestId('video-edit-pending-count')).toHaveText('Pending changes: 2');
  await expect(page.getByTestId('video-edit-new-length')).toHaveText('New length 19 s');
  await expect(page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"] [data-testid="video-timeline-trim-end"]')).toBeVisible();
  await testInfo.attach('edit-selected-part-900', { body: await page.screenshot(), contentType: 'image/png' });

  const request = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('video-edit-apply').click();
  await request;
  expect(sent).toEqual([[
    'Apply these edits to this video:',
    '- Part "Budget vote" (id scene-2): change text "headline" from "Council approves the budget" to "Council rejects the budget"',
    '- Part "Budget vote" (id scene-2): shorten by 1.0 s at the end',
  ].join('\n')]);
});

// contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
test('Discard restores the video, removing the last part is refused and leaving asks first', async ({ page }) => {
  const sent = recordFollowups(page);
  await open(page, 'composed');
  await page.getByTestId('video-edit-button').click();
  await page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"]').click();
  const text = page.getByTestId('video-edit-text-headline');
  await text.fill('Changed');
  await expect(page.getByTestId('video-edit-pending-count')).toHaveText('Pending changes: 1');
  await page.getByTestId('video-edit-discard').click();
  await expect(page.getByTestId('video-edit-pending-count')).toHaveText('Pending changes: 0');
  expect(sent).toHaveLength(0);

  await page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"]').click();
  await page.getByTestId('video-edit-remove').click();
  await expect(page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"]')).toHaveAttribute('data-removed', 'true');
  await expect(page.getByTestId('video-edit-new-length')).toHaveText('New length 15 s');
  for (const id of ['scene-1', 'scene-3', 'scene-4']) {
    await page.locator(`[data-testid="video-timeline-part"][data-part-id="${id}"]`).click();
    await page.getByTestId('video-edit-remove').click();
  }
  await page.locator('[data-testid="video-timeline-part"][data-part-id="scene-5"]').click();
  await expect(page.getByTestId('video-edit-remove')).toBeDisabled();
  await expect(page.getByTestId('video-edit-remove-hint')).toBeVisible();

  await page.getByTestId('video-edit-button').click();
  await expect(page.getByTestId('video-edit-confirm')).toBeVisible();
  await page.getByTestId('video-edit-keep').click();
  await expect(page.getByTestId('video-edit-pending')).toBeVisible();
  await page.getByTestId('video-edit-button').click();
  await page.getByTestId('video-edit-confirm-discard').click();
  await expect(page.getByTestId('video-edit-pending')).toHaveCount(0);
  await expect(page.locator('[data-removed="true"]')).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=videos-generate.change.edit-mode
test('a generative video can only be shortened from its start or end', async ({ page }) => {
  const sent = recordFollowups(page);
  await open(page, 'generative');
  await page.getByTestId('video-edit-button').click();
  const inspector = page.getByTestId('video-edit-inspector');
  await expect(inspector).toBeVisible();
  await expect(inspector.getByTestId('video-edit-remove')).toHaveCount(0);
  await expect(inspector.locator('input')).toHaveCount(0);
  await inspector.getByTestId('video-edit-shorten-start-more').click();
  await inspector.getByTestId('video-edit-shorten-end-more').click();
  await inspector.getByTestId('video-edit-shorten-end-more').click();
  const request = page.waitForRequest('**/v1/apps/workspace/interpret');
  await page.getByTestId('video-edit-apply').click();
  await request;
  expect(sent).toEqual(['Apply these edits to this video:\n- Trim the video: remove 0.5 s from the start and 1.0 s from the end']);
});

// contract-test: direct surface=gui.web assertions=videos-generate.change.same-video-next-version
test('a second version shows the version history under the timeline', async ({ page }, testInfo) => {
  await page.route('**/v1/embeds/33333333-3333-4333-8333-333333333333/versions?**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    headers: { 'access-control-allow-origin': 'http://localhost:5173', 'access-control-allow-credentials': 'true' },
    body: JSON.stringify({
      embed_id: '33333333-3333-4333-8333-333333333333', current_version: 2, next_cursor: null, readonly: false,
      versions: [2, 1].map((n) => ({ version_number: n, created_at: 1760000000 + n, has_snapshot: true, has_patch: false })),
    }),
  }));
  await open(page, 'version2');
  const history = page.getByTestId('embed-version-timeline');
  await expect(history).toBeVisible();
  await expect(history.locator('[data-testid^="version-dot-"]')).toHaveCount(2);
  await expect(page.getByTestId('video-generate-fullscreen')).toHaveAttribute('data-embed-version', '2');
  await history.evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await testInfo.attach('version-two-900', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: direct surface=gui.web assertions=videos-generate.timeline.below-the-video
for (const theme of ['light', 'dark'] as const) {
  for (const width of [900, 390, 320]) {
    test(`fits ${width}px without horizontal overflow in ${theme} (all variants, edit mode, extend field)`, async ({ page }, testInfo) => {
      test.setTimeout(120_000);
      for (const variant of ['composed', 'generative', 'legacy']) {
        await open(page, variant, width, theme);
        await noHorizontalOverflow(page);
        await testInfo.attach(`${variant}-${theme}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      }
      await open(page, 'generative', width, theme);
      await page.getByTestId('video-timeline-extend-end').click();
      await expect(page.getByTestId('video-extend-input')).toBeFocused();
      await noHorizontalOverflow(page);
      await testInfo.attach(`extend-open-${theme}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      await open(page, 'composed', width, theme);
      await page.getByTestId('video-edit-button').click();
      await page.locator('[data-testid="video-timeline-part"][data-part-id="scene-2"]').click();
      await page.getByTestId('video-edit-shorten-start-more').click();
      await page.getByTestId('video-edit-text-headline').fill('Council rejects the budget');
      await noHorizontalOverflow(page);
      await testInfo.attach(`edit-selected-${theme}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    });
  }
}
