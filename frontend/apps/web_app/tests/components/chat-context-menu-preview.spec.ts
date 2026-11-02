// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (width = 420) =>
  `/dev/preview/chats/ChatContextMenu?${new URLSearchParams({ chrome: '0', theme: 'dark', width: String(width) })}`;

test.describe('Chat context menu', () => {
  // contract-test: direct surface=gui.web assertions=chat-navigation.menu.parity-ranked
  test('shows at most five actions, a close button and a scroll arrow for the rest', async ({ page }) => {
    await page.goto(preview());
    await waitForComponentPreview(page);
    const menu = page.getByTestId('context-menu');
    await expect(menu).toBeVisible();
    await expect(menu.getByTestId('chat-context-close')).toBeVisible();

    const list = menu.getByTestId('chat-context-scroll');
    const items = list.locator('[data-usage-id]');
    expect(await items.count()).toBeGreaterThan(5);

    // Only the first five actions fit the scroll viewport.
    const listBox = await list.boundingBox();
    const fifth = await items.nth(4).boundingBox();
    const sixth = await items.nth(5).boundingBox();
    expect(listBox && fifth && sixth).toBeTruthy();
    expect(fifth!.y + fifth!.height).toBeLessThanOrEqual(listBox!.y + listBox!.height + 1);
    expect(sixth!.y).toBeGreaterThanOrEqual(listBox!.y + listBox!.height - 1);

    // The triangle scrolls down to the remaining actions, then disappears.
    const more = menu.getByTestId('chat-context-scroll-more');
    await expect(more).toBeVisible();
    await expect(more).toHaveAttribute('aria-label', /more/i);
    await more.click();
    await expect.poll(() => list.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    await list.evaluate(el => el.scrollTo({ top: el.scrollHeight }));
    await expect(more).toHaveCount(0);
    await expect(menu.getByTestId('chat-context-delete')).toBeInViewport();
    // Scrolling inside the menu must not close it.
    await expect(menu).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=chat-navigation.menu.parity-ranked
  test('uses uniform colours and real icons for every action', async ({ page }) => {
    await page.goto(preview());
    await waitForComponentPreview(page);
    const items = page.getByTestId('context-menu').locator('[data-usage-id][data-tone="default"]:enabled');
    const colours = await items.evaluateAll(nodes => nodes.map(node => getComputedStyle(node).color));
    expect(colours.length).toBeGreaterThan(3);
    expect(new Set(colours).size).toBe(1);
    const masks = await page.getByTestId('context-menu').getByTestId('chat-context-icon')
      .evaluateAll(nodes => nodes.map(node => getComputedStyle(node).maskImage || getComputedStyle(node).webkitMaskImage));
    expect(masks.every(mask => mask && mask !== 'none')).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=chat-navigation.menu.parity-ranked
  test('ranks a used action first', async ({ page }) => {
    await page.goto(preview());
    await waitForComponentPreview(page);
    const list = page.getByTestId('context-menu').getByTestId('chat-context-scroll');
    await expect(list.locator('[data-usage-id]').first()).not.toHaveAttribute('data-testid', 'chat-context-mark-unread');
    await list.getByTestId('chat-context-mark-unread').click();
    await expect(list.locator('[data-usage-id]').first()).toHaveAttribute('data-testid', 'chat-context-mark-unread');
  });
});
