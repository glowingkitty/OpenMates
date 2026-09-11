/**
 * Workspace embed transition and cold-loading regressions.
 * Synthetic preview events exercise the real ActiveChat fullscreen handler.
 * Checks keep the shell responsive while children are unavailable, preserve
 * the chat element, and prevent intermediate layout changes during movement.
 * See docs/architecture/frontend/embed-workspace-transitions.md.
 */
import { expect, test } from '../helpers/cookie-audit';
import type { Page } from '@playwright/test';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/ActiveChat?chrome=0';
const LOAD_WAIT_MS = 4000;

async function openSearch(page: Page, missingChild = false) {
  await page.evaluate((missing) => {
    document.dispatchEvent(new CustomEvent('embedfullscreen', { detail: {
      embedType: 'app-skill-use', hasChatContext: true,
      embedData: { status: 'finished' },
      decodedContent: {
        app_id: 'web', skill_id: 'search', query: 'Workspace transition fixture',
        ...(missing ? { embed_ids: ['00000000-0000-4000-8000-000000000001'] } : {
          results: [{ title: 'Example result', url: 'https://example.com', description: 'Fictional search result.' }]
        })
      }
    }}));
  }, missingChild);
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(PREVIEW);
  await expect(page.getByTestId('active-chat-container')).toBeVisible();
  await expect(page.getByTestId('message-editor')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
test('a missing child does not block opening or closing the workspace shell', async ({ page }) => {
  await openSearch(page, true);
  const panel = page.getByTestId('embed-fullscreen-container');
  await expect(panel).toBeVisible({ timeout: 1000 });
  await panel.getByTestId('embed-minimize').click();
  await expect(panel).toHaveCount(0);
  // The old pre-open retry continues for 3.2 seconds. Closing must fence it.
  await page.waitForTimeout(LOAD_WAIT_MS);
  await expect(panel).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
test('warm pane movement preserves the chat and does not resize it on every frame', async ({ page }) => {
  const chat = page.getByTestId('chat-side');
  const originalChat = await chat.elementHandle();
  await openSearch(page);
  const panel = page.getByTestId('embed-fullscreen-container');
  await expect(panel.getByTestId('embed-minimize')).toBeVisible();
  await expect(panel.getByTestId('search-template-grid')).toBeVisible();
  // Let opening complete before measuring close independently.
  await page.waitForTimeout(600);
  const result = await panel.getByTestId('embed-minimize').evaluate(async (button: HTMLElement) => {
    const chatNode = document.querySelector('[data-testid="chat-side"]')!;
    const widths: number[] = [];
    const start = performance.now();
    button.click();
    await new Promise<void>((resolve) => {
      function sample(now: number) {
        widths.push(Math.round(chatNode.getBoundingClientRect().width));
        if (now - start < 900) requestAnimationFrame(sample); else resolve();
      }
      requestAnimationFrame(sample);
    });
    return { widths: [...new Set(widths)], connected: chatNode.isConnected };
  });
  expect(result.widths.length).toBeLessThanOrEqual(2);
  expect(result.connected).toBe(true);
  expect(await originalChat!.evaluate((node) => node.isConnected)).toBe(true);
  await expect(panel).toHaveCount(0);
  await originalChat!.dispose();
});

// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
test('reopening during the exit restores an interactive pane', async ({ page }) => {
  await openSearch(page);
  const panel = page.getByTestId('embed-fullscreen-container');
  await expect(panel.getByTestId('search-template-grid')).toBeVisible();
  await page.waitForTimeout(300);
  await panel.getByTestId('embed-minimize').evaluate(async (button: HTMLElement) => {
    button.click();
    // Reopen after the close has flushed, while its 200 ms outro still owns
    // the retained element. This exercises Svelte's interrupted-outro reuse.
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    document.dispatchEvent(new CustomEvent('embedfullscreen', { detail: {
      embedType: 'app-skill-use', hasChatContext: true,
      embedData: { status: 'finished' },
      decodedContent: {
        app_id: 'web', skill_id: 'search', query: 'Reopened workspace fixture',
        results: [{ title: 'Reopened result', url: 'https://example.com', description: 'Fictional search result.' }]
      }
    }}));
  });
  await expect(panel).toHaveCount(1);
  await expect(panel).toHaveCSS('pointer-events', 'auto');
  await expect(panel).toHaveCSS('position', 'relative');
  await expect(panel.getByTestId('search-template-grid')).toContainText('Reopened result');
  await panel.getByTestId('embed-minimize').click();
  await expect(panel).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
test('vertical wheel over an embed row scrolls the chat in both directions', async ({ page }) => {
  await page.goto('/#chat-id=example-ai-workshops-meetups-berlin');
  const history = page.getByTestId('chat-history-container');
  const row = page.getByTestId('app-skill-embed-group-scroll').first();
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect.poll(() => row.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);

  await row.hover();
  const beforeDown = await history.evaluate(el => el.scrollTop);
  await page.mouse.wheel(0, 100);
  await expect.poll(() => history.evaluate(el => el.scrollTop)).toBeGreaterThan(beforeDown + 30);

  await row.hover();
  const beforeUp = await history.evaluate(el => el.scrollTop);
  expect(beforeUp).toBeGreaterThan(30);
  await page.mouse.wheel(0, -100);
  await expect.poll(() => history.evaluate(el => el.scrollTop)).toBeLessThan(beforeUp - 30);

  // A horizontal gesture still moves the embed list, not the conversation.
  await row.hover();
  const beforeHorizontal = await history.evaluate(el => el.scrollTop);
  const beforeLeft = await row.evaluate(el => el.scrollLeft);
  await page.mouse.wheel(180, 0);
  await expect.poll(() => row.evaluate(el => el.scrollLeft)).toBeGreaterThan(beforeLeft + 30);
  expect(await history.evaluate(el => el.scrollTop)).toBeCloseTo(beforeHorizontal, 0);
});
