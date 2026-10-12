import { expect, type Page } from '@playwright/test';
import { waitForChatReady } from './chat-test-helpers';

/** Reopen a known chat after an app editor; the Chat tab links to the workspace root. */
export async function returnToChatWorkspace(page: Page, chatUrl: string): Promise<void> {
  await page.goto(chatUrl, { waitUntil: 'domcontentloaded' });
  await waitForChatReady(page);
  await expect(page, 'The existing chat must reopen before the wiki question').toHaveURL(chatUrl);
}

/** Reload an existing chat without waiting for unrelated iframe or asset load events. */
export async function reloadChatWorkspace(
  page: Page,
  chatUrl: string,
  logCheckpoint: (message: string) => void = () => {},
): Promise<void> {
  logCheckpoint('Chat workspace reload started.');
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  logCheckpoint('Chat workspace DOM content loaded.');
  await waitForChatReady(page);
  logCheckpoint('Chat workspace ready after reload.');
  await expect.poll(() => page.url() === chatUrl, {
    message: 'The existing chat URL must be restored after reload',
  }).toBe(true);
  logCheckpoint('Existing chat URL verified after reload.');
}
