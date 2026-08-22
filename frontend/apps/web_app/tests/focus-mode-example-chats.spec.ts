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
  const sidebarToggle = page.getByTestId('sidebar-toggle');
  await expect(sidebarToggle).toBeVisible({ timeout: 10_000 });
  await sidebarToggle.click();

  const financeChat = page.locator('[data-testid="chat-item-wrapper"][data-chat-id="example-finance-cash-flow-overview"]');
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if ((await financeChat.count()) > 0) {
      await financeChat.first().scrollIntoViewIfNeeded();
      await expect(financeChat.first()).toBeVisible({ timeout: 10_000 });
      await financeChat.first().click();
      return;
    }

    const showMoreExamples = page.getByTestId('show-more-example-chats').first();
    if ((await showMoreExamples.count()) > 0) {
      await showMoreExamples.scrollIntoViewIfNeeded();
      await showMoreExamples.click();
      await page.waitForTimeout(500);
      continue;
    }

    break;
  }

  await expect(financeChat.first()).toBeVisible({ timeout: 10_000 });
}

test.describe('focus-mode example chat state', () => {
  // contract-test: direct surface=gui.web assertions=public-example-chats.surface.semantic-parity,public-example-chats.transcript.safe-rendering
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

  // contract-test: direct surface=gui.web assertions=public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
  test('renders Deep research sub-chat summaries below activation and opens child transcript', async ({
    page,
  }: {
    page: any;
  }) => {
    test.setTimeout(60_000);

    await page.goto(getE2EDebugUrl('/#chat-id=example-us-egg-prices-deep'), {
      waitUntil: 'domcontentloaded',
    });

    await expect(
      page.getByTestId('user-message-content').filter({
        hasText: 'Why did US egg prices stay high after avian flu eased?',
      }),
    ).toBeVisible({ timeout: 15_000 });

    const focusBar = page.getByTestId('focus-mode-bar').filter({ hasText: 'Deep research' }).first();
    await expect(focusBar).toBeVisible({ timeout: 15_000 });

    const carousel = page.getByTestId('sub-chats-carousel');
    await expect(carousel).toBeVisible({ timeout: 15_000 });
    await expect(carousel.getByTestId('sub-chat-card')).toHaveCount(3);

    const firstCard = carousel.getByTestId('sub-chat-card').filter({ hasText: 'Research US egg supply recover' }).first();
    await expect(firstCard).toContainText('Reviews avian-flu flock losses');
    await expect(firstCard.getByTestId('sub-chat-status-completed')).toContainText('Completed');
    await expect(carousel.getByTestId('sub-chat-card').filter({ hasText: 'Compares counterarguments around feed' }).first()).toBeVisible();
    await expect(carousel.getByTestId('sub-chat-card').filter({ hasText: 'Examines producer concentration' }).first()).toBeVisible();

    const focusBox = await focusBar.boundingBox();
    const carouselBox = await carousel.boundingBox();
    expect(focusBox, 'Focus activation card should have a rendered layout box.').not.toBeNull();
    expect(carouselBox, 'Sub-chat carousel should have a rendered layout box.').not.toBeNull();
    expect(carouselBox!.y, 'Sub-chat cards should render after the focus-mode activation card.').toBeGreaterThan(
      focusBox!.y + focusBox!.height,
    );

    await firstCard.click();
    await expect(page).toHaveURL(/chat-id=example-us-egg-prices-deep-sub-chat-1/, { timeout: 10_000 });
    await expect(
      page.getByTestId('user-message-content').filter({
        hasText: 'Research US egg supply recovery timelines',
      }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByTestId('mate-message-content').filter({
        hasText: 'Supply recovered slowly because the 2024-2025 HPAI losses hit laying hens',
      }),
    ).toBeVisible({ timeout: 15_000 });

    const returnButton = page.getByTestId('return-to-parent-button');
    await expect(returnButton).toBeVisible({ timeout: 10_000 });
    await returnButton.click();
    await expect(page).toHaveURL(/chat-id=example-us-egg-prices-deep/, { timeout: 10_000 });
  });
});
