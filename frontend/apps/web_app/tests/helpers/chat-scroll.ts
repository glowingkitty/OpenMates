// contract-test-file: infrastructure
import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';
import { waitForComponentMotion } from './component-preview';

/** Finish native scrolling before opening a surface that dismisses on scroll. */
export async function clickSettledScrollTarget(target: Locator, testInfo: TestInfo): Promise<void> {
  await expect(target).toBeVisible();
  await expect(target).toBeEnabled();
  await target.scrollIntoViewIfNeeded();
  try {
    await expect.poll(() => target.evaluate(async element => {
      const sample = () => {
        const bounds = element.getBoundingClientRect();
        const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
        const offsets = [[window.scrollX, window.scrollY]];
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
          offsets.push([parent.scrollLeft, parent.scrollTop]);
        }
        return { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height, offsets,
          hit: hit === element || !!hit && element.contains(hit) };
      };
      const first = await new Promise<ReturnType<typeof sample>>(resolve => requestAnimationFrame(() => resolve(sample())));
      const second = await new Promise<ReturnType<typeof sample>>(resolve => requestAnimationFrame(() => resolve(sample())));
      return { stable: JSON.stringify(first) === JSON.stringify(second), hit: first.hit && second.hit };
    }), { message: 'scroll target should settle and receive pointer input before opening its menu' })
      .toEqual({ stable: true, hit: true });
    await target.click();
  } catch (error) {
    const state = await target.evaluate(element => ({ testId: element.getAttribute('data-testid'),
      bounds: element.getBoundingClientRect().toJSON(), connected: element.isConnected })).catch(() => null);
    await testInfo.attach('scroll-target-state', { body: JSON.stringify(state), contentType: 'application/json' });
    throw error;
  }
}

/** Scroll a chat action into the usable area below any sticky call media. */
export async function clickChatTarget(target: Locator, testInfo: TestInfo): Promise<void> {
  try {
    await expect(target).toBeVisible();
    await expect(target).toBeEnabled();
    await target.scrollIntoViewIfNeeded();
    await expect.poll(() => target.evaluate(async element => {
      const history = element.closest<HTMLElement>('[data-testid="chat-history-container"]');
      if (!history) return false;
      const h = history.getBoundingClientRect();
      const bar = document.querySelector('[data-testid="voice-call-bar"]')?.getBoundingClientRect();
      const top = Math.max(0, h.top, bar && bar.right > h.left && bar.left < h.right ? bar.bottom : h.top);
      const bottom = Math.min(innerHeight, h.bottom);
      const bounds = element.getBoundingClientRect();
      if (bounds.top < top || bounds.bottom > bottom) {
        history.scrollTop += bounds.top + bounds.height / 2 - (top + bottom) / 2;
      }
      const sample = () => {
        const rect = element.getBoundingClientRect();
        const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        return { ready: history.getAttribute('data-scroll-state') === 'ready',
          hit: hit === element || !!hit && element.contains(hit),
          x: rect.x, y: rect.y, width: rect.width, height: rect.height, scrollTop: history.scrollTop };
      };
      const first = await new Promise<ReturnType<typeof sample>>(resolve => requestAnimationFrame(() => resolve(sample())));
      const second = await new Promise<ReturnType<typeof sample>>(resolve => requestAnimationFrame(() => resolve(sample())));
      return first.ready && second.ready && first.hit && second.hit && JSON.stringify(first) === JSON.stringify(second);
    }), { message: 'chat action should settle in an unobstructed part of the chat viewport' }).toBe(true);
    await target.click();
  } catch (error) {
    const state = await target.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const history = element.closest<HTMLElement>('[data-testid="chat-history-container"]');
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return { testId: element.getAttribute('data-testid'), bounds: rect.toJSON(),
        scrollState: history?.getAttribute('data-scroll-state'), scrollTop: history?.scrollTop,
        hitTestId: hit?.closest('[data-testid]')?.getAttribute('data-testid') };
    }).catch(() => null);
    await testInfo.attach('chat-target-state', { body: JSON.stringify(state), contentType: 'application/json' });
    throw error;
  }
}

/** Open an untouched activity group after its asynchronous terminal check settles. */
export async function openCompletedAssistantActivity(group: Locator, testInfo: TestInfo): Promise<void> {
  await expect(group).not.toHaveClass(/(?:^|\s)active(?:\s|$)/);
  const toggle = group.getByTestId('assistant-activity-toggle');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  // Observe the one real activation through its postcondition. Geometry alone
  // cannot distinguish a missed click from replacement or a later state reset.
  const activation = await toggle.evaluateHandle(element => {
    const group = element.closest('[data-testid="assistant-activity-group"]');
    const snapshot = () => ({ expanded: element.getAttribute('aria-expanded'),
      connected: element.isConnected, groupConnected: group?.isConnected ?? false });
    const transitions = [snapshot()];
    const events: Array<{ type: string; phase: string; trusted: boolean; prevented: boolean;
      targetTestId: string | null; originalTarget: boolean; expanded: string | null; connected: boolean }> = [];
    const record = (event: Event, phase: string) => {
      if (events.length >= 16) return;
      const target = event.target instanceof Element ? event.target : null;
      events.push({ type: event.type, phase, trusted: event.isTrusted, prevented: event.defaultPrevented,
        targetTestId: target?.closest('[data-testid]')?.getAttribute('data-testid') ?? null,
        originalTarget: !!target && (target === element || element.contains(target)),
        expanded: element.getAttribute('aria-expanded'), connected: element.isConnected });
    };
    const capture = (event: Event) => record(event, 'capture');
    const bubble = (event: Event) => record(event, 'bubble');
    for (const type of ['pointerdown', 'pointerup', 'click']) {
      document.addEventListener(type, capture, true);
      document.addEventListener(type, bubble);
    }
    const observer = new MutationObserver(() => {
      const state = snapshot();
      if (transitions.length < 16 && JSON.stringify(state) !== JSON.stringify(transitions.at(-1))) transitions.push(state);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-expanded'] });
    return { read: () => ({ events, transitions, final: snapshot() }), dispose: () => {
      observer.disconnect();
      for (const type of ['pointerdown', 'pointerup', 'click']) {
        document.removeEventListener(type, capture, true);
        document.removeEventListener(type, bubble);
      }
    } };
  });
  try {
    await clickChatTarget(toggle, testInfo);
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(group.getByTestId('assistant-activity-body')).toBeVisible();
  } catch (error) {
    const state = await activation.evaluate(probe => probe.read()).catch(() => ({ captureFailed: true }));
    await testInfo.attach('assistant-activity-activation', { body: JSON.stringify(state), contentType: 'application/json' });
    throw error;
  } finally {
    await activation.evaluate(probe => probe.dispose()).catch(() => {});
    await activation.dispose();
  }
}

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

/** Exercise native wheel scrolling without dismissing the active composer. */
export async function expectFocusedChatWheelScroll(page: Page): Promise<void> {
  const history = page.getByTestId('chat-history-container');
  const field = page.getByTestId('message-field');
  const editor = page.getByTestId('message-editor').locator('.ProseMirror');
  await expect(field).toHaveAttribute('data-focused', 'true');
  await expect(editor).toBeFocused();
  await expect(history).toHaveAttribute('data-scroll-state', 'ready');
  await expect.poll(() => history.evaluate(element => element.scrollHeight - element.clientHeight)).toBeGreaterThan(600);
  // Position the fixture in the middle so both directions have real history.
  // Only setup uses scrollTo; the regression assertions require native input.
  const initialTop = await history.evaluate(element => {
    element.scrollTo({ top: (element.scrollHeight - element.clientHeight) / 2, behavior: 'instant' });
    return element.scrollTop;
  });
  const bounds = await history.boundingBox();
  expect(bounds).not.toBeNull();
  await page.mouse.move(bounds!.x + bounds!.width * 0.75, bounds!.y + bounds!.height * 0.5);
  await page.mouse.wheel(0, -280);
  await expect.poll(() => history.evaluate(element => element.scrollTop)).toBeLessThan(initialTop - 100);
  await expect(editor).toBeFocused();
  const afterUp = await history.evaluate(element => element.scrollTop);
  await page.mouse.wheel(0, 280);
  await expect.poll(() => history.evaluate(element => element.scrollTop)).toBeGreaterThan(afterUp + 100);
  await expect(field).toHaveAttribute('data-focused', 'true');
  await expect(editor).toBeFocused();
}
