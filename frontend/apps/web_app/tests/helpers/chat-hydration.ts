import { expect, type Locator, type Page, type TestInfo } from '@playwright/test';

/** Auth/socket readiness does not imply the selected encrypted chat is loaded. */
export async function waitForHydratedChat(
  page: Page, chatId: string, testInfo: TestInfo, targetMessage?: Locator,
): Promise<void> {
  const activeChat = page.getByTestId('active-chat-container');
  const deadline = Date.now() + 30_000;
  try {
    await expect.poll(() => activeChat.evaluate(element => ({
      chatId: element.getAttribute('data-current-chat-id'),
      loadState: element.getAttribute('data-chat-load-state'),
    })), { timeout: Math.max(1, deadline - Date.now()) }).toEqual({ chatId, loadState: 'ready' });
    // Decryption/loading can finish before the selected message's body renders.
    if (targetMessage) await expect(targetMessage).toBeVisible({ timeout: Math.max(1, deadline - Date.now()) });
  } catch (error) {
    const state = await activeChat.evaluate(element => ({
      chatId: element.getAttribute('data-current-chat-id'),
      loadState: element.getAttribute('data-chat-load-state'),
      messagesVersion: element.getAttribute('data-current-chat-messages-version'),
      messageCount: element.getAttribute('data-current-message-count'),
      messagesConsistent: element.getAttribute('data-current-message-chat-consistent'),
    })).catch(() => null);
    const target = targetMessage ? {
      count: await targetMessage.count().catch(() => -1),
      visible: await targetMessage.isVisible().catch(() => false),
    } : undefined;
    await testInfo.attach('chat-hydration-state', { body: JSON.stringify({ state, target }), contentType: 'application/json' });
    throw error;
  }
}
