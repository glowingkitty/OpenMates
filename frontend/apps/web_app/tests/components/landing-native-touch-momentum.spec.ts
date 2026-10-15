import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview
test.use({ browserName: 'chromium', hasTouch: true, isMobile: true });
test.beforeEach(async ({ page }) => {
  await page.route('**/v1/settings/server-status', route => route.fulfill({json:{anonymous_free_usage:{active:true,can_send_text:true}}}));
});
const preview = (width: number) => `/dev/preview/landing/LandingPage?chrome=0&theme=light&width=${width}`;
const scrollToFeature = async (page: import('@playwright/test').Page, id: string, offset = 0) => {
  await page.getByTestId('landing-scroll-container').evaluate((element, target) => {
    const section = element.querySelector<HTMLElement>(`#${target.id}`)!;
    const top = section.getBoundingClientRect().top - element.getBoundingClientRect().top + element.scrollTop;
    element.scrollTo({ top: top + target.offset, behavior: 'auto' });
  }, { id, offset });
};

  // contract-test: direct surface=gui.web assertions=marketing-landing.independent-scroll
  test('trusted vertical touch release continues native momentum without section snapping', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(preview(390), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await scrollToFeature(page, 'actionable', 40);
    const scroller = page.getByTestId('landing-scroll-container');
    await expect(scroller).toHaveCSS('scroll-snap-type', 'none');
    const initialTop = await scroller.evaluate(element => element.scrollTop);
    await scroller.evaluate(element => {
      element.addEventListener('touchend', event => {
        const releaseTop = element.scrollTop;
        const samples: number[] = [];
        queueMicrotask(() => {
          element.setAttribute('data-touch-trusted', String(event.isTrusted));
          element.setAttribute('data-touch-cancelled', String(event.defaultPrevented));
          const sample = () => {
            samples.push(element.scrollTop);
            if (samples.length < 40) requestAnimationFrame(sample);
            else element.setAttribute('data-touch-momentum', JSON.stringify({ releaseTop, samples }));
          };
          requestAnimationFrame(sample);
        });
      }, { passive: true, once: true });
    });
    const bounds = await scroller.boundingBox();
    expect(bounds).not.toBeNull();
    const x = Math.round(bounds!.x + bounds!.width * .72);
    const startY = Math.round(bounds!.y + bounds!.height * .72);
    const hitTarget = await page.evaluate(({ x, y }) => {
      const target = document.elementFromPoint(x, y);
      const ancestors = [];
      for (let node = target; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        ancestors.push({ tag: node.tagName, testId: node.getAttribute('data-testid'), touchAction: style.touchAction,
          overflowY: style.overflowY, snap: style.scrollSnapType });
      }
      return { insideScroller: !!target?.closest('[data-testid="landing-scroll-container"]'), ancestors };
    }, { x, y: startY });
    expect(hitTarget.insideScroller).toBe(true);
    expect(hitTarget.ancestors.every(node => node.touchAction !== 'none')).toBe(true);
    const cdp = await page.context().newCDPSession(page);
    try {
      // Dispatch native touch points directly. synthesizeScrollGesture's
      // preventFling:false removes its stopping delay but does not guarantee a
      // release velocity. Frame-paced moves followed immediately by release
      // let Chromium's own gesture recognizer calculate that velocity.
      await cdp.send('Input.dispatchTouchEvent', {
        type: 'touchStart', touchPoints: [{ x, y: startY, id: 1 }], timestamp: Date.now() / 1000,
      });
      for (let step = 1; step <= 7; step++) {
        await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
        await cdp.send('Input.dispatchTouchEvent', {
          type: 'touchMove', touchPoints: [{ x, y: startY - step * 40, id: 1 }], timestamp: Date.now() / 1000,
        });
      }
      await cdp.send('Input.dispatchTouchEvent', {
        type: 'touchEnd', touchPoints: [], timestamp: Date.now() / 1000,
      });
    } finally { await cdp.detach(); }
    await expect(scroller).toHaveAttribute('data-touch-trusted', 'true');
    await expect(scroller).toHaveAttribute('data-touch-cancelled', 'false');
    await expect(scroller).toHaveAttribute('data-touch-momentum', /releaseTop/);
    const momentum = JSON.parse((await scroller.getAttribute('data-touch-momentum'))!) as { releaseTop: number; samples: number[] };
    await testInfo.attach('trusted-native-touch-momentum', { body: JSON.stringify({ initialTop, hitTarget, ...momentum }), contentType: 'application/json' });
    expect(momentum.releaseTop).toBeGreaterThan(initialTop + 100);
    expect(Math.max(...momentum.samples)).toBeGreaterThan(momentum.releaseTop + 5);
    expect(momentum.samples.some((position, index) => index > 0 && position > momentum.samples[index - 1] + 1)).toBe(true);
    const positions: number[] = [];
    await expect.poll(async () => {
      positions.push(await scroller.evaluate(element => element.scrollTop));
      return positions.length >= 3 && Math.max(...positions.slice(-3)) - Math.min(...positions.slice(-3)) < 2;
    }, { intervals: [100, 200, 300] }).toBe(true);
    await expect(scroller).toHaveCSS('scroll-snap-type', 'none');
  });
