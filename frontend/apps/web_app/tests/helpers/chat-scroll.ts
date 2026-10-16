// contract-test-file: infrastructure
import { expect, type Page, type TestInfo } from '@playwright/test';
import { waitForComponentMotion } from './component-preview';

/** Initial hydration can schedule a later scroll to the latest message. */
export async function scrollChatHistoryToStart(page: Page, testInfo: TestInfo): Promise<void> {
  const container = page.getByTestId('chat-history-container');
  try {
    await expect(container, 'chat scroll should finish before reading older history')
      .toHaveAttribute('data-scroll-state', 'ready', { timeout: 10_000 });
    await container.evaluate(async element => {
      element.scrollTo({ top: 0, behavior: 'instant' });
      // Let the scroll event and its frame-based UI update reach the DOM.
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    });
    await expect.poll(() => container.evaluate(element => ({
      state: element.getAttribute('data-scroll-state'),
      top: element.scrollTop,
    })), { message: 'chat should remain at the beginning after its initial scroll', timeout: 5_000 })
      .toEqual({ state: 'ready', top: 0 });
  } catch (error) {
    const state = await container.evaluate(element => ({
      state: element.getAttribute('data-scroll-state'),
      top: element.scrollTop,
      height: element.clientHeight,
      contentHeight: element.scrollHeight,
    })).catch(() => null);
    await testInfo.attach('chat-scroll-state', { body: JSON.stringify(state), contentType: 'application/json' });
    throw error;
  }
}

/** Wait until fixed call controls and their chat scroller have stopped moving. */
export async function waitForStickyCallControlsReady(page: Page, testInfo: TestInfo): Promise<void> {
  const history = page.getByTestId('chat-history-container');
  const bar = page.getByTestId('voice-call-bar');
  const more = page.getByTestId('voice-call-more');
  const video = page.getByTestId('voice-call-video');
  try {
    await expect(history).toHaveAttribute('data-scroll-state', 'ready');
    await expect(bar).toHaveClass(/fixed/);
    await waitForComponentMotion(more);
    await waitForComponentMotion(video);
    await expect.poll(async () => page.evaluate(async () => {
      const sample = () => {
        const history = document.querySelector<HTMLElement>('[data-testid="chat-history-container"]');
        const bar = document.querySelector<HTMLElement>('[data-testid="voice-call-bar"]');
        const more = document.querySelector<HTMLElement>('[data-testid="voice-call-more"]');
        if (!history || !bar || !more) return null;
        const h = history.getBoundingClientRect();
        const b = bar.getBoundingClientRect();
        const m = more.getBoundingClientRect();
        const hit = document.elementFromPoint(m.left + m.width / 2, m.top + m.height / 2);
        return {
          ready: history.getAttribute('data-scroll-state') === 'ready',
          fixed: bar.classList.contains('fixed'),
          aligned: b.top === h.top,
          inside: m.width > 0 && m.height > 0 && m.left >= b.left && m.right <= b.right &&
            m.top >= b.top && m.bottom <= b.bottom,
          hit: hit === more || more.contains(hit),
          metrics: {
            history: { x: h.x, y: h.y, width: h.width, height: h.height,
              top: history.scrollTop, scrollHeight: history.scrollHeight, clientHeight: history.clientHeight },
            bar: { x: b.x, y: b.y, width: b.width, height: b.height },
            more: { x: m.x, y: m.y, width: m.width, height: m.height },
          },
        };
      };
      const first = await new Promise<ReturnType<typeof sample>>(resolve => requestAnimationFrame(() => resolve(sample())));
      const second = await new Promise<ReturnType<typeof sample>>(resolve => requestAnimationFrame(() => resolve(sample())));
      return {
        ready: first?.ready && second?.ready,
        fixed: first?.fixed && second?.fixed,
        aligned: first?.aligned && second?.aligned,
        inside: first?.inside && second?.inside,
        hit: first?.hit && second?.hit,
        stable: !!first && !!second && JSON.stringify(first.metrics) === JSON.stringify(second.metrics),
      };
    }), { message: 'fixed call controls should remain stable and clickable within the chat viewport' })
      .toEqual({ ready: true, fixed: true, aligned: true, inside: true, hit: true, stable: true });
  } catch (error) {
    const state = await page.evaluate(() => {
      const history = document.querySelector<HTMLElement>('[data-testid="chat-history-container"]');
      const bar = document.querySelector<HTMLElement>('[data-testid="voice-call-bar"]');
      const more = document.querySelector<HTMLElement>('[data-testid="voice-call-more"]');
      const h = history?.getBoundingClientRect();
      const b = bar?.getBoundingClientRect();
      const m = more?.getBoundingClientRect();
      const hit = m && document.elementFromPoint(m.left + m.width / 2, m.top + m.height / 2);
      return {
        history: h && { y: h.y, height: h.height, scrollTop: history?.scrollTop,
          scrollHeight: history?.scrollHeight, clientHeight: history?.clientHeight,
          state: history?.getAttribute('data-scroll-state') },
        bar: b && { y: b.y, height: b.height, fixed: bar?.classList.contains('fixed') },
        more: m && { x: m.x, y: m.y, width: m.width, height: m.height,
          centerHitMore: hit === more || !!(hit && more?.contains(hit)) },
      };
    }).catch(() => null);
    await testInfo.attach('sticky-call-controls-state', { body: JSON.stringify(state), contentType: 'application/json' });
    throw error;
  }
}
