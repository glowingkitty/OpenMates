// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

const { expect, test } = require('../helpers/cookie-audit');

test.describe('Workflow run provenance preview', () => {
  test.use({ timezoneId: 'UTC' });
  // contract-test: direct surface=gui.web assertions=workflows.chat-delivery.run-provenance
  test('uses the workflow embed card and opens on click', async ({ page }: { page: import('@playwright/test').Page }) => {
    await page.goto('/dev/preview/embeds/workflows/WorkflowRunEmbedPreview?theme=light&width=900&chrome=0', { waitUntil: 'networkidle' });
    const card = page.getByTestId('workflow-run-embed-preview');
    await expect(card).toBeVisible();
    await expect(card).toContainText('Upcoming events');
    await expect(card).toContainText('Find relevant events');
    await expect(card).toContainText('Started');
    const shell = page.getByTestId('embed-preview');
    await expect(shell).toHaveAttribute('data-app-id', 'workflows');
    await expect(shell.getByTestId('embed-app-icon-mask')).toBeVisible();
    await shell.click();
    await expect.poll(() => page.evaluate(() => document.body.dataset.workflowRunOpened)).toBe('true');
  });

  // contract-test: direct surface=gui.web assertions=workflows.chat-delivery.run-provenance
  test('shows the compact trigger and expands into the run preview', async ({ page }: { page: import('@playwright/test').Page }) => {
    await page.goto('/dev/preview/embeds/workflows/WorkflowRunActivity?theme=light&width=900&chrome=0', { waitUntil: 'networkidle' });
    const toggle = page.getByTestId('workflow-run-activity-toggle');
    await expect(toggle).toContainText("Triggered by 'Upcoming events', Oct 11 7:00PM");
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('workflow-run-embed-preview')).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('workflow-run-embed-preview')).toContainText('Find relevant events');
  });

  // contract-test: direct surface=gui.web assertions=workflows.chat-delivery.run-provenance
  test('shows an encrypted run snapshot as expandable activity inside a delivered chat message', async ({ page }: { page: import('@playwright/test').Page }) => {
    await page.goto('/dev/preview/ChatMessage?variant=workflowRun&theme=light&width=900&chrome=0', { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-run-provenance')).toBeVisible();
    const toggle = page.getByTestId('workflow-run-activity-toggle');
    await expect(toggle).toContainText("Triggered by 'Upcoming events'");
    await expect(page.getByTestId('workflow-run-embed-preview')).toHaveCount(0);
    await toggle.click();
    await expect(page.getByTestId('workflow-run-embed-preview')).toContainText('Find relevant events and send a short summary');
    await expect(page.getByText('Here are the upcoming events.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'View workflow run' })).toBeHidden();
  });
});
