// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';
import { scrollChatHistoryToStart, waitForStickyCallControlsReady } from '../helpers/chat-scroll';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const handsetSvg = readFile(resolve(process.cwd(), '../../packages/ui/static/icons/audiocall.svg'), 'utf8');

const preview = (width: number, theme: string, variant?: string) =>
  `/dev/preview/voicecall/VoiceCallHeaderActions?${new URLSearchParams({
    chrome: '0', theme, background: '#dbeafe', width: String(width), ...(variant ? { variant } : {}),
  })}`;

for (const { direction, withHeader } of [
  { direction: 'ltr', withHeader: false }, { direction: 'rtl', withHeader: false },
  { direction: 'ltr', withHeader: true }, { direction: 'rtl', withHeader: true },
]) {
  for (const transition of ['activeClose', 'idleHangup']) {
    // contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.fixed-binding
    test(`keeps the bound call and scrolled chat targets clear in ${direction} ${withHeader ? 'with' : 'without'} global Header after ${transition}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`/dev/preview/voicecall/ActiveChatCallHeaderPreview?${new URLSearchParams({
        chrome: '0', width: '390',
        ...(withHeader ? { variant: direction === 'rtl' ? 'headerRtl' : 'header' } : direction === 'rtl' ? { variant: 'rtl' } : {}),
      })}`);
      await waitForComponentPreview(page);
      const profile = page.getByTestId('profile-picture');
      const github = page.getByTestId('header-github-link');
      const call = page.getByTestId('voice-call-start');
      const close = page.getByTestId('chat-close-button');
      const bar = page.getByTestId('voice-call-bar');
      const history = page.getByTestId('chat-history-container');
      const banner = page.getByTestId('chat-header-banner');
      await expect(profile).toBeVisible();
      await expect(github).toBeVisible();
      await expect(close).toBeVisible();
      await expect(call).toHaveCount(0);
      await expect(bar).toBeVisible();
      await expect(bar).not.toHaveClass(/fixed/);
      if (withHeader) await expect(page.getByTestId('global-header')).toBeVisible();
      else await expect(page.getByTestId('global-header')).toHaveCount(0);
      await scrollChatHistoryToStart(page, testInfo);
      const [bannerBox, inlineBox] = await Promise.all([banner.boundingBox(), bar.boundingBox()]);
      expect(bannerBox).not.toBeNull();
      expect(inlineBox).not.toBeNull();
      expect(inlineBox!.y).toBeGreaterThanOrEqual(bannerBox!.y + bannerBox!.height - 1);
      await history.hover();
      await page.mouse.wheel(0, 500);
      await expect.poll(() => history.evaluate(element => element.scrollTop)).toBeGreaterThan(50);
      await expect(bar).toHaveClass(/fixed/);
      await waitForStickyCallControlsReady(page, testInfo);
      await expect(close).not.toBeVisible();
      const fixedClose = page.getByTestId('voice-call-close-chat');
      const more = page.getByTestId('voice-call-more');
      await expect(fixedClose).toBeVisible();
      await expect(more).toBeVisible();
      await expect(page.getByTestId('voice-call-video')).toBeVisible();
      await expect(page.getByTestId('voice-call-hangup')).toBeVisible();
      const [profileBox, githubBox, historyBox, barBox] = await Promise.all([
        profile.boundingBox(), github.boundingBox(), history.boundingBox(), bar.boundingBox(),
      ]);
      for (const box of [profileBox, githubBox, historyBox, barBox]) expect(box).not.toBeNull();
      expect(profileBox!.width).toBe(50);
      expect(profileBox!.height).toBe(50);
      expect(githubBox!.width).toBe(42);
      expect(githubBox!.height).toBe(42);
      expect(Math.abs(barBox!.y - historyBox!.y)).toBeLessThanOrEqual(1);
      if (withHeader) {
        const headerBox = await page.getByTestId('global-header').boundingBox();
        expect(headerBox).not.toBeNull();
        expect(barBox!.y).toBeGreaterThanOrEqual(headerBox!.y + headerBox!.height);
      }
      const scrollTop = page.getByRole('button', { name: 'Scroll to top', exact: true });
      await expect(scrollTop).toBeVisible();
      const scrollBox = await scrollTop.boundingBox();
      expect(scrollBox).not.toBeNull();
      expect(scrollBox!.y).toBeGreaterThanOrEqual(barBox!.y + barBox!.height);
      await more.click();
      const moreActions = page.getByTestId('voice-call-more-actions');
      await expect(moreActions).toBeVisible();
      await waitForComponentMotion(moreActions);
      await expect(moreActions.getByTestId('report-issue-button')).toBeVisible();
      await expect(moreActions.getByTestId('chat-share-button')).toBeVisible();
      await expect(moreActions).toHaveClass(/more-actions/);
      const [menuBox, menuHistoryBox] = await Promise.all([moreActions.boundingBox(), history.boundingBox()]);
      expect(menuBox).not.toBeNull();
      expect(menuHistoryBox).not.toBeNull();
      expect(menuBox!.x).toBeGreaterThanOrEqual(menuHistoryBox!.x);
      expect(menuBox!.x + menuBox!.width).toBeLessThanOrEqual(menuHistoryBox!.x + menuHistoryBox!.width - 8);
      await expect(moreActions.locator('.new-chat-button-wrapper').first()).toBeVisible();
      expect(await moreActions.getByTestId('chat-share-button').evaluate(element =>
        getComputedStyle(element).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
      await page.screenshot({ path: testInfo.outputPath(`mobile-call-more-open-${direction}-${withHeader ? 'header' : 'no-header'}-${transition}.png`) });
      await page.getByTestId('voice-call-mute').click();
      await expect(moreActions).toHaveCount(0);
      await more.click();
      await expect(moreActions).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('voice-call-more-actions')).toHaveCount(0);
      await expect(more).toBeFocused();
      await page.screenshot({ path: testInfo.outputPath(`mobile-call-sticky-${direction}-${withHeader ? 'header' : 'no-header'}.png`) });
      if (transition === 'activeClose') {
        await fixedClose.click();
        await expect(bar).toHaveCount(0);
        if (withHeader) await expect(page.getByTestId('voice-call-pill')).toBeVisible();
        return;
      }
      await page.getByTestId('voice-call-hangup').click();
      await expect(bar).toHaveCount(0);
      await expect(close).toBeVisible();
      await expect(call).toHaveCount(0);
      await history.hover();
      await page.mouse.wheel(0, 500);
      await expect(scrollTop).toBeVisible();
      const idleToolbar = await page.getByTestId('chat-top-actions').boundingBox();
      const idleScroll = await scrollTop.boundingBox();
      expect(idleToolbar).not.toBeNull();
      expect(idleScroll).not.toBeNull();
      expect(idleScroll!.y).toBeGreaterThanOrEqual(idleToolbar!.y + idleToolbar!.height);
      await close.click();
      await expect(close).toHaveCount(0);
    });
  }
}

for (const width of [320, 390, 1180]) {
  // contract-test: direct surface=gui.web assertions=video-call.chat.fixed-binding,video-call.lifecycle.recovery-and-billing
  test(`keeps the inline and sticky call below the real Header at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/dev/preview/voicecall/ActiveChatCallHeaderPreview?${new URLSearchParams({
      chrome: '0', width: String(width), variant: 'headerViewport',
    })}`);
    await waitForComponentPreview(page);
    const header = page.getByTestId('global-header');
    const history = page.getByTestId('chat-history-container');
    const banner = page.getByTestId('chat-header-banner');
    const bar = page.getByTestId('voice-call-bar');
    await expect(header).toBeVisible();
    await expect(bar).toBeVisible();
    await expect(page.getByTestId('voice-call-start')).toHaveCount(0);
    await scrollChatHistoryToStart(page, testInfo);
    const [bannerBox, inlineBox] = await Promise.all([banner.boundingBox(), bar.boundingBox()]);
    expect(bannerBox).not.toBeNull();
    expect(inlineBox).not.toBeNull();
    expect(inlineBox!.y).toBeGreaterThanOrEqual(bannerBox!.y + bannerBox!.height - 1);
    await page.screenshot({ path: testInfo.outputPath(`call-inline-${width}.png`) });
    await history.hover();
    await page.mouse.wheel(0, 500);
    await expect.poll(() => history.evaluate(element => element.scrollTop)).toBeGreaterThan(50);
    await expect(bar).toHaveClass(/fixed/);
    await waitForStickyCallControlsReady(page, testInfo);
    const [headerBox, historyBox, fixedBox] = await Promise.all([header.boundingBox(), history.boundingBox(), bar.boundingBox()]);
    expect(headerBox).not.toBeNull();
    expect(historyBox).not.toBeNull();
    expect(fixedBox).not.toBeNull();
    expect(fixedBox!.y).toBeGreaterThanOrEqual(headerBox!.y + headerBox!.height);
    expect(Math.abs(fixedBox!.y - historyBox!.y)).toBeLessThanOrEqual(1);
    await expect(page.getByTestId('voice-call-more')).toBeVisible();
    await expect(page.getByTestId('voice-call-close-chat')).toBeVisible();
    await waitForComponentMotion(page.getByTestId('voice-call-video'));
    const [moreBox, videoBox, centerBox] = await Promise.all([
      page.getByTestId('voice-call-more').boundingBox(),
      page.getByTestId('voice-call-video').boundingBox(),
      page.getByTestId('voice-call-mute').boundingBox(),
    ]);
    for (const box of [moreBox, videoBox, centerBox]) expect(box).not.toBeNull();
    expect(moreBox!.width).toBe(videoBox!.width);
    expect(moreBox!.height).toBe(videoBox!.height);
    expect(moreBox!.x + moreBox!.width).toBeLessThanOrEqual(videoBox!.x + 1);
    expect(videoBox!.x + videoBox!.width).toBeLessThanOrEqual(centerBox!.x + 1);
    const iconContrast = await page.getByTestId('voice-call-more').evaluate(element => {
      const icon = element.querySelector('.icon_more');
      if (!icon) throw new Error('More icon is missing');
      const bar = element.closest('[data-testid="voice-call-bar"]');
      const videoIcon = bar?.querySelector('[data-testid="voice-call-video"] .icon_video_call');
      if (!bar || !videoIcon) throw new Error('Adjacent call controls are missing');
      return {
        more: getComputedStyle(icon).backgroundColor,
        video: getComputedStyle(videoIcon).backgroundColor,
        contrast: getComputedStyle(bar).color,
        moreImage: getComputedStyle(icon).backgroundImage,
      };
    });
    expect(iconContrast.more).toBe(iconContrast.video);
    expect(iconContrast.more).toBe(iconContrast.contrast);
    expect(iconContrast.moreImage).toBe('none');
    await page.getByTestId('voice-call-more').click();
    await expect(page.getByTestId('voice-call-more-actions')).toBeVisible();
    await page.getByTestId('voice-call-video').click();
    await expect(page.getByTestId('voice-call-more-actions')).toHaveCount(0);
    await expect(page.getByText('Video calls are coming soon.')).toBeVisible();
    await page.getByTestId('notification-dismiss').click();
    await expect(page.getByTestId('notification')).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`call-sticky-${width}.png`) });
    await page.getByTestId('voice-call-close-chat').click();
    await expect(page.getByTestId('voice-call-start')).toHaveCount(0);
    await expect(page.getByTestId('daily-inspiration-label')).toBeVisible();
    const pill = page.getByTestId('voice-call-pill');
    await expect(pill).toBeVisible();
    if (width <= 390) {
      const switcher = page.getByTestId('header-workspace-switcher');
      const hamburger = page.getByTestId('sidebar-toggle');
      const github = page.getByTestId('header-github-link');
      const profile = page.getByTestId('profile-picture');
      await expect(switcher).toBeVisible();
      await expect(github).toBeVisible();
      await waitForComponentMotion(switcher);
      const [hamburgerBox, pillBox, switcherBox, githubBox, profileBox] = await Promise.all([
        hamburger.boundingBox(), pill.boundingBox(), switcher.boundingBox(), github.boundingBox(), profile.boundingBox(),
      ]);
      expect(hamburgerBox).not.toBeNull();
      expect(pillBox).not.toBeNull();
      expect(switcherBox).not.toBeNull();
      expect(githubBox).not.toBeNull();
      expect(profileBox).not.toBeNull();
      expect(hamburgerBox!.x + hamburgerBox!.width + 8).toBeLessThanOrEqual(pillBox!.x);
      expect(pillBox!.x + pillBox!.width + 8).toBeLessThanOrEqual(switcherBox!.x);
      expect(switcherBox!.x + switcherBox!.width + 8).toBeLessThanOrEqual(githubBox!.x);
      expect(githubBox!.x + githubBox!.width + 8).toBeLessThanOrEqual(profileBox!.x);
    }
    await page.screenshot({ path: testInfo.outputPath(`background-call-${width}.png`) });
    await page.getByTestId('voice-call-pill').click();
    await expect(bar).toBeVisible();
    await expect(page.getByTestId('voice-call-pill')).toHaveCount(0);
  });
}

// contract-test: direct surface=gui.web assertions=video-call.chat.fixed-binding,video-call.chat.typed-input
test('keeps call and chat-header controls clickable while the composer is focused', async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 844 });
  await page.goto('/dev/preview/voicecall/ActiveChatCallHeaderPreview?chrome=0&width=1180&variant=headerViewport');
  await waitForComponentPreview(page);
  const editor = page.getByTestId('message-editor');
  const chatSide = page.getByTestId('chat-side');
  await expect(page.getByTestId('voice-call-bar')).toBeVisible();
  await editor.click();
  await expect(page.getByTestId('input-dismiss-button')).toBeVisible();
  await expect(chatSide).not.toHaveAttribute('inert');
  await page.getByTestId('voice-call-mute').click();
  await editor.click();
  await expect(page.getByTestId('input-dismiss-button')).toBeVisible();
  await expect(chatSide).not.toHaveAttribute('inert');
  await page.getByTestId('chat-close-button').click();
  await expect(page.getByTestId('voice-call-pill')).toBeVisible();
});

// contract-test: direct surface=gui.web assertions=video-call.lifecycle.recovery-and-billing,video-call.chat.launch-and-provider
test('restores Start and allows a new call after hanging up in a private chat', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/voicecall/ActiveChatCallHeaderPreview?chrome=0&width=390&variant=privateCall');
  await waitForComponentPreview(page);
  const bar = page.getByTestId('voice-call-bar');
  const start = page.getByTestId('voice-call-start');
  await expect(page.locator('[data-action="message-input"][data-current-chat-id="preview-private-voice-call"]')).toBeVisible();
  await expect(bar).toBeVisible();
  await expect(start).toHaveCount(0);
  await page.getByTestId('voice-call-hangup').click();
  await expect(bar).toHaveCount(0);
  await expect(page.getByTestId('chat-top-actions')).toBeVisible();
  await expect(start).toBeVisible();
  await expect(start).toHaveAccessibleName('Start voice call');
  await page.getByTestId('message-editor').click();
  await expect(page.getByTestId('chat-side')).toHaveAttribute('inert');
  await page.getByTestId('input-dismiss-button').click();
  await expect(page.getByTestId('chat-side')).not.toHaveAttribute('inert');
  await start.click();
  await expect(bar).toBeVisible();
  await expect(start).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=video-call.chat.fixed-binding
test('keeps demo-mode Report suppression in the shared call More overlay', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/voicecall/ActiveChatCallHeaderPreview?chrome=0&width=390&variant=demoCall');
  await waitForComponentPreview(page);
  const previewViewport = page.locator('.call-header-preview');
  await expect(previewViewport).toHaveClass(/viewport-aligned/);
  expect((await previewViewport.boundingBox())?.y).toBe(0);
  const history = page.getByTestId('chat-history-container');
  const bar = page.getByTestId('voice-call-bar');
  const menu = page.getByTestId('voice-call-more-actions');
  await scrollChatHistoryToStart(page, testInfo);
  await history.hover();
  await page.mouse.wheel(0, 500);
  await expect(bar).toHaveClass(/fixed/);
  await waitForStickyCallControlsReady(page, testInfo);
  await page.getByTestId('voice-call-more').click();
  await expect(bar).toHaveClass(/fixed/);
  await expect(menu).toBeVisible();
  await waitForComponentMotion(menu);
  await expect(menu.getByTestId('report-issue-button')).toBeHidden();
  await expect(menu.getByTestId('chat-share-button')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('demo-call-more-open.png') });
});

test.describe('Call and Close header actions', () => {
  for (const { width, viewport, theme } of [
    { width: 680, viewport: 1280, theme: 'light' },
    { width: 330, viewport: 390, theme: 'dark' },
  ]) {
    // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.fixed-binding
    test(`keeps the handset left of Close and toggles the call at ${viewport}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width: viewport, height: 844 });
      await page.goto(preview(width, theme));
      await waitForComponentPreview(page);
      const call = page.getByTestId('voice-call-start');
      const close = page.getByTestId('chat-close-button');
      const handset = page.getByTestId('voice-call-handset');
      await expect(call).toHaveAccessibleName('Start voice call');
      await expect(call).toHaveAttribute('aria-pressed', 'false');
      // Vite can inline this small asset. Verify the SVG geometry actually used
      // by the computed mask against the real shared asset in either form.
      const icon = await handset.evaluate(async (element, expectedSvg) => {
        const mask = getComputedStyle(element).maskImage;
        const uri = /^url\(["']?(.*?)["']?\)$/.exec(mask)?.[1];
        if (!uri) throw new Error(`Missing handset mask: ${mask}`);
        let renderedSvg: string;
        if (uri.startsWith('data:')) {
          const comma = uri.indexOf(',');
          renderedSvg = uri.slice(0, comma).includes(';base64')
            ? atob(uri.slice(comma + 1)) : decodeURIComponent(uri.slice(comma + 1));
        } else {
          const response = await fetch(uri);
          if (!response.ok) throw new Error(`Handset SVG returned ${response.status}`);
          renderedSvg = await response.text();
        }
        const geometry = (source: string) => {
          const svg = new DOMParser().parseFromString(source, 'image/svg+xml');
          if (svg.querySelector('parsererror')) throw new Error('Invalid handset SVG');
          return [...svg.querySelectorAll('path')].map((path) =>
            (path.getAttribute('d')?.match(/[a-zA-Z]|[-+]?(?:\d*\.?\d+)(?:e[-+]?\d+)?/g) ?? [])
              .map((token) => Number.isNaN(Number(token)) ? token : String(Number(token))).join(' '));
        };
        return { actual: geometry(renderedSvg), expected: geometry(expectedSvg) };
      }, await handsetSvg);
      expect(icon.actual.length).toBeGreaterThan(0);
      expect(icon.actual).toEqual(icon.expected);
      await expect(handset).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
      const geometry = async () => {
        const a = (await call.boundingBox())!;
        const b = (await close.boundingBox())!;
        expect(a.width).toBeGreaterThanOrEqual(25);
        expect(a.height).toBeGreaterThanOrEqual(25);
        expect(Math.abs(a.y + a.height / 2 - b.y - b.height / 2)).toBeLessThan(1);
        expect(b.x - a.x - a.width).toBeGreaterThanOrEqual(0);
        expect(b.x - a.x - a.width).toBeLessThanOrEqual(24);
        expect(b.x + b.width).toBeLessThanOrEqual(viewport);
      };
      await geometry();
      await call.hover();
      await expect.poll(() => call.evaluate((element) => new DOMMatrix(getComputedStyle(element.parentElement!).transform).a)).toBeGreaterThan(1.05);
      await page.mouse.move(0, 0);
      // Navigate back from Close with the keyboard, so the browser
      // applies :focus-visible after the pointer-driven hover check.
      await close.focus();
      await page.keyboard.press('Shift+Tab');
      await expect(call).toBeFocused();
      const focus = await call.evaluate((element) => {
        const style = getComputedStyle(element);
        const token = style.getPropertyValue('--color-button-primary').trim();
        return { focusVisible: element.matches(':focus-visible'), focusToken: token,
          focusTokenValid: CSS.supports('color', token), outline: style.outline };
      });
      expect(focus).toMatchObject({ focusVisible: true, focusTokenValid: true });
      await expect(call, JSON.stringify(focus)).toHaveCSS('outline-style', 'solid');
      await expect(call).toHaveCSS('outline-width', '2px');
      await page.screenshot({ path: testInfo.outputPath(`idle-${viewport}.png`) });
      await page.keyboard.press('Enter');
      await expect(call).toHaveAttribute('data-call-state', 'connecting');
      await expect(call).toHaveAccessibleName('Hang up');
      await expect(call).toHaveAttribute('aria-pressed', 'true');
      // Check actual rotation and red fill, including the header-overlap treatment.
      await handset.locator('..').locator('..').evaluate((element) => element.setAttribute('data-header-overlay', ''));
      await expect(handset).toHaveCSS('filter', 'none');
      await expect.poll(() => handset.evaluate((element) => {
        const style = getComputedStyle(element);
        const matrix = new DOMMatrix(style.transform);
        const probe = document.createElement('span');
        probe.style.color = 'var(--color-error)'; element.append(probe);
        const red = getComputedStyle(probe).color; probe.remove();
        return { angle: Math.round(Math.atan2(matrix.b, matrix.a) * 180 / Math.PI), red: style.backgroundColor === red,
          redTokenValid: CSS.supports('color', style.getPropertyValue('--color-error').trim()) };
      })).toEqual({ angle: 135, red: true, redTokenValid: true });
      await geometry();
      await page.screenshot({ path: testInfo.outputPath(`connecting-${viewport}.png`) });
      await call.click();
      await expect(call).toHaveAttribute('data-call-state', 'ended');
      await expect(call).toHaveAccessibleName('Start voice call');
      await expect(handset).toHaveCSS('transform', 'matrix(1, 0, 0, 1, 0, 0)');
      await geometry();
    });
  }

  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.fixed-binding
  test('keeps a live call available and omits Close on a new chat', async ({ page }) => {
    await page.addInitScript(() => {
      window.addEventListener('voice-call-preview-close', () => document.documentElement.setAttribute('data-preview-closed', 'true'));
    });
    await page.goto(preview(330, 'light', 'live'));
    await waitForComponentPreview(page);
    const call = page.getByTestId('voice-call-start');
    await expect(call).toHaveAccessibleName('Hang up');
    await expect(page.getByTestId('chat-close-button')).toBeVisible();
    await call.click();
    await expect(call).toHaveAttribute('data-call-state', 'ended');
    await page.getByTestId('chat-close-button').click();
    await expect(page.locator('html')).toHaveAttribute('data-preview-closed', 'true');
    await page.goto(preview(330, 'light', 'newChat'));
    await waitForComponentPreview(page);
    await expect(call).toBeVisible();
    await expect(page.getByTestId('chat-close-button')).toHaveCount(0);
    await page.goto(preview(330, 'light', 'unavailable'));
    await waitForComponentPreview(page);
    await expect(call).toHaveCount(0);
    await expect(page.getByTestId('chat-close-button')).toBeVisible();
  });
});

for (const width of [390, 1180]) {
  for (const direction of ['ltr', 'rtl']) {
    // contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.call-strip-layout
    test(`keeps the idle close target at the chat edge at ${width}px ${direction}`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/dev/preview/voicecall/ActiveChatCallHeaderPreview?${new URLSearchParams({
        chrome: '0', width: String(width), variant: 'headerViewport', props: JSON.stringify({ direction }),
      })}`);
      await waitForComponentPreview(page);
      await page.getByTestId('voice-call-hangup').click();
      const close = page.getByTestId('chat-close-button');
      await expect(close).toBeVisible();
      await page.mouse.move(0, 0);
      await waitForComponentMotion(close);
      const toolbar = page.getByTestId('chat-top-actions');
      const geometry = await toolbar.evaluate((element, dir) => {
        const parent = (element as HTMLElement).offsetParent!;
        const parentBox = parent.getBoundingClientRect();
        const box = element.getBoundingClientRect();
        return dir === 'rtl' ? box.x - parentBox.x : parentBox.right - box.right;
      }, direction);
      expect(geometry).toBeCloseTo(width <= 730 ? 10 : 15, 0);
      await expect(close).toBeEnabled();
      await page.screenshot({ path: testInfo.outputPath(`chat-close-edge-${width}-${direction}.png`) });
    });
  }
}
