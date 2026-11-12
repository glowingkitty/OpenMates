// proof-video: not_required reason=visual_smoke_not_needed
import type { Locator, Page, TestInfo } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
/*
 * Generated video result card (VideoGenerateEmbedPreview) and the videos.generate
 * request card (GeneratedMediaGroupEmbedPreview): a thumbnail with a play button
 * instead of a player, the maker named once, text kept in its own column, the
 * running step, and running changes of an earlier video.
 */
const PREVIEW = '/dev/preview/embeds/videos/VideoGenerateEmbedPreview?chrome=0&theme=light&background=%23dbeafe';
const PARENT = '/dev/preview/embeds/GeneratedMediaGroupEmbedPreview?chrome=0&theme=light&background=%23dbeafe';
const FULLSCREEN = '/dev/preview/embeds/videos/VideoGenerateEmbedFullscreen?chrome=0&theme=light&background=%23dbeafe';

async function open(page: Page, variant: string, width = 1100, base = PREVIEW): Promise<Locator> {
  await page.setViewportSize({ width: Math.max(width, 320), height: 900 });
  await page.goto(`${base}&variant=${variant}&width=${width}`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('embed-preview');
  await expect(card).toBeVisible();
  return card;
}

async function attach(testInfo: TestInfo, page: Page, name: string) {
  await testInfo.attach(name, {
    body: await page.getByTestId('component-preview-canvas').screenshot({ animations: 'disabled' }),
    contentType: 'image/png',
  });
}

// Several preview variants are opened per test; each is its own page load.
test.describe.configure({ timeout: 150_000 });

type Box = { x: number; y: number; width: number; height: number };
const intersects = (a: Box, b: Box) =>
  a.x < b.x + b.width - 0.5 && b.x < a.x + a.width - 0.5 && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;

/** The loaded image is a real picture, not an empty or black frame. */
async function expectNonBlackImage(image: Locator) {
  await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  const brightness = await image.evaluate((el: HTMLImageElement) => {
    const canvas = document.createElement('canvas');
    canvas.width = 32; canvas.height = 18;
    const context = canvas.getContext('2d')!;
    context.drawImage(el, 0, 0, 32, 18);
    const data = context.getImageData(0, 0, 32, 18).data;
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
    return sum / (data.length / 4);
  });
  expect(brightness).toBeGreaterThan(30);
}

for (const width of [1100, 390]) {
  // contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
  test(`finished video cards show a thumbnail with a play button and name the maker once at ${width}px`, async ({ page }, testInfo) => {
    for (const [variant, maker, rawId] of [
      ['composed', 'GPT-6.1 Sol', 'gpt-6.1-sol'],
      ['generative', 'Gemini Omni 1.2 Flash', 'gemini-omni-1.2-flash'],
    ] as const) {
      const card = await open(page, variant, width);
      await expect(card.locator('video')).toHaveCount(0);
      const thumbnail = card.getByTestId('video-generate-thumbnail');
      await expect(thumbnail).toBeVisible();
      await expect(thumbnail).toHaveCSS('object-fit', 'cover');
      await expectNonBlackImage(thumbnail);
      const play = card.getByTestId('video-generate-play');
      await expect(play).toBeVisible();
      // The play button sits centered over the thumbnail.
      const media = (await card.getByTestId('result-card-media').boundingBox())!;
      const playBox = (await play.boundingBox())!;
      expect(Math.abs(playBox.x + playBox.width / 2 - (media.x + media.width / 2))).toBeLessThan(2);
      expect(Math.abs(playBox.y + playBox.height / 2 - (media.y + media.height / 2))).toBeLessThan(2);

      await expect(card.getByText(`Created by ${maker}`, { exact: true })).toHaveCount(1);
      const copy = await card.evaluate((el) => (el as HTMLElement).innerText);
      expect(copy.split(maker).length - 1, 'the maker is named exactly once').toBe(1);
      expect(copy).not.toContain(rawId);
      await attach(testInfo, page, `${variant}-${width}px`);

      await expect(card.getByTestId('video-generate-open')).toHaveAccessibleName('Play video');
      // The card is one button: a press on the play button (the card's centre of the media) opens the video.
      const playBoxNow = (await play.boundingBox())!;
      await page.mouse.click(playBoxNow.x + playBoxNow.width / 2, playBoxNow.y + playBoxNow.height / 2);
      await expect(page.locator('body')).toHaveAttribute('data-video-generate-fullscreen-opens', '1');
      const thumbnailBox = (await thumbnail.boundingBox())!;
      await page.mouse.click(thumbnailBox.x + 12, thumbnailBox.y + thumbnailBox.height - 12);
      await expect(page.locator('body')).toHaveAttribute('data-video-generate-fullscreen-opens', '2');
    }

    // An older video without a stored thumbnail: neutral surface, still a play button.
    const card = await open(page, 'noThumbnail', width);
    await expect(card.locator('video')).toHaveCount(0);
    await expect(card.getByTestId('video-generate-placeholder')).toBeVisible();
    await expect(card.getByTestId('video-generate-play')).toBeVisible();
    await attach(testInfo, page, `no-thumbnail-${width}px`);
  });
}

for (const width of [1100, 700, 390]) {
  // contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
  test(`a long title stays inside its text column at ${width}px`, async ({ page }, testInfo) => {
    const card = await open(page, 'longTitle', width);
    const media = (await card.getByTestId('result-card-media').boundingBox())!;
    for (const part of [card.getByTestId('result-card-title'), card.getByText('Created by GPT-6.1 Sol', { exact: true })]) {
      await expect(part).toBeVisible();
      const box = (await part.boundingBox())!;
      expect(intersects(box, media), 'text must not run over the thumbnail').toBe(false);
    }
    const title = await card.getByTestId('result-card-title').evaluate((el) => {
      const style = getComputedStyle(el);
      return { clamp: style.webkitLineClamp, overflow: el.scrollWidth > el.clientWidth + 1, height: el.getBoundingClientRect().height, line: parseFloat(style.lineHeight) };
    });
    expect(title.clamp).toBe('2');
    expect(title.overflow).toBe(false);
    expect(title.height).toBeLessThanOrEqual(title.line * 2 + 1);
    const cardBox = (await card.boundingBox())!;
    expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(width + 1);
    await attach(testInfo, page, `long-title-${width}px`);
  });
}

for (const [variant, label] of [
  ['processingDeciding', 'Deciding how to make the video…'],
  ['processingWriting', 'Writing the composition…'],
  ['processingRendering', 'Rendering the video…'],
  ['processingCorrecting', 'Fixing a render problem (round 2)…'],
  ['processingGenerating', 'Generating the clip…'],
] as const) {
  // contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
  test(`a running request names its current step: ${variant}`, async ({ page }, testInfo) => {
    for (const width of [1100, 390]) {
      const card = await open(page, variant, width);
      await expect(card.getByTestId('video-generate-stage')).toHaveText(label);
      await expect(card.getByTestId('video-generate-processing')).toBeVisible();
      await expect(card.getByTestId('video-generate-play')).toHaveCount(0);
      await expect(card.locator('video')).toHaveCount(0);
      await expect(card).not.toContainText('Generating video');
      await attach(testInfo, page, `${variant}-${width}px`);
    }
  });
}

// contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
test('a running change shows the changed video, the kind of change and the instruction', async ({ page }, testInfo) => {
  for (const [variant, label, instruction, resolved] of [
    ['changeEdit', 'Editing video', 'Make the headline of the budget scene bigger and use a warmer color', true],
    ['changeExtendEnd', 'Extending video at the end', 'Continue with the sun rising over the mountains', true],
    ['changeUnresolved', 'Editing video', 'Remove the closing line', false],
  ] as const) {
    for (const width of [1100, 390]) {
      const card = await open(page, variant, width);
      await expect(card.getByText(label, { exact: true })).toBeVisible();
      await expect(card.getByTestId('result-card-title')).toHaveText(instruction);
      await expect(card.getByTestId('video-generate-source')).toBeVisible();
      await expect(card.getByTestId('video-generate-processing')).toBeVisible();
      await expect(card.getByTestId('video-generate-play')).toHaveCount(0);
      const source = card.getByTestId('video-generate-source-thumbnail');
      if (resolved) {
        await expect(source).toBeVisible();
        await expectNonBlackImage(source);
        await expect(source).toHaveCSS('opacity', '0.45');
      } else {
        await expect(source).toHaveCount(0);
      }
      await attach(testInfo, page, `${variant}-${width}px`);
    }
  }
});

// contract-test: supporting surface=gui.web assertions=videos-generate.progress.shown-while-running
test('the videos.generate request card shows the step and a running change', async ({ page }, testInfo) => {
  let card = await open(page, 'videoCorrecting', 700, PARENT);
  await expect(card.getByTestId('image-generate-request-model')).toHaveText('Fixing a render problem (round 2)…');
  await attach(testInfo, page, 'request-card-correcting');
  card = await open(page, 'videoChange', 700, PARENT);
  await expect(card.getByTestId('video-generate-request-change')).toHaveText('Editing video');
  await expect(card.getByTestId('image-generate-request-model')).toHaveText('Writing the composition…');
  await expect(card.getByTestId('image-generate-request-prompt')).toHaveText('Make the headline of the budget scene bigger and use a warmer color');
  await expectNonBlackImage(card.getByTestId('video-generate-source-thumbnail'));
  await attach(testInfo, page, 'request-card-change');
});

// contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
test('a failed request shows its error in every card size', async ({ page }, testInfo) => {
  for (const width of [1100, 390]) {
    const card = await open(page, 'error', width);
    await expect(card.getByTestId('video-generate-error')).toHaveText('Video generation failed');
    await expect(card.getByTestId('video-generate-play')).toHaveCount(0);
    await attach(testInfo, page, `error-${width}px`);
  }
});

// contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
test('the fullscreen opened from the play button starts playing once the video has loaded', async ({ page }, testInfo) => {
  // Like the chat: the click comes first, the video bytes (decrypted there) arrive later.
  let release!: () => void;
  const clicked = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/store-examples/video-generate-1.mp4', async (route) => { await clicked; await route.continue(); });
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto(`${FULLSCREEN}&variant=composed&width=1100`);
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  // Any click gives the page the user activation the chat has after pressing the play button.
  await page.getByTestId('result-facts').click({ position: { x: 2, y: 2 }, force: true });
  release();
  const video = page.getByTestId('video-generate-fullscreen-video');
  await expect(video).toHaveAttribute('autoplay', '');
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => !el.paused && el.currentTime > 0.2), { timeout: 20_000 }).toBe(true);
  await attach(testInfo, page, 'fullscreen-playing');
});

for (const variant of ['composed', 'longTitle']) {
  // contract-test: supporting surface=gui.web assertions=videos-generate.result.video-with-timeline
  test(`the wide chat card keeps the ${variant} text in its left column beside the thumbnail`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto(`${PREVIEW}&variant=${variant}&width=1100&context=chat`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('embed-preview');
    await expect(card).toBeVisible();
    const cardBox = (await card.boundingBox())!;
    expect(cardBox.width, 'the chat context renders the wide card').toBeGreaterThan(401);
    const media = (await card.getByTestId('result-card-media').boundingBox())!;
    // Text on the left third, the thumbnail with its play button on the right.
    expect(media.x).toBeGreaterThan(cardBox.x + cardBox.width * 0.3);
    for (const part of [card.getByTestId('result-card-title'), card.getByText('Created by GPT-6.1 Sol', { exact: true })]) {
      await expect(part).toBeVisible();
      const box = (await part.boundingBox())!;
      expect(intersects(box, media), 'text must not run over the thumbnail').toBe(false);
      expect(box.x + box.width).toBeLessThanOrEqual(media.x + 0.5);
    }
    await expect(card.locator('video')).toHaveCount(0);
    await expect(card.getByTestId('video-generate-thumbnail')).toBeVisible();
    await expect(card.getByTestId('video-generate-play')).toBeVisible();
    await attach(testInfo, page, `wide-chat-card-${variant}`);
  });
}
