// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');

function preview(variant?: string, theme = 'light', width = 900): string {
  const query = new URLSearchParams({ theme, width: String(width), chrome: '0' });
  if (variant) query.set('variant', variant);
  return `/dev/preview/workflows/WorkflowAskAiTestPreview?${query}`;
}

async function openPreview(page: Page, variant?: string, theme = 'light', width = 900): Promise<void> {
  await page.goto(preview(variant, theme, width), { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
}

test.describe('Workflow Ask AI test response', () => {
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
