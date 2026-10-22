import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

const previews = [
  'images/ImageResultEmbedPreview',
  'images/ImageEmbedPreview',
  'images/ImageGenerateEmbedPreview',
  'videos/VideoEmbedPreview',
  'videos/VideoGenerateEmbedPreview',
];
const fullscreens = [
  'images/ImageResultEmbedFullscreen',
  'images/ImageEmbedFullscreen',
  'images/ImageGenerateEmbedFullscreen',
  'videos/VideoEmbedFullscreen',
  'videos/VideoGenerateEmbedFullscreen',
];

for (const width of [390, 1100]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`media results preserve full media and shared structure at ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    const fixture = await page.request.get('/images/examples/group1.jpg');
    expect(fixture.ok()).toBeTruthy();
    const image = await fixture.body();
    await page.route('**/api/v1/image?*', route => route.fulfill({ contentType: 'image/jpeg', body: image }));
    for (const component of previews) {
      await page.goto(`/dev/preview/embeds/${component}?chrome=0&theme=light&width=${width}`);
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview');
      await expect(card).toHaveClass(/result-preview/);
      await expect(card.getByTestId('result-card-title')).toBeVisible();
      await expect(card.getByTestId('embed-basic-infos-bar')).toHaveCount(0);
      const media = card.getByTestId('result-card-media').locator('img:not(.provider-icon):not(.model-icon), video').first();
      await expect(media).toBeVisible();
      await expect.poll(() => media.evaluate((element) => element instanceof HTMLImageElement
        ? element.complete && element.naturalWidth > 0
        : (element as HTMLVideoElement).readyState >= 2)).toBe(true);
      await expect(media).toHaveCSS('object-fit', 'contain');
      const bounds = await card.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(-1);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
      await testInfo.attach(`${component.replace('/', '-')}-${width}px-default`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
      });
    }
    for (const component of fullscreens) {
      await page.goto(`/dev/preview/embeds/${component}?chrome=0&theme=light&width=${width}`);
      await waitForComponentPreview(page);
      await expect(page.getByTestId('result-embed-content')).toHaveAttribute('data-app-id', component.split('/')[0]);
      await expect(page.getByTestId('apps-request-composer')).toBeVisible();
      const media = page.getByTestId('result-media').locator('img.result-primary-media, video.result-primary-media').first();
      await expect(media).toBeVisible();
      await expect.poll(() => media.evaluate((element) => element instanceof HTMLImageElement
        ? element.complete && element.naturalWidth > 0
        : (element as HTMLVideoElement).readyState >= 2)).toBe(true);
      await expect(media).toHaveCSS('object-fit', 'contain');
      const bounds = await media.boundingBox();
      expect(bounds!.x).toBeGreaterThanOrEqual(-1);
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width + 1);
      if (component.startsWith('images/')) {
        const naturalWidth = await media.evaluate((element: HTMLImageElement) => element.naturalWidth);
        expect(bounds!.width).toBeGreaterThan(naturalWidth);
      }
      if (component.startsWith('videos/')) {
        const composer = await page.getByTestId('apps-request-composer').boundingBox();
        expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(composer!.y - 8);
      }
      await testInfo.attach(`${component.replace('/', '-')}-${width}px-default`, {
        body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
      });
    }
    await page.goto(`/dev/preview/embeds/images/ImageResultEmbedFullscreen?chrome=0&theme=light&width=${width}&variant=failedImage`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('image-result-fullscreen-placeholder')).toBeVisible();
    await expect(page.getByTestId('apps-request-composer')).toBeVisible();
    await testInfo.attach(`ImageResultEmbedFullscreen-${width}px-missing-media`, {
      body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
      contentType: 'image/png',
    });
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('generated video previews retain native controls and fullscreen PiP remains available after play', async ({ page }) => {
  await page.goto('/dev/preview/embeds/videos/VideoGenerateEmbedPreview?chrome=0&width=700');
  await waitForComponentPreview(page);
  const video = page.getByTestId('video-generate-video');
  await expect(video).toHaveAttribute('controls', '');
  await expect(video).toHaveAttribute('playsinline', '');
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
  await video.focus();
  await video.press('Space');
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(false);
  await video.press('Space');
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  await expect(page.getByTestId('video-generate-video')).toBeVisible();

  const fixture = await page.request.get('/images/examples/group1.jpg');
  const image = await fixture.body();
  await page.route('**/api/v1/image?*', route => route.fulfill({ contentType: 'image/jpeg', body: image }));
  await page.goto('/dev/preview/embeds/videos/VideoEmbedFullscreen?chrome=0&width=1100');
  await waitForComponentPreview(page);
  await expect(page.locator('.embed-header-cta')).toHaveAttribute('href', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  await page.locator('.play-button-overlay').click();
  await expect(page.locator('.video-playing-spacer')).toBeVisible();
  const pip = page.locator('.pip-button');
  await expect(pip).toBeVisible();
  await pip.focus();
  await expect(pip).toBeFocused();
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('uploaded authenticity and generated prompt controls survive the shared result shell', async ({ page }) => {
  const props = encodeURIComponent(JSON.stringify({ aiDetection: { ai_generated: 0.1, provider: 'sightengine', status: 'success' } }));
  await page.goto(`/dev/preview/embeds/images/ImageEmbedFullscreen?chrome=0&width=700&props=${props}`);
  await waitForComponentPreview(page);
  const authenticity = page.getByTestId('image-authenticity-badge');
  await expect(authenticity).toBeVisible();
  await authenticity.hover();
  await expect(authenticity).toHaveAttribute('aria-expanded', 'true');
  await authenticity.click();
  await expect(authenticity).toHaveAttribute('aria-expanded', 'false');
  await page.mouse.move(0, 0);
  await authenticity.focus();
  await authenticity.press('Enter');
  await expect(authenticity).toHaveAttribute('aria-expanded', 'true');
  await expect(authenticity).toHaveClass(/expanded/);
  await page.goto('/dev/preview/embeds/images/ImageGenerateEmbedFullscreen?chrome=0&width=700');
  await waitForComponentPreview(page);
  await expect(page.getByRole('button', { name: 'Copy prompt', exact: true })).toBeVisible();
  await expect(page.locator('.generated-by-line')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('media followups contain visible metadata without encryption material', async ({ page }) => {
  test.setTimeout(120_000);
  const sentinel = 'private-media-crypto-sentinel';
  const props = encodeURIComponent(JSON.stringify({
    aes_key: sentinel, aesKey: sentinel, aes_nonce: sentinel, aesNonce: sentinel,
    files: { original: { aes_nonce: sentinel, encryption: sentinel } },
  }));
  await page.route('**/v1/apps/workspace/interpret', route => route.fulfill({ status: 503, json: { detail: 'isolated component request' } }));
  for (const component of fullscreens) {
    await page.goto(`/dev/preview/embeds/${component}?chrome=0&width=700&props=${props}`);
    await waitForComponentPreview(page);
    await page.getByTestId('apps-request-textarea').fill('Describe this result');
    const pending = page.waitForRequest('**/v1/apps/workspace/interpret');
    await page.getByTestId('apps-request-submit').click();
    const request = await pending;
    const body = request.postDataJSON();
    expect(body.context.result).toBeTruthy();
    expect(JSON.stringify(body.context.result)).not.toContain(sentinel);
    expect(body.context.result).not.toHaveProperty('files');
    expect(body.context.result).not.toHaveProperty('aes_key');
    expect(body.context.result).not.toHaveProperty('aesKey');
    expect(body.context.result).not.toHaveProperty('aes_nonce');
    expect(body.context.result).not.toHaveProperty('aesNonce');
  }
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('YouTube PiP preserves the production iframe and playing media document across fullscreen restore (provider document fixture)', async ({ page }, testInfo) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1100, height: 900 });
  // Only the remote provider document is isolated. Real production fullscreen,
  // VideoIframe and videoIframeStore own playback, PiP and remount transitions.
  // A real media element plays checked-in MP4 bytes, so time and document/node
  // identity assertions detect an iframe reload instead of asserting fake state.
  // Keep provider media HTTPS and same-origin with its intercepted document.
  // An HTTPS provider frame loading CI's HTTP localhost assets is blocked by
  // mixed-content/local-network rules before the real media can start.
  const mediaFixture = await page.request.get('/store-examples/video-generate-1.mp4');
  expect(mediaFixture.ok()).toBeTruthy();
  const mediaBytes = await mediaFixture.body();
  const mediaUrl = 'https://www.youtube-nocookie.com/fixture-media/video.mp4';
  await page.route(mediaUrl, route => route.fulfill({ contentType: 'video/mp4', body: mediaBytes }));
  let providerDocumentLoads = 0;
  await page.route('https://www.youtube-nocookie.com/embed/**', route => {
    providerDocumentLoads += 1;
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><title>Isolated provider media document</title></head><body style="margin:0"><video aria-label="Provider fixture video" controls autoplay muted loop playsinline style="width:100vw;height:100vh;object-fit:contain" src="${mediaUrl}"></video></body></html>` });
  });
  await page.goto('/dev/preview/embeds/videos/VideoPlaybackHostFixture?chrome=0&width=1100');
  await waitForComponentPreview(page);
  await page.locator('.play-button-overlay').click();
  const iframe = page.locator('iframe.video-iframe');
  await expect(iframe).toBeVisible();
  const originalIframe = await iframe.elementHandle();
  expect(originalIframe).not.toBeNull();
  // HTML video has no implicit ARIA role; its explicit accessible label is stable.
  const media = page.frameLocator('iframe.video-iframe').locator('video[aria-label="Provider fixture video"]');
  await expect(media).toHaveAttribute('controls', '');
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2);
  if (await media.evaluate((element: HTMLVideoElement) => element.paused)) {
    await media.focus();
    await media.press('Space');
  }
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0.25);
  const originalPlayer = await media.elementHandle();
  expect(originalPlayer).not.toBeNull();
  const beforePip = await media.evaluate((element: HTMLVideoElement) => element.currentTime);
  await page.locator('.pip-button').click();
  await expect(page.getByTestId('result-embed-content')).toHaveCount(0);
  await expect(page.getByTestId('video-playback-player-host')).toHaveClass(/pip/);
  await expect(page.getByRole('button', { name: 'Open fullscreen video' })).toBeVisible();
  expect(await iframe.evaluate((current, original) => current === original, originalIframe)).toBe(true);
  expect(await media.evaluate((current, original) => current === original, originalPlayer)).toBe(true);
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(beforePip);
  expect(await media.evaluate((element: HTMLVideoElement) => element.paused)).toBe(false);
  await testInfo.attach('VideoPlaybackHostFixture-pip-playing', { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });

  const beforeRestore = await media.evaluate((element: HTMLVideoElement) => element.currentTime);
  await page.getByRole('button', { name: 'Open fullscreen video' }).click();
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  await expect(page.getByTestId('result-embed-content')).toBeVisible();
  await expect(page.getByTestId('video-playback-player-host')).not.toHaveClass(/pip/);
  await expect(page.locator('.video-playing-spacer')).toBeVisible();
  await expect(page.locator('.pip-button')).toBeVisible();
  await expect(page.getByTestId('apps-request-composer')).toBeVisible();
  await expect.poll(async () => {
    const playerBounds = await iframe.boundingBox();
    const slotBounds = await page.locator('.video-playing-spacer').boundingBox();
    return !!playerBounds && !!slotBounds
      && Math.abs(playerBounds.x - slotBounds.x) < 1
      && Math.abs(playerBounds.y - slotBounds.y) < 1
      && Math.abs(playerBounds.width - slotBounds.width) < 1;
  }, { message: 'restored persistent player must align with the final fullscreen slot' }).toBe(true);
  const restoredPlayerBounds = await iframe.boundingBox();
  const restoredComposerBounds = await page.getByTestId('apps-request-composer').boundingBox();
  expect(restoredPlayerBounds!.y + restoredPlayerBounds!.height).toBeLessThanOrEqual(restoredComposerBounds!.y - 8);
  expect(await iframe.evaluate((current, original) => current === original, originalIframe)).toBe(true);
  expect(await media.evaluate((current, original) => current === original, originalPlayer)).toBe(true);
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(beforeRestore);
  expect(providerDocumentLoads).toBe(1);
  await expect(media).toHaveAttribute('controls', '');
  await media.focus();
  await media.press('Space');
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  await media.press('Space');
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.paused)).toBe(false);
  await testInfo.attach('VideoPlaybackHostFixture-restored-playing', { body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }), contentType: 'image/png' });
  await originalPlayer?.dispose();
  await originalIframe?.dispose();
});
