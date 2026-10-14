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

/** Settle initial account sync before seeding or selecting a local fixture chat. */
export async function waitForContextSyncComplete(page: Page, testInfo: TestInfo): Promise<void> {
  const connectionState = () => page.evaluate(async () => {
    const hook = (window as typeof window & {
      __openmatesE2EChatConnectionState?: () => Promise<{
        websocketConnected: boolean;
        cachePrimed: boolean;
        contextSyncCompleted: boolean;
      }>;
    }).__openmatesE2EChatConnectionState;
    if (!hook) return null;
    const state = await hook();
    return {
      websocketConnected: state.websocketConnected,
      cachePrimed: state.cachePrimed,
      contextSyncCompleted: state.contextSyncCompleted,
    };
  });
  try {
    await expect.poll(async () => (await connectionState())?.contextSyncCompleted === true,
      { timeout: 45_000 }).toBe(true);
  } catch (error) {
    await testInfo.attach('chat-context-sync-state', {
      body: JSON.stringify(await connectionState().catch(() => null)),
      contentType: 'application/json',
    });
    throw error;
  }
}

/** Select a chat only after the account's initial snapshot can no longer replace it. */
export async function openChatAfterContextSync(page: Page, chatId: string, testInfo: TestInfo): Promise<void> {
  await waitForContextSyncComplete(page, testInfo);
  await page.evaluate((id) => {
    const target = `#chat-id=${encodeURIComponent(id)}`;
    // Reload can leave the target hash in the URL after startup reset selection.
    // Clearing only that stale hash lets the router observe a real hash change.
    if (window.location.hash === target) {
      window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
    }
    window.location.hash = target;
  }, chatId);
  await waitForHydratedChat(page, chatId, testInfo);
}

/** Click the one currently usable composer Send control without DOM-order guesses. */
export async function clickReadyComposerSend(page: Page): Promise<void> {
  const send = page.getByTestId('composer-send-button').filter({ visible: true });
  await expect(send).toHaveCount(1);
  await expect(send).toBeEnabled();
  await send.click();
}
