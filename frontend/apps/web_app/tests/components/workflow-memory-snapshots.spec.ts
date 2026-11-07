// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

const { expect, test } = require('../helpers/cookie-audit');

// contract-test: supporting surface=gui.web assertions=app-memories.workflows.explicit-snapshots
test('Ask AI step shows a memory chip and the run-time consent notice for a pasted memory mention', async ({ page, context }: { page: import('@playwright/test').Page; context: import('@playwright/test').BrowserContext }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/dev/preview/workflows/WorkflowGraphRenderer?chrome=0&width=900', { waitUntil: 'networkidle' });
  await page.getByTestId('workflow-add-step').last().click();
  await page.getByTestId('workflow-step-ask-ai').click();
  const editor = page.getByTestId('workflow-message-template');
  await editor.focus();
  await page.evaluate(() => navigator.clipboard.writeText('Write in {{memory.m1}} voice'));
  await page.keyboard.press('ControlOrMeta+V');
  await expect(editor.locator('.generic-mention')).toContainText('Memory');
  await expect(page.getByTestId('workflow-memory-snapshot-consent')).toBeVisible();
});
