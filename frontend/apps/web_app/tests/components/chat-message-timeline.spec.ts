// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { scrollChatHistoryToStart } from '../helpers/chat-scroll';

test.use({ hasTouch: true });

async function activations(page: import('@playwright/test').Page) {
  return page.evaluate(() => (window as unknown as { timelineActivations: string[] }).timelineActivations);
}

// contract-test: direct surface=gui.web assertions=chat-message-timeline.bookmarks,chat-message-timeline.accessible-layout
test('a bookmark in a dense scrollable stack stays yellow and can be selected and toggled without jumping', async ({ page }, info) => {
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

test.describe('desktop mouse preview', () => {
  test.use({ hasTouch: false });
// contract-test: direct surface=gui.web assertions=chat-message-timeline.preview-and-activate,chat-message-timeline.compression-history,chat-message-timeline.accessible-layout
test('desktop hover previews both messages without jumping, then click activates the selected exchange', async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/dev/preview/ChatMessageTimeline?theme=light&background=%23dbeafe&width=1280&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  const box = (await rail.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + 30);
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
  await expect(rail.locator('button')).toHaveCount(0);
  const markStyle = await rail.locator('.timeline-mark.selected').evaluate(node => ({ scale: getComputedStyle(node).scale, transform: getComputedStyle(node).transform }));
  expect(markStyle.transform).toBe('none');
  expect(['none', '1']).toContain(markStyle.scale);
  expect((await preview.boundingBox())!.height).toBeLessThan(170);
  await page.screenshot({ path: info.outputPath('timeline-desktop-hover.png') });
  await page.mouse.click(box.x + box.width / 2, box.y + 30);
  await expect.poll(() => activations(page)).toEqual(['timeline-user-2']);
  await expect(preview).toHaveCount(0);
});

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
  const beforeScroll = await rail.evaluate(node => node.scrollTop);
  await rail.hover(); await page.mouse.wheel(0, -240);
  await expect.poll(() => rail.evaluate(node => node.scrollTop)).toBeLessThan(beforeScroll);
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
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 4:');
  const preview = (await page.getByTestId('timeline-preview').boundingBox())!;
  expect(preview.x).toBeGreaterThan(x + 40);
  expect(preview.x + preview.width).toBeLessThanOrEqual(390);
  expect(preview.y).toBeGreaterThanOrEqual(0);
  expect(preview.y + preview.height).toBeLessThanOrEqual(844);
  await expect(page.getByTestId('timeline-before-compression')).toBeVisible();
  await page.screenshot({ path: info.outputPath('timeline-phone-scrubbing.png') });
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => activations(page)).toEqual(['timeline-user-4']);
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: box.y + box.height * 0.5, id: 2 }] });
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  await session.send('Input.dispatchTouchEvent', { type: 'touchCancel', touchPoints: [] });
  await expect(page.getByTestId('timeline-preview')).toHaveCount(0);
  expect(await activations(page)).toEqual(['timeline-user-4']);
  await page.touchscreen.tap(x, box.y + box.height * 0.5);
  await expect.poll(() => activations(page)).toEqual(['timeline-user-4', 'timeline-user-10']);
  await session.detach();
});

// contract-test: direct surface=gui.web assertions=chat-message-timeline.touch-scrubbing,chat-message-timeline.full-history-loading
test('held touch at the stack edge scrolls to individual offscreen marks and releases at the previewed identity', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/ChatMessageTimeline?variant=dense&theme=dark&width=390&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  await rail.focus(); await rail.press('Home'); await rail.press('Escape');
  const box = (await rail.boundingBox())!, x = box.x + box.width / 2;
  const session = await page.context().newCDPSession(page);
  await session.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: box.y + box.height / 2, id: 1 }] });
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: box.y + box.height - 1, id: 1 }] });
  await expect.poll(() => rail.evaluate(node => node.scrollTop)).toBeGreaterThan(240);
  // Freeze the edge scroll in the middle before comparing release to its preview.
  await session.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: box.y + box.height / 2, id: 1 }] });
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  const selected = await page.getByTestId('timeline-preview').getAttribute('data-message-id');
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => activations(page)).toEqual([selected]);
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
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 4:');
  await page.evaluate(() => window.dispatchEvent(new Event('preview:timeline-prepend')));
  await expect(rail).toHaveAttribute('data-count', '48');
  await expect(page.getByTestId('timeline-user-preview')).toContainText('Question 4:');
  await session.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect.poll(() => activations(page)).toEqual(['timeline-user-4']);
  await session.detach();

  await page.mouse.move(x, box.y + box.height * 0.4);
  await expect(page.getByTestId('timeline-user-preview')).toBeVisible();
  const selected = await page.getByTestId('timeline-preview').getAttribute('data-message-id');
  await page.evaluate(() => window.dispatchEvent(new Event('preview:timeline-prepend')));
  await expect(rail).toHaveAttribute('data-count', '72');
  await page.mouse.down();
  await page.mouse.up();
  await expect.poll(() => activations(page)).toEqual(['timeline-user-4', selected]);
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

// contract-test: direct surface=gui.web assertions=chat-message-timeline.full-history-loading,chat-message-timeline.compression-history,chat-message-timeline.preview-and-activate,chat-message-timeline.accessible-layout,chat-message-timeline.bookmarks
test('real history positions compact marks beside the column and reliably opens non-rendered long exchanges', async ({ page }, info) => {
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/dev/preview/ChatHistoryTimelinePreviewHarness?theme=dark&background=%23171717&width=1920&chrome=0');
  await waitForComponentPreview(page);
  const rail = page.getByTestId('timeline-rail');
  const viewport = page.getByTestId('chat-history-container');
  await expect(rail).toHaveAttribute('data-count', '1000');
  expect((await rail.boundingBox())!.height).toBe(240);
  const lane = await page.getByTestId('chat-history-content').evaluate(node => {
    const box = node.getBoundingClientRect();
    return box.left + parseFloat(getComputedStyle(node).paddingLeft);
  });
  const box = (await rail.boundingBox())!;
  expect(box.x + box.width).toBeCloseTo(lane - 8, 0);
  expect(box.x).toBeGreaterThan((await viewport.boundingBox())!.x + 250);
  await expect(rail.locator('button')).toHaveCount(0);
  for (const index of [0, 8, 15]) {
    await rail.focus(); await rail.press('Home');
    for (let step = 0; step < index; step++) await rail.press('ArrowDown');
    await expect(page.getByTestId('timeline-user-preview')).toContainText(`Question ${index}:`);
    await rail.press('Enter');
    await expect(page.getByTestId('timeline-preview')).toHaveCount(0);
    const target = page.locator(`.message-wrapper[data-message-id="timeline-history-${index * 2}"]`);
    await expect(target).toBeVisible();
    await expect(target).toHaveAttribute('data-forgotten', 'true');
    await expect.poll(() => target.evaluate(node => node.getBoundingClientRect().top - node.closest('.chat-history-container')!.getBoundingClientRect().top)).toBeCloseTo(70, 0);
    expect(await page.locator('.message-wrapper').count()).toBeLessThan(180);
  }
  const user = page.locator('.message-wrapper.user');
  await expect(user.getByTestId('message-bookmark-button')).toHaveCount(0);
  const reply = page.locator('.message-wrapper.assistant[data-message-id="timeline-history-31"]').getByTestId('message-bookmark-button');
  await reply.click();
  await expect(reply).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: info.outputPath('timeline-wide-long-exact-jump.png') });
  await page.evaluate(() => window.dispatchEvent(new Event('preview:history-latest')));
  await expect(page.locator('[data-testid="message-assistant"][data-message-id="timeline-history-1999"]')).toBeVisible();
  await expect(rail).toHaveAttribute('aria-valuenow', '1000');
  await scrollChatHistoryToStart(page, info);
  await expect(page.locator('.chat-header-wrapper')).toBeInViewport({ ratio: 1 });
  await expect.poll(async () => {
    const banner = (await page.locator('.chat-header-wrapper').boundingBox())!;
    return (await rail.boundingBox())!.y >= banner.y + banner.height + 7;
  }).toBe(true);
  const banner = (await page.locator('.chat-header-wrapper').boundingBox())!;
  expect(banner.x).toBeLessThanOrEqual((await viewport.boundingBox())!.x + 1);
  await page.screenshot({ path: info.outputPath('timeline-wide-header-boundary.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await scrollChatHistoryToStart(page, info);
  await expect(rail).toBeVisible();
  await expect(page.locator('.chat-header-wrapper')).toBeInViewport({ ratio: 1 });
  expect((await rail.boundingBox())!.x - (await viewport.boundingBox())!.x).toBeLessThan(30);
  const headerPhone = (await page.locator('.chat-header-wrapper').boundingBox())!;
  expect((await rail.boundingBox())!.y).toBeGreaterThanOrEqual(headerPhone.y + headerPhone.height);
  await page.screenshot({ path: info.outputPath('timeline-phone-header-boundary.png') });
});

test.describe('compact follow-up and fixed assistant actions', () => {
  test.use({ hasTouch: false });
  // contract-test: direct surface=gui.web assertions=chat-message-timeline.visibility-and-spacing,chat-message-timeline.assistant-message-actions,chat-message-timeline.bookmarks,chat-message-timeline.accessible-layout
  test('the second answer fades in two marks and assistant icons use shared tooltips without expanding', async ({ page }, info) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto('/dev/preview/ChatHistoryTimelinePreviewHarness?variant=short&theme=dark&background=%23171717&width=1280&chrome=0');
    await waitForComponentPreview(page);
    await expect(page.getByTestId('timeline-rail')).toHaveCount(0);
    await expect(page.locator('.message-wrapper.user').getByTestId('message-bookmark-button')).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new Event('preview:history-follow-up')));
    const rail = page.getByTestId('timeline-rail');
    await expect(rail).toBeVisible();
    expect((await rail.boundingBox())!.height).toBe(24);
    expect(await rail.evaluate(node => getComputedStyle(node).animationName)).toMatch(/(?:^|-)timeline-appear$/);
    const marks = await rail.locator('.timeline-mark').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
    expect(marks[1] - marks[0]).toBe(12);
    const row = page.locator('.message-wrapper.assistant').last();
    await row.scrollIntoViewIfNeeded();
    const copy = row.locator('.copy-message-btn'), report = row.locator('.report-bad-answer-btn');
    const bookmark = row.getByTestId('message-bookmark-button');
    await expect(copy).toBeVisible(); await expect(report).toBeVisible(); await expect(bookmark).toBeVisible();
    const reportDirection = await report.locator('.icon_thumbsdown').evaluate(node => {
      const matrix = new DOMMatrixReadOnly(getComputedStyle(node).transform);
      return { x: matrix.a, y: matrix.d };
    });
    expect(reportDirection).toEqual({ x: -1, y: -1 });
    await expect(row.locator('.message-action-text')).toHaveCount(0);
    const initial = (await report.boundingBox())!;
    const gray = await bookmark.evaluate(node => getComputedStyle(node).color);
    expect(await bookmark.locator('svg').evaluate(node => getComputedStyle(node).fill)).toBe(gray);
    await bookmark.hover();
    expect(await bookmark.evaluate(node => getComputedStyle(node).color)).not.toBe(gray);
    await page.mouse.move(1200, 50);
    for (const button of [copy, bookmark, report]) {
      const before = (await button.boundingBox())!;
      await button.hover();
      await expect(page.locator('.tooltip')).toBeVisible();
      await expect(page.locator('.tooltip')).toContainText((await button.getAttribute('aria-label'))!);
      const after = (await button.boundingBox())!;
      expect(after.width).toBeCloseTo(before.width, 1);
      expect(after.height).toBeCloseTo(before.height, 1);
      expect((await report.boundingBox())!.x).toBeCloseTo(initial.x, 1);
      await page.mouse.move(1200, 50);
      await expect(page.locator('.tooltip')).toHaveCount(0);
    }
    await bookmark.click();
    await expect(bookmark).toHaveAttribute('aria-pressed', 'true');
    expect(await bookmark.evaluate(node => getComputedStyle(node).color)).not.toBe(gray);
    expect(await bookmark.locator('svg').evaluate(node => getComputedStyle(node).filter)).toContain('drop-shadow');
    await expect(rail.locator('.timeline-mark.bookmarked')).toHaveCount(1);
    await page.screenshot({ path: info.outputPath('timeline-two-marks-assistant-actions.png') });
  });
});
