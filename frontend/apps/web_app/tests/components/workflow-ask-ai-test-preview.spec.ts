// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

function preview(variant?: string, theme = 'light', width = 900): string {
  const query = new URLSearchParams({ theme, width: String(width), chrome: '0' });
  if (variant) query.set('variant', variant);
  return `/dev/preview/workflows/WorkflowAskAiTestPreview?${query}`;
}

async function openPreview(page: Page, variant?: string, theme = 'light', width = 900): Promise<void> {
  await page.goto(preview(variant, theme, width), { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
}

test.describe('Workflow Ask AI test response', () => {
  for (const [width, theme] of [[390, 'dark'], [900, 'light']] as const) {
    // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,workflows-ui.responsive-accessible-reachable
    test(`selected result links and cards render left aligned at ${width}px in ${theme} mode`, async ({ page }: { page: Page }) => {
      await page.setViewportSize({ width, height: 844 });
      await openPreview(page, 'withEmbeds', theme, width);
      await page.addStyleTag({ content: '[data-testid="component-preview-canvas"] { text-align: center; }' });
      const response = page.getByTestId('workflow-ask-ai-test-preview');
      const body = response.getByTestId('workflow-ask-ai-test-body');
      await expect(body.locator('h2')).toHaveText('Art this week');
      await expect(body.locator('h2')).toHaveCSS('text-align', 'left');
      await expect(body.locator('p').first()).toHaveCSS('text-align', 'left');
      const inline = body.locator('.embed-inline-link').first();
      await expect(inline).toBeVisible();
      const results = body.getByRole('region', { name: 'Art classes' });
      await expect(results.getByRole('tabpanel', { name: 'Calendar results' })).toBeVisible();
      await expect(results.getByRole('button', { name: /Berlin drawing class/ })).toBeVisible();
      await expect(body).toContainText('Berlin drawing class');
      await page.evaluate(() => document.addEventListener('embedfullscreen', event => {
        const detail = (event as CustomEvent).detail;
        document.documentElement.dataset.workflowPreviewEmbed = JSON.stringify({ id: detail.embedId, type: detail.embedType });
      }));
      await inline.click();
      await expect.poll(() => page.evaluate(() => document.documentElement.dataset.workflowPreviewEmbed)).toContain('00000000-0000-4000-8000-000000007001');
      const persisted = await page.evaluate(async () => {
        if (!(await indexedDB.databases()).some(db => db.name === 'chats_db')) return false;
        const db = await new Promise<IDBDatabase>((resolve, reject) => { const request = indexedDB.open('chats_db'); request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
        try { if (!db.objectStoreNames.contains('embeds')) return false; return await new Promise<boolean>((resolve, reject) => { const request = db.transaction('embeds').objectStore('embeds').get('embed:00000000-0000-4000-8000-000000007001'); request.onsuccess = () => resolve(!!request.result); request.onerror = () => reject(request.error); }); } finally { db.close(); }
      });
      expect(persisted).toBe(false);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
      await response.screenshot({ animations: 'disabled', path: test.info().outputPath(`ask-ai-embeds-${width}-${theme}.png`) });
    });
  }
  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,chats.streaming.progressive-presentation
  test('uses the OpenMates assistant identity and chat Markdown renderer', async ({ page }: { page: Page }) => {
    await openPreview(page);
    const response = page.getByTestId('workflow-ask-ai-test-preview');
    await expect(response.getByTestId('workflow-ask-ai-test-sender')).toHaveText('OpenMates');
    await expect(response.getByTestId('workflow-ask-ai-test-avatar')).toHaveAttribute('aria-label', 'OpenMates');
    await expect(response.getByTestId('message-content')).toHaveAttribute('data-streaming', 'false');
    const body = response.getByTestId('workflow-ask-ai-test-body');
    await expect(body.locator('strong')).toHaveText(['Monday:', 'Tuesday:']);
    await expect(body.locator('li')).toHaveCount(2);
    await expect(body.locator('a[href="https://example.com/forecast"]')).toHaveText('forecast');
    await expect(response).not.toContainText('[DONE]');
    await expect(response).not.toContainText('data:');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,chats.streaming.progressive-presentation
  test('renders cumulative partial text and converges to the final rich response', async ({ page }: { page: Page }) => {
    await openPreview(page, 'streaming');
    const response = page.getByTestId('workflow-ask-ai-test-preview');
    await expect(response).toHaveAttribute('aria-busy', 'true');
    await expect(response.getByTestId('message-content')).toHaveAttribute('data-streaming', 'true');
    await expect(response.getByTestId('workflow-ask-ai-test-body')).toContainText('Monday: Mild and clear');

    await openPreview(page);
    await expect(response).toHaveAttribute('aria-busy', 'false');
    await expect(response.getByTestId('message-content')).toHaveAttribute('data-streaming', 'false');
    await expect(response.getByTestId('workflow-ask-ai-test-body').locator('li')).toHaveCount(2);
    await expect(response.getByTestId('workflow-ask-ai-test-body')).toContainText('Tuesday: Bring a raincoat');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.ask-ai,workflows-ui.responsive-accessible-reachable
  test('keeps error and empty states clear across themes and phone width', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openPreview(page, 'error', 'dark', 390);
    await expect(page.getByTestId('workflow-ask-ai-test-error')).toHaveAttribute('role', 'alert');
    await expect(page.getByTestId('workflow-ask-ai-test-message')).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await openPreview(page, 'streaming', 'dark', 390);
    await expect(page.getByTestId('workflow-ask-ai-test-body').locator('li')).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.getByTestId('workflow-ask-ai-test-preview').screenshot({ animations:'disabled', path: test.info().outputPath('ask-ai-response-phone.png') });
    await openPreview(page, 'empty', 'dark', 390);
    await expect(page.getByTestId('workflow-ask-ai-test-preview')).toHaveCount(0);
  });
});
