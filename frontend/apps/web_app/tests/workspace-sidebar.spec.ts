/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers expose CommonJS exports. */
/**
 * Active workspace sidebar coverage.
 *
 * Purpose: verifies the Workflows hamburger drawer renders workflow rows and
 * opens a focused editor instead of falling back to chat navigation.
 * Security: creates and deletes only the workflow seeded by this test.
 */

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function deriveApiUrl(baseUrl: string): string {
  try {
    const url = new URL(baseUrl);
    if (url.hostname === 'openmates.org' || url.hostname === 'www.openmates.org') return 'https://api.openmates.org';
    if (url.hostname.startsWith('app.')) return `${url.protocol}//api.${url.hostname.slice(4)}`;
    if (url.hostname === 'localhost') return 'http://localhost:8000';
  } catch {
    // Fall through to the production API default.
  }
  return 'https://api.openmates.org';
}

test.describe('Workspace sidebar', () => {
  test('opens a workflow from the mobile workspace drawer', async ({ page }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);

    const apiUrl = deriveApiUrl(process.env.PLAYWRIGHT_TEST_BASE_URL || '');
    const title = `Sidebar workflow ${Date.now()}`;
    let workflowId = '';
    const log = (message: string, metadata: Record<string, unknown> = {}) => {
      console.log(`[WORKSPACE_SIDEBAR_E2E] ${message} ${JSON.stringify(metadata)}`);
    };
    const screenshot = async () => {};

    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, log, screenshot);

    try {
      const createResponse = await page.request.post(`${apiUrl}/v1/workflows`, {
        data: {
          title,
          graph: { version: 1, nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual', config: {} }], edges: [] },
          enabled: false,
        },
      });
      expect(createResponse.ok()).toBe(true);
      workflowId = (await createResponse.json()).workflow.id;

      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
      await page.getByTestId('sidebar-toggle').click();

      const sidebar = page.getByTestId('workflows-sidebar');
      await expect(sidebar).toBeVisible();
      const workflowRow = sidebar.getByTestId('workflow-sidebar-row').filter({ hasText: title });
      await expect(workflowRow).toBeVisible({ timeout: 30000 });
      await workflowRow.click();
      await expect(page.getByTestId('workflow-editor')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('workflow-title-input')).toHaveValue(title);
    } finally {
      if (workflowId) await page.request.delete(`${apiUrl}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
    }
  });
});
