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
