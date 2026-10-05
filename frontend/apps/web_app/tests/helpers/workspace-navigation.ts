import { expect, type Page } from '@playwright/test';
import { waitForChatReady } from './chat-test-helpers';

/** Reopen a known chat after an app editor; the Chat tab links to the workspace root. */
export async function returnToChatWorkspace(page: Page, chatUrl: string): Promise<void> {
  await page.goto(chatUrl, { waitUntil: 'domcontentloaded' });
  await waitForChatReady(page);
  await expect(page, 'The existing chat must reopen before the wiki question').toHaveURL(chatUrl);
}
