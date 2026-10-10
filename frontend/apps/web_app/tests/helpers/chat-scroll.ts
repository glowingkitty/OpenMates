import { expect, type Page, type TestInfo } from '@playwright/test';

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
