// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};
import type { Page } from '@playwright/test';

const { expect, test } = require('../helpers/cookie-audit');
const preview = (variant?: string) => `/dev/preview/workflows/WorkflowBindingReview?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: '430', ...(variant ? { variant } : {}) })}`;

test.describe('Imported Workflow binding review', () => {
  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.composer-drop-import,workflows.portability.disabled-validated-import
  test('shows each required binding, edits the corresponding step, and blocks confirmation while unsaved', async ({ page }: { page: Page }) => {
    await page.goto(preview(), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-binding-item')).toHaveCount(2);
    await expect(page.getByTestId('workflow-binding-review')).toContainText('Chat destination');
    const geometry = await page.getByTestId('workflow-binding-review').evaluate(element => ({ scroll: element.scrollWidth, client: element.clientWidth }));
    expect(geometry.scroll).toBeLessThanOrEqual(geometry.client);
    const fontSize = await page.getByTestId('workflow-binding-review').locator('small').first().evaluate(element => parseFloat(getComputedStyle(element).fontSize));
    expect(fontSize).toBeGreaterThanOrEqual(14);
    const edit = page.evaluate(() => new Promise<string>(resolve => window.addEventListener('workflow-preview-edit-binding', event => resolve((event as CustomEvent<string>).detail), { once: true })));
    await page.getByTestId('workflow-binding-item').nth(1).getByTestId('workflow-binding-edit').click();
    await expect(edit).resolves.toBe('step_2');
    const confirmation = page.evaluate(() => new Promise<string>(resolve => window.addEventListener('workflow-preview-confirm-binding', event => resolve((event as CustomEvent<string>).detail), { once: true })));
    await page.getByTestId('workflow-binding-item').nth(1).getByTestId('workflow-binding-confirm').click();
    await expect(confirmation).resolves.toBe('step_2');
    await page.goto(preview('unsaved'), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-binding-confirm').first()).toBeDisabled();
    await expect(page.getByTestId('workflow-binding-review')).toContainText('Save your changes');
    await page.goto(preview('partial'), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-binding-review')).toContainText('Confirmed');
    await expect(page.getByTestId('workflow-binding-confirm')).toHaveCount(1);
  });
});
