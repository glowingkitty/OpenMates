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

async function navigateToFinanceExample(page: any): Promise<void> {
  const financeTitle = page.getByTestId('chat-header-title').filter({ hasText: 'Summarize recent business finances' }).first();
  for (let attempt = 0; attempt < 12; attempt += 1) {
    if (await financeTitle.isVisible().catch(() => false)) return;
    const previousButton = page.getByTestId('chat-header-previous').first();
    if (await previousButton.isVisible().catch(() => false)) {
      await previousButton.click();
    } else {
      await page.getByTestId('chat-header-next').first().click();
    }
    await expect(page.getByTestId('chat-header-title').first()).toBeVisible({ timeout: 5_000 });
  }
  await expect(financeTitle).toBeVisible({ timeout: 5_000 });
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

    await navigateToFinanceExample(page);
    await expect(page).toHaveURL(/chat-id=example-finance-cash-flow-overview/, { timeout: 10_000 });
    await expect(page.getByTestId('chat-header-title').filter({ hasText: 'Summarize recent business finances' }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('user-message-content').filter({ hasText: 'cash flow' }).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('focus-pill')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('Focus active');
  });
});
