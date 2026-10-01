// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page, Route } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');

async function openCheck(page: Page, variant = 'comparisonCheck', width = 900): Promise<void> {
  await page.goto(`/dev/preview/workflows/WorkflowGraphRenderer?${new URLSearchParams({ variant, theme:'light', width:String(width), chrome:'0' })}`, { waitUntil:'domcontentloaded' });
  await waitForComponentPreview(page);
  await page.locator('[data-node-id="rain"]').getByTestId('workflow-node-summary').click();
}
async function select(page: Page, id: string, name: string | RegExp): Promise<void> {
  await page.getByTestId(id).click();
  await page.getByRole('option', { name, exact:typeof name === 'string' }).click();
}

test.describe('Workflow If editor', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.website-change.composition,workflows.website-change.baseline
  test('explains a blocked website read in run detail', async ({ page }: { page: Page }) => {
    await page.goto('/dev/preview/workflows/WorkflowGraphRenderer?variant=websiteBlocked&theme=light&width=900&chrome=0', { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const read = page.locator('[data-node-id="read"]');
    await read.getByTestId('workflow-node-summary').click();
    await expect(read.locator('.error')).toHaveText('This website blocked the read. The last successful version was kept.');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.website-change.composition,workflows.website-change.diff-inputs
  test('offers website change fields through existing exact and AI Checks with baseline guidance', async ({ page }: { page: Page }) => {
    let saved: { nodes: Array<{ id: string; config: Record<string, unknown> }> } | undefined;
    await page.route('**/v1/workflows/preview-workflow', async (route: Route) => {
      saved = route.request().postDataJSON().graph;
      await route.fulfill({ json: {} });
    });
    await openCheck(page, 'websiteChange');
    await expect(page.getByTestId('workflow-check-variable')).toContainText('Has changed since last successful read');
    await expect(page.getByTestId('workflow-website-change-guidance')).toContainText('first successful read');
    await expect(page.getByTestId('workflow-website-change-guidance')).toContainText('Failed or blocked reads');
    await page.getByTestId('workflow-check-variable').click();
    await expect(page.getByRole('option', { name: /Changes since last successful read/ })).toBeVisible();
    await page.keyboard.press('Escape');
    await page.getByTestId('workflow-node-save').click();
    expect(saved?.nodes.find(node => node.id === 'rain')?.config.predicate).toEqual({ op: 'eq', left: '$nodes.read.output.has_changed', right: true });
    await openCheck(page, 'websiteAiChange');
    await expect(page.getByTestId('workflow-check-source')).toContainText('AI confirms');
    await expect(page.getByTestId('workflow-website-change-guidance')).toBeVisible();
    await page.locator('[data-source-node-id="read"]').click();
    await expect(page.locator('[data-variable-reference="$nodes.read.output.changes"]')).toHaveText('Changes since last successful read');
    await expect(page.locator('[data-variable-reference="$nodes.read.output.has_changed"]')).toHaveText('Has changed since last successful read');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.if-editor.authored-conditions,workflows.control.typed-data
  test('compares compatible outputs from two earlier app nodes with branded dropdowns', async ({ page }: { page: Page }) => {
    let savedGraph: { nodes:Array<{ id:string; config:Record<string,unknown> }> } | undefined;
    await page.route('**/v1/workflows/preview-workflow', async (route: Route) => {
      savedGraph = route.request().postDataJSON().graph;
      await route.fulfill({ json:{} });
    });
    await openCheck(page);
    const editor = page.getByTestId('workflow-node-expanded');
    await expect(editor.getByRole('heading', { name:'If', exact:true })).toBeVisible();
    await expect(editor.getByTestId('workflow-check-source')).toContainText('Weather');
    await editor.getByTestId('workflow-check-source').click();
    await expect(page.getByRole('option', { name:'AI confirms', exact:true })).toBeVisible();
    await expect(page.getByRole('option', { name:/News/ })).toHaveCount(0);
    await expect(page.getByRole('option').first().locator('.option-icon')).toBeVisible();
    await page.keyboard.press('Escape');
    await select(page,'workflow-check-operator','is more than');
    await select(page,'workflow-check-compare-source',/Paris/);
    await page.getByTestId('workflow-check-compare-variable').click();
    await expect(page.getByRole('option', { name:/Rain Expected/ })).toHaveCount(0);
    await page.getByRole('option', { name:'Rain Probability', exact:true }).click();
    await expect(editor.getByTestId('workflow-node-save')).toBeEnabled();
    await editor.screenshot({ animations:'disabled', path:test.info().outputPath('if-output-comparison.png') });
    await editor.getByTestId('workflow-node-save').click();
    await expect.poll(() => savedGraph?.nodes.find(node => node.id === 'rain')?.config).toMatchObject({ mode:'exact', predicate:{ left:'$nodes.weather.output.rain_probability', op:'gt', right:'$nodes.second_forecast.output.rain_probability' } });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.if-editor.authored-conditions,workflows.ai-check.single-call-billing,workflows.control.ai-check
  test('shows rejected question errors for Save and Test then preserves an Unsure result', async ({ page }: { page: Page }) => {
    let hints = 0;
    let tests = 0;
    page.on('request', request => { if (request.url().includes('/ai-authoring/hints')) hints += 1; });
    await page.route('**/v1/workflows/preview-workflow', (route: Route) => route.fulfill({ status:422, json:{ detail:{ code:'WORKFLOW_AI_CHECK_NOT_BOOLEAN', node_id:'rain' } } }));
    await page.route('**/v1/workflows/preview-workflow/steps/rain/test', (route: Route) => {
      tests += 1;
      return route.fulfill({ json:{ run:{ id:`check-test-${tests}`, status:tests === 1 ? 'failed' : 'completed', credit_cost:1, node_runs:[{ node_id:'rain', status:tests === 1 ? 'failed' : 'completed', error_summary:tests === 1 ? 'WORKFLOW_AI_CHECK_NOT_BOOLEAN' : null, credit_cost:1, output_summary:tests === 1 ? {} : { decision:'unsure', branch:'unsure' } }] } } });
    });
    await openCheck(page,'aiCheckTestable');
    const question = page.getByTestId('workflow-message-template');
    await question.fill('Summarize this weather @Weather');
    await page.getByTestId('workflow-variable-sources').locator('[data-source-node-id="weather"]').click();
    await page.getByTestId('workflow-ai-suggestions').getByRole('button', { name:/Rain Probability/ }).click();
    await expect(page.getByTestId('workflow-save-validation-cost')).toHaveText('Save validation · 1 credit');
    await page.getByTestId('workflow-node-save').click();
    await expect(page.getByRole('alert')).toHaveText('Enter a question that can be answered True or False.');
    await expect(question).toContainText('Summarize this weather');
    await page.getByTestId('workflow-test-action').click();
    await expect(page.getByRole('alert')).toHaveText('Enter a question that can be answered True or False.');
    await question.fill('Will it rain? @Weather');
    await page.getByTestId('workflow-ai-suggestions').getByRole('button', { name:/Rain Probability/ }).click();
    await page.getByTestId('workflow-test-action').click();
    await expect(page.getByTestId('workflow-check-test-result')).toHaveText('Test output: Unsure');
    await expect(page.locator('.branch-label')).toHaveText(['If true','Else','If unsure']);
    expect(tests).toBe(2);
    expect(hints).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.if-editor.authored-conditions,workflows-ui.responsive-accessible-reachable
  test('keeps the If controls reachable by keyboard on a phone and returns to Next step', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width:390, height:844 });
    await openCheck(page,'comparisonCheck',390);
    const [icon, control] = await Promise.all([page.getByTestId('workflow-editor-primary-icon').boundingBox(), page.getByTestId('workflow-node-delete').boundingBox()]);
    expect(icon!.y).toBeGreaterThan(control!.y + control!.height);
    await expect(page.getByRole('button', { name:'Next step', exact:true }).locator('span')).toBeHidden();
    const source = page.getByTestId('workflow-check-source');
    await source.focus();
    await page.keyboard.press('ArrowDown');
    const popup = page.getByRole('listbox');
    await expect(popup).toBeVisible();
    const box = await popup.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(391);
    await page.keyboard.press('End');
    await page.keyboard.press('Enter');
    await expect(source).toContainText('AI confirms');
    await expect(page.getByTestId('workflow-message-template')).toBeVisible();
    expect(await page.getByTestId('workflow-message-template').locator('p').first().evaluate(element => getComputedStyle(element, '::before').textAlign)).toBe('start');
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.getByTestId('workflow-node-expanded').screenshot({ animations:'disabled', path:test.info().outputPath('if-ai-confirms-phone.png') });
    await page.getByRole('button', { name:'Next step', exact:true }).click();
    await expect(page.getByTestId('workflow-step-menu')).toBeVisible();
    await expect(page.getByTestId('workflow-step-menu').locator('.choice')).toHaveText(['Use app','Ask AI','Add check','Send message']);
  });
});
