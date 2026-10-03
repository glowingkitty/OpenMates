import { expect, type Page, type TestInfo } from '@playwright/test';

/** Auth/socket readiness does not imply the selected encrypted chat is loaded. */
export async function waitForHydratedChat(page: Page, chatId: string, testInfo: TestInfo): Promise<void> {
  const activeChat = page.getByTestId('active-chat-container');
  try {
    await expect.poll(() => activeChat.evaluate(element => ({
      chatId: element.getAttribute('data-current-chat-id'),
      loadState: element.getAttribute('data-chat-load-state'),
    })), { timeout: 30_000 }).toEqual({ chatId, loadState: 'ready' });
  } catch (error) {
    const state = await activeChat.evaluate(element => ({
      chatId: element.getAttribute('data-current-chat-id'),
      loadState: element.getAttribute('data-chat-load-state'),
      messagesVersion: element.getAttribute('data-current-chat-messages-version'),
      messageCount: element.getAttribute('data-current-message-count'),
      messagesConsistent: element.getAttribute('data-current-message-chat-consistent'),
    })).catch(() => null);
    await testInfo.attach('chat-hydration-state', { body: JSON.stringify(state), contentType: 'application/json' });
    throw error;
  }
}
