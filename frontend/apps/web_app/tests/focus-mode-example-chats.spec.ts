/* eslint-disable @typescript-eslint/no-require-imports */
/**
 * Regression coverage for example-chat focus state navigation.
 * Example chats can carry active focus metadata, but that state must not leak
 * into the next example chat while ActiveChat asynchronously loads metadata.
 * Spec: docs/specs/finance-example-quality/spec.yml
 */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

async function navigateToExampleChat(page: any, chatId: string): Promise<void> {
  await page.evaluate((targetChatId: string) => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    params.set('chat-id', targetChatId);
    window.location.hash = params.toString();
  }, chatId);
  await page.waitForFunction((targetChatId: string) => {
    return new URLSearchParams(window.location.hash.slice(1)).get('chat-id') === targetChatId;
  }, chatId, { timeout: 10_000 });
}

test.describe('focus-mode example chat state', () => {
  test('does not leak an active focus pill into the Finance example chat', async ({ page }: { page: any }) => {
    test.setTimeout(60_000);

    await page.goto(getE2EDebugUrl('/#chat-id=example-frontend-developer-career-pivot'), {
      waitUntil: 'domcontentloaded',
    });
    await expect(page.getByTestId('message-assistant').filter({ hasText: 'career' }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('focus-pill')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('focus-pill-label')).toContainText(/career/i);

    await navigateToExampleChat(page, 'example-finance-cash-flow-overview');
    await expect(page).toHaveURL(/chat-id=example-finance-cash-flow-overview/, { timeout: 10_000 });
    await expect(page.getByText('Business Cash Flow Overview')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('user-message-content').filter({ hasText: 'cash flow' }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('focus-pill')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('Focus active');
  });
});
