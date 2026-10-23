// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

test.use({ hasTouch: true });

async function activations(page: import('@playwright/test').Page) {
  return page.evaluate(() => (window as unknown as { timelineActivations: string[] }).timelineActivations);
}

// contract-test: direct surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.accessible-layout
test('a bookmark outside the dense overview sample stays yellow and can be selected and toggled without jumping', async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/dev/preview/ChatMessageTimelineUpdatingPreviewHarness?variant=bookmarks&theme=dark&background=%23171717&width=1280&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  const mark = rail.locator('.timeline-mark.bookmarked[data-message-id="timeline-user-4711"]');
  await expect(mark).toHaveCount(1);
  const box = (await mark.boundingBox())!;
  const railBox = (await rail.boundingBox())!;
  await page.mouse.move(railBox.x + railBox.width / 2, box.y + box.height / 2);
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 4711:');
  const button = page.getByTestId('timeline-preview').getByTestId('message-bookmark-button');
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  expect(await button.locator('svg').evaluate(node => getComputedStyle(node).filter)).toContain('drop-shadow');
  const colors = await Promise.all([mark.evaluate(node => getComputedStyle(node).backgroundColor), button.evaluate(node => getComputedStyle(node).color)]);
  expect(colors[0]).toBe(colors[1]);
  expect(await rail.locator('.timeline-mark').count()).toBeLessThanOrEqual(50);
  await page.screenshot({ path: info.outputPath('timeline-desktop-bookmark.png') });
  await button.click();
  await expect(button).toHaveAttribute('aria-pressed', 'false');
  await expect(rail.locator('.timeline-mark.bookmarked')).toHaveCount(0);
  expect(await activations(page)).toEqual([]);
  await button.click();
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  await expect(mark).toHaveCount(1);
  expect(await activations(page)).toEqual([]);
  await button.press('Escape');
  await expect(page.getByTestId('timeline-preview')).toHaveCount(0);
  await expect(rail).toBeFocused();
  expect(await activations(page)).toEqual([]);
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.accessible-layout
test('phone bookmark save failure preserves yellow state and the same touch control retries', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/ChatMessageTimelineUpdatingPreviewHarness?variant=bookmarkFailure&theme=dark&background=%23171717&width=390&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  const mark = rail.locator('.timeline-mark.bookmarked[data-message-id="timeline-user-4711"]');
  const box = (await mark.boundingBox())!;
  const railBox = (await rail.boundingBox())!;
  await page.mouse.move(railBox.x + railBox.width / 2, box.y + box.height / 2);
  const preview = page.getByTestId('timeline-preview');
  const button = preview.getByTestId('message-bookmark-button');
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  const target = (await button.boundingBox())!;
  expect(target.width).toBeGreaterThanOrEqual(44);
  expect(target.height).toBeGreaterThanOrEqual(44);
  await button.tap();
  await expect(button).toHaveAttribute('data-save-failed', 'true');
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  await expect(mark).toHaveCount(1);
  expect((await preview.boundingBox())!.x + (await preview.boundingBox())!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('timeline-phone-bookmark-retry.png') });
  await button.tap();
  await expect(button).toHaveAttribute('data-save-failed', 'false');
  await expect(button).toHaveAttribute('aria-pressed', 'false');
  expect(await activations(page)).toEqual([]);
});
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as unknown as { timelineActivations: string[] };
    state.timelineActivations = [];
    window.addEventListener('timeline-preview-activated', event => state.timelineActivations.push((event as CustomEvent).detail));
  });
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.preview-and-activate,chat-message-timeline.compression-history,chat-message-timeline.accessible-layout
test('desktop hover previews both messages without jumping, then click activates the selected exchange', async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/dev/preview/ChatMessageTimeline?theme=light&background=%23dbeafe&width=1280&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  const box = (await rail.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height * 0.1);
  const preview = page.getByTestId('timeline-preview');
  await expect(preview.getByTestId('timeline-user-preview')).toContainText('Question 2');
  await expect(preview.getByTestId('timeline-response-preview')).toContainText('answer to question 2');
  await expect(page.getByTestId('timeline-before-compression')).toContainText('Before compression');
  expect(await activations(page)).toEqual([]);
  expect(await rail.locator('.timeline-mark.selected').evaluate(node => node.getBoundingClientRect().width))
    .toBeGreaterThan(await rail.locator('.timeline-mark').first().evaluate(node => node.getBoundingClientRect().width));
  expect(await page.getByTestId('timeline-user-preview').evaluate(node => {
    const style = getComputedStyle(node);
    return node.clientHeight <= parseFloat(style.lineHeight) + 1 && style.textOverflow === 'ellipsis';
  })).toBe(true);
  expect(await page.getByTestId('timeline-response-preview').evaluate(node =>
    node.clientHeight <= parseFloat(getComputedStyle(node).lineHeight) * 3 + 1)).toBe(true);
  await expect(preview.locator('strong')).toHaveCount(0);
  expect((await preview.boundingBox())!.height).toBeLessThan(170);
  await page.screenshot({ path: info.outputPath('timeline-desktop-hover.png') });
  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.1);
  await expect.poll(() => activations(page)).toEqual(['timeline-user-2']);
  await expect(preview).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.accessible-layout,chat-message-timeline.preview-and-activate
// contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading
test('keyboard reaches individual entries in a ten-thousand-exchange rail with reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/dev/preview/ChatMessageTimeline?variant=dense&theme=light&width=1024&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  await expect(rail).toHaveAttribute('data-count', '10000');
  await expect(rail.locator('.timeline-mark.current')).toHaveCount(1);
  expect(await rail.locator('.timeline-mark').count()).toBeLessThanOrEqual(50);
  await rail.focus();
  await rail.press('Home');
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 0:');
  await rail.press('ArrowDown');
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 1:');
  await rail.press('End');
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 9999:');
  await rail.press('Escape');
  await expect(page.getByTestId('timeline-preview')).toHaveCount(0);
  expect(await activations(page)).toEqual([]);
  await rail.press('Home');
  await rail.press('Enter');
  await expect.poll(() => activations(page)).toEqual(['timeline-user-0']);
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.touch-scrubbing,chat-message-timeline.accessible-layout,chat-message-timeline.compression-history
test('phone hold-and-slide keeps the preview clear of the finger and commits once on release; cancellation does not jump', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/ChatMessageTimeline?theme=dark&background=%23171717&width=390&chrome=0');
  await waitForComponentPreview(page);
  const box = (await page.getByTestId('timeline-rail').boundingBox())!;
  const x = box.x + box.width / 2;
  const session = await page.context().newCDPSession(page);
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: box.y + box.height * 0.8, id: 1 }] });
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  expect(await activations(page)).toEqual([]);
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: box.y + box.height * 0.2, id: 1 }] });
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 5:');
  const preview = (await page.getByTestId('timeline-preview').boundingBox())!;
  expect(preview.x).toBeGreaterThan(x + 40);
  expect(preview.x + preview.width).toBeLessThanOrEqual(390);
  expect(preview.y).toBeGreaterThanOrEqual(0);
  expect(preview.y + preview.height).toBeLessThanOrEqual(844);
  await expect(page.getByTestId('timeline-before-compression')).toBeVisible();
  await page.screenshot({ path: info.outputPath('timeline-phone-scrubbing.png') });
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => activations(page)).toEqual(['timeline-user-5']);
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: box.y + box.height * 0.5, id: 2 }] });
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  await session.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
  await expect(page.getByTestId('timeline-preview')).toHaveCount(0);
  expect(await activations(page)).toEqual(['timeline-user-5']);
  await page.touchscreen.tap(x, box.y + box.height * 0.5);
  await expect.poll(() => activations(page)).toEqual(['timeline-user-5', 'timeline-user-12']);
  await session.detach();
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.preview-and-activate
// contract-test: supporting surface=gui.web assertions=chat-message-timeline.full-history-loading
test('empty, pending and unavailable previews remain truthful and offer retry', async ({ page }) => {
  await page.goto('/dev/preview/ChatMessageTimeline?variant=empty&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('timeline-rail')).toHaveCount(0);
  for (const variant of ['pending', 'unavailable']) {
    await page.goto(`/dev/preview/ChatMessageTimeline?variant=${variant}&theme=light&width=680&chrome=0`);
    await waitForComponentPreview(page);
    await page.getByTestId('timeline-rail').focus();
    if (variant === 'pending') await expect(page.getByTestId('timeline-response-preview')).toHaveText('Response pending');
    else {
      await expect(page.getByTestId('timeline-preview')).toContainText('This section couldn’t be loaded.');
      await page.getByTestId('timeline-retry').click();
      await expect(page.getByTestId('timeline-preview')).toContainText('This section couldn’t be loaded.');
    }
  }
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.touch-scrubbing,chat-message-timeline.preview-and-activate,chat-message-timeline.access-and-lifecycle
test('catalogue growth preserves the previewed exchange through touch release and mouse click', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/ChatMessageTimelineUpdatingPreviewHarness?theme=light&width=390&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  const box = (await rail.boundingBox())!;
  const x = box.x + box.width / 2;
  const session = await page.context().newCDPSession(page);
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: box.y + box.height * 0.2, id: 1 }] });
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 5:');
  await page.evaluate(() => window.dispatchEvent(new Event('preview:timeline-prepend')));
  await expect(rail).toHaveAttribute('data-count', '48');
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 5:');
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => activations(page)).toEqual(['timeline-user-5']);
  await session.detach();

  await page.mouse.move(x, box.y + box.height * 0.4);
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  const selected = await page.getByTestId('timeline-preview').getAttribute('data-message-id');
  await page.evaluate(() => window.dispatchEvent(new Event('preview:timeline-prepend')));
  await expect(rail).toHaveAttribute('data-count', '72');
  await page.mouse.down();
  await page.mouse.up();
  await expect.poll(() => activations(page)).toEqual(['timeline-user-5', selected]);
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.access-and-lifecycle
test('preview text follows the chat PII visibility setting', async ({ page }) => {
  for (const variant of ['piiHidden', 'piiRevealed']) {
    await page.goto(`/dev/preview/ChatMessageTimeline?variant=${variant}&theme=light&width=680&chrome=0`);
    await waitForComponentPreview(page);
    await page.getByTestId('timeline-rail').focus();
    const preview = page.getByTestId('timeline-user-preview');
    await expect(preview).toContainText(variant === 'piiHidden' ? '[EMAIL_1_com]' : 'alex@example.test');
    if (variant === 'piiHidden') await expect(preview).not.toContainText('alex@example.test');
  }
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.compression-history,chat-message-timeline.preview-and-activate
test('real ChatHistory opens a non-rendered compressed exchange and returns to its latest virtualized window', async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/dev/preview/ChatHistory?variant=timelineHistory&theme=light&width=1024&chrome=0');
  await waitForComponentPreview(page);
  const first = page.locator('[data-testid="message-user"][data-message-id="timeline-history-0"]');
  await expect(first).toHaveCount(0);
  const rail = page.getByTestId('timeline-rail');
  await expect(rail).toHaveAttribute('data-count', '1000');
  expect((await rail.boundingBox())!.x).toBeCloseTo((await page.getByTestId('chat-history-container').boundingBox())!.x, 1);
  await rail.focus();
  await rail.press('Home');
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 0:');
  await expect(page.getByTestId('timeline-response-preview')).toContainText('Response 0:');
  await rail.press('Enter');
  await expect(first).toBeVisible();
  await expect(first).toContainText('Question 0:');
  await expect(first).toHaveAttribute('data-forgotten', 'true');
  expect(await page.locator('.message-wrapper').count()).toBeLessThan(180);
  const geometry = await first.evaluate(node => {
    const viewport = node.closest('[data-testid="chat-history-container"]')!.getBoundingClientRect();
    const row = node.getBoundingClientRect();
    return { visible: row.top >= viewport.top && row.top < viewport.bottom };
  });
  expect(geometry.visible).toBe(true);
  const questionBookmark = first.getByTestId('message-bookmark-button');
  await questionBookmark.click();
  await expect(questionBookmark).toHaveAttribute('aria-pressed', 'true');
  const yellow = rail.locator('.timeline-mark.bookmarked[data-message-id="timeline-history-0"]');
  await expect(yellow).toHaveCount(1);
  const replyBookmark = page.locator('.message-wrapper[data-message-id="timeline-history-1"]').getByTestId('message-bookmark-button');
  await replyBookmark.click();
  await questionBookmark.click();
  await expect(questionBookmark).toHaveAttribute('aria-pressed', 'false');
  await expect(yellow).toHaveCount(1); // Reply alone keeps its question's mark yellow.
  await replyBookmark.click();
  await expect(rail.locator('.timeline-mark.bookmarked')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('timeline-history-compressed-jump.png') });
  await page.getByTestId('timeline-latest').click();
  await expect(page.getByTestId('timeline-latest')).toHaveCount(0);
  await expect(page.locator('[data-message-id="timeline-history-1999"]')).toBeVisible();
  await expect(rail).toHaveAttribute('aria-valuenow', '1000');
  await expect(first).toHaveCount(0);
});
