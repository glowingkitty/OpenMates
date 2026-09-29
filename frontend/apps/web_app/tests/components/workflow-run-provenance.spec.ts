// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

const { expect, test } = require('../helpers/cookie-audit');

test.describe('Workflow run provenance preview', () => {
  // contract-test: direct surface=gui.web assertions=workflows.chat-delivery.run-provenance
  test('uses the workflow embed card and opens on click', async ({ page }: { page: import('@playwright/test').Page }) => {
    await page.goto('/dev/preview/embeds/workflows/WorkflowRunEmbedPreview?theme=light&width=900&chrome=0', { waitUntil: 'networkidle' });
    const card = page.getByTestId('workflow-run-embed-preview');
    await expect(card).toBeVisible();
    await expect(card).toContainText('Workflow run');
    const shell = page.getByTestId('embed-preview');
    await expect(shell).toHaveAttribute('data-app-id', 'workflows');
    await shell.click();
    await expect.poll(() => page.evaluate(() => document.body.dataset.workflowRunOpened)).toBe('true');
  });

  // contract-test: direct surface=gui.web assertions=workflows.chat-delivery.run-provenance
  test('shows a legacy run link as an embed preview inside a delivered chat message', async ({ page }: { page: import('@playwright/test').Page }) => {
    await page.goto('/dev/preview/ChatMessage?variant=workflowRun&theme=light&width=900&chrome=0', { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-run-provenance')).toBeVisible();
    await expect(page.getByTestId('workflow-run-embed-preview')).toBeVisible();
    await expect(page.getByText('Here are the upcoming events.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'View workflow run' })).toBeHidden();
  });
});
