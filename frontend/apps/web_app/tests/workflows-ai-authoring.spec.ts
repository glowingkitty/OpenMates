/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
/** AI authoring in the authenticated workspace, with deterministic paid-validation responses. */
export {};
import type { Page, Route } from '@playwright/test';
const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost' ? 'http://localhost:8000' : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

test.describe('Workflow AI authoring', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.mvp.ask-ai,workflows-ui.if-editor.authored-conditions,workflows.ai-ask.validation-billing,workflows.ai-check.single-call-billing
  test('keeps typing local, shows paid Save errors, and offers AI confirms with Unsure', async ({ page }: { page: Page }) => {
    test.setTimeout(180_000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:workflows']);
    await page.goto(getE2EDebugUrl('/'), { waitUntil:'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});
    const graph = { version:2, trigger_node_id:null, nodes:[{ id:'events', type:'app_skill_action', title:'Events search', config:{ app_id:'events', skill_id:'search', input:{ requests:[{ query:'Design events in Berlin' }] } } }], edges:[] };
    const response = await page.request.post(`${apiUrl()}/v1/workflows`, { data:{ title:`Workflow AI authoring ${Date.now()}`, graph, enabled:false } });
    expect(response.ok()).toBe(true);
    const { workflow } = await response.json();
    let hints = 0;
    let saves = 0;
    page.on('request', request => { if (request.url().includes('/ai-authoring/hints')) hints += 1; });
    // Provider inference is exercised on dev; CI covers the real frontend Save and its server errors.
    await page.route(`**/v1/workflows/${workflow.id}`, async (route: Route) => {
      if (route.request().method() !== 'PATCH') { await route.continue(); return; }
      saves += 1;
      await route.fulfill({ status:422, json:{ detail:{ code:saves === 1 ? 'WORKFLOW_AI_ASK_REQUIRES_APP_ACTION' : 'WORKFLOW_AI_CHECK_NOT_BOOLEAN' } } });
    });
    try {
      await page.goto(getE2EDebugUrl(`/#workflow-id=${workflow.id}&workflow-tab=details`), { waitUntil:'domcontentloaded' });
      await expect(page.getByTestId('workspace-detail-title')).toHaveText(workflow.title, { timeout:30_000 });
      await page.getByTestId('workflow-add-step').click();
      await expect(page.getByTestId('workflow-step-menu').locator('.choice')).toHaveText(['Use app','Ask AI','Add check','Send message']);
      await page.getByTestId('workflow-step-ask-ai').click();
      const instruction = page.getByTestId('workflow-message-template');
      await instruction.fill('Search for new events @Events');
      await expect(instruction).toBeFocused();
      await expect(instruction).not.toHaveCSS('caret-color', 'rgba(0, 0, 0, 0)');
      await expect(instruction.locator('.workflow-mention-query')).toHaveText('@Events');
      await page.getByTestId('workflow-variable-sources').locator('[data-source-node-id="events"]').click();
      await page.getByTestId('workflow-ai-suggestions').getByRole('button', { name:/Results/ }).first().click();
      await expect(instruction.locator('.generic-mention')).toHaveCount(1);
      await expect(page.getByTestId('workflow-save-validation-cost')).toHaveText('Save validation · 1 credit');
      await page.getByTestId('workflow-node-save').click();
      await expect(page.getByRole('alert')).toContainText("You can't ask for using app skills here");
      await expect(instruction).toContainText('Search for new events');
      await page.getByRole('button', { name:'Close', exact:true }).click();
      await page.getByTestId('workflow-add-step').click();
      await page.getByTestId('workflow-step-menu').getByText('Add check', { exact:true }).click();
      await page.getByTestId('workflow-check-source').click();
      await page.getByRole('option', { name:'AI confirms', exact:true }).click();
      await expect(page.getByRole('heading', { name:'If', exact:true })).toBeVisible();
      await instruction.fill('Summarize the events @Events');
      await expect(instruction).toBeFocused();
      await expect(instruction).not.toHaveCSS('caret-color', 'rgba(0, 0, 0, 0)');
      await page.getByTestId('workflow-variable-sources').locator('[data-source-node-id="events"]').click();
      await page.getByTestId('workflow-ai-suggestions').getByRole('button', { name:/Results/ }).first().click();
      await page.getByTestId('workflow-node-save').click();
      await expect(page.getByRole('alert')).toHaveText('Enter a question that can be answered True or False.');
      await expect(instruction.locator('.generic-mention')).toHaveCount(1);
      expect(saves).toBe(2);
      expect(hints).toBe(0);
    } finally {
      await page.unroute(`**/v1/workflows/${workflow.id}`);
      await page.request.delete(`${apiUrl()}/v1/workflows/${encodeURIComponent(workflow.id)}`).catch(() => null);
    }
  });
});
