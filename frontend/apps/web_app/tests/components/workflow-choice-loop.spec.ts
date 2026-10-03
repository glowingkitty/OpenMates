// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page, Route } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');

async function preview(page: Page, variant: string): Promise<void> {
  await page.goto(`/dev/preview/workflows/WorkflowGraphRenderer?${new URLSearchParams({ variant, theme:'light', width:'900', chrome:'0' })}`, { waitUntil:'domcontentloaded' });
  await waitForComponentPreview(page);
}

test.describe('Workflow choices and loop scope', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.check.options,workflows.control.choice-check
  test('preserves option IDs and populated branches while editing labels and order', async ({ page }: { page: Page }) => {
    let saved: { nodes: Array<{ id: string; config: Record<string, unknown> }>; edges: Array<{ from: string; branch?: string }> } | undefined;
    await page.route('**/v1/workflows/preview-workflow', async (route: Route) => {
      saved = route.request().postDataJSON().graph;
      await route.fulfill({ json: {} });
    });
    await preview(page, 'choiceCheck');
    await expect(page.locator('[data-branch="option:bring_coat"]')).toContainText('Bring a coat');
    await expect(page.locator('[data-branch="option:take_umbrella"]')).toBeVisible();
    await expect(page.locator('[data-branch="no_match"]')).toBeVisible();
    await expect(page.locator('[data-branch="unsure"]')).toBeVisible();
    await page.locator('[data-node-id="rain"]').getByTestId('workflow-node-summary').click();
    const editor = page.getByTestId('workflow-node-expanded');
    await expect(editor.getByTestId('workflow-check-result-type')).toContainText('Multiple choice');
    await expect(editor.getByTestId('workflow-check-selection-mode')).toContainText('All that apply');
    await editor.locator('[data-option-id="bring_coat"] input').first().fill('Wear a coat');
    await editor.locator('[data-option-id="bring_coat"]').getByRole('button', { name:'Move step down Wear a coat' }).click();
    await editor.getByTestId('workflow-node-save').click();
    await expect.poll(() => saved?.nodes.find(node => node.id === 'rain')?.config.options).toMatchObject([
      { id:'take_umbrella', label:'Take an umbrella' }, { id:'bring_coat', label:'Wear a coat' },
    ]);
    expect(saved?.nodes.find(node => node.id === 'rain')?.config).toMatchObject({ question:'{{steps.weather.rain_probability}}', selected_inputs:['$nodes.weather.output.rain_probability'] });
    expect(saved?.edges).toContainEqual({ from:'rain', to:'message', branch:'option:bring_coat' });
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.for-each,workflows.control.for-each
  test('shows the item source only in the loop body and keeps continuation separate', async ({ page }: { page: Page }) => {
    await preview(page, 'forEachBody');
    await expect(page.getByTestId('workflow-loop-body')).toContainText('For each item');
    await page.locator('[data-node-id="message"]').getByTestId('workflow-node-summary').click();
    await expect(page.locator('[data-source-node-id="loop"]')).toBeVisible();
    await page.locator('[data-source-node-id="loop"]').click();
    await expect(page.locator('[data-variable-reference="$items.loop.item.title"]')).toBeVisible();
    const itemIndex = page.locator('[data-variable-reference="$items.loop.index"]');
    if (await itemIndex.count() === 0) await page.getByTestId('workflow-variable-picker').getByRole('button', { name:'Show all' }).click();
    await expect(itemIndex).toBeVisible();
    await page.getByTestId('workflow-node-expanded').getByRole('button', { name:'Close', exact:true }).click();
    await page.locator('[data-node-id="after"]').getByTestId('workflow-node-summary').click();
    await expect(page.locator('[data-source-node-id="loop"]')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.for-each,workflows.control.for-each
  test('offers a loop for a declared start input list', async ({ page }: { page: Page }) => {
    await preview(page, 'forEachStartInput');
    await page.getByTestId('workflow-add-step').click();
    await expect(page.getByTestId('workflow-step-for-each')).toBeVisible();
    await page.getByTestId('workflow-step-for-each').click();
    await expect(page.getByTestId('workflow-for-each-items')).toContainText('Results');
    await expect(page.getByTestId('workflow-node-save')).toBeEnabled();
  });
});
