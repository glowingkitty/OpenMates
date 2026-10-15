// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright fixtures use CommonJS. */
export {};
import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';
const { expect, test } = require('../helpers/cookie-audit');

for (const width of [1280, 390]) {
  // contract-test: direct surface=gui.web assertions=workflows-ui.workspace.guest-template-preview,workflows-ui.template.centered-in-place-editor,workflows-ui.responsive-accessible-reachable
  test(`guest template uses the actual node editor with signup and a working close at ${width}px`, async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width, height: 900 });
    const writes: string[] = [];
    page.on('request', request => {
      if (request.url().includes('/v1/workflows') && request.method() !== 'GET') writes.push(request.url());
    });
    const query = new URLSearchParams({ variant: 'guestTemplate', theme: 'light', width: String(width), chrome: '0' });
    await page.goto(`/dev/preview/workflows/WorkflowGraphRenderer?${query}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await page.evaluate(() => {
      const counters = { signup: 0, saves: 0 };
      Object.assign(window, { guestWorkflowCounters: counters });
      window.addEventListener('workflow-guest-preview-signup', () => { counters.signup += 1; });
      window.addEventListener('workflow-guest-preview-save', () => { counters.saves += 1; });
    });
    const node = page.locator('[data-node-id="events"]');
    await node.getByTestId('workflow-node-summary').click();
    const editor = node.getByTestId('workflow-node-expanded');
    await expect(editor).toBeVisible();
    await expect(editor.getByTestId('workflow-editor-primary-icon')).toBeVisible();
    await expect(editor.getByTestId('workflow-input-heading')).toBeVisible();
    // Real schema form and request fields replace the generic value/details viewer.
    await expect(editor.locator('.schema-field').first()).toBeVisible();
    await expect(editor.getByRole('textbox', { name: 'Query', exact: true })).toHaveValue('AI');
    await expect(editor.getByRole('textbox', { name: 'Query', exact: true })).toBeDisabled();
    await expect(editor.locator('[contenteditable="true"]')).toHaveCount(0);
    // A fieldset is a group, so Playwright's actionable-control disabled matcher does not apply.
    // Assert its native property alongside the real Query control's disabled behavior above.
    await expect(editor.locator('fieldset.editor-fields')).toHaveJSProperty('disabled', true);
    await expect(editor.getByTestId('workflow-node-save')).toHaveCount(0);
    await expect(editor.getByTestId('workflow-node-delete')).toHaveCount(0);
    await expect(editor.getByTestId('workflow-node-move-up')).toHaveCount(0);
    await expect(editor.getByTestId('workflow-test-action')).toBeDisabled();
    const signup = editor.getByRole('button', { name: 'Signup', exact: true });
    await expect(editor.getByTestId('workflow-guest-customize')).toContainText('Signup to customize workflow');
    await signup.scrollIntoViewIfNeeded();
    await expect(signup).toBeVisible();
    await signup.click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { guestWorkflowCounters: { signup: number; saves: number } }).guestWorkflowCounters)).toEqual({ signup: 1, saves: 0 });
    const close = editor.getByRole('button', { name: 'Close', exact: true });
    await close.scrollIntoViewIfNeeded();
    await expect(close).toBeVisible();
    await close.click();
    await expect(editor).toHaveCount(0);
    await node.getByTestId('workflow-node-summary').click();
    await expect(node.getByTestId('workflow-node-expanded').getByRole('textbox', { name: 'Query', exact: true })).toHaveValue('AI');
    // Rich message inputs also stay read-only; native fieldset disabled does not cover contenteditable.
    const message = page.locator('[data-node-id="message"]');
    await message.getByTestId('workflow-node-summary').click();
    await expect(message.locator('.tiptap')).toBeVisible();
    await expect(message.locator('[contenteditable="true"]')).toHaveCount(0);
    expect(writes).toEqual([]);
    await expect(page.getByTestId('workflow-add-step')).toHaveCount(0);
  });
}
