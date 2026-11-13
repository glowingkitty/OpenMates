// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
//
// Code file editor (CodeEditor) in the component preview: typing, Tab indent,
// dirty indicator, save and cancel callbacks. The real save is proven by the
// Projects real-stack E2E.
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const PREVIEW = '/dev/preview/embeds/code/CodeEditor';
const url = (variant = '') => `${PREVIEW}?${new URLSearchParams({ variant, chrome: '0', width: '880' })}`;

// contract-test: supporting surface=gui.web assertions=projects.items.create-documents
test('edits code with Tab indent, shows the dirty state and keeps Save disabled until changed', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1000, height: 700 });
  await page.goto(url());
  await waitForComponentPreview(page);

  const editor = page.getByTestId('code-editor');
  const textarea = page.getByTestId('code-editor-textarea');
  await expect(editor).toBeVisible();
  await expect(textarea).toHaveValue(/export function add/);
  await expect(page.getByTestId('code-editor-save')).toBeDisabled();
  await testInfo.attach('code-editor-viewer', { body: await page.screenshot(), contentType: 'image/png' });

  await textarea.click();
  await page.keyboard.press('Control+End');
  await page.keyboard.press('Tab');
  await page.keyboard.type('// edited');
  await expect(textarea).toHaveValue(/\n {2}\/\/ edited$/);
  await expect(editor).toHaveAttribute('data-dirty', 'true');
  await expect(page.getByTestId('code-editor-save')).toBeEnabled();

  await page.keyboard.press('Shift+Tab');
  await expect(textarea).toHaveValue(/\n\/\/ edited$/);
  await page.keyboard.press('Tab');
  await testInfo.attach('code-editor-edited', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.items.create-documents
test('shows a conflict error with a reload action', async ({ page }) => {
  await page.goto(url('conflict'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('code-editor-error')).toContainText('changed elsewhere');
  await expect(page.getByTestId('code-editor-reload')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=projects.items.create-documents
test('cancel without changes needs no confirmation', async ({ page }) => {
  await page.goto(url('blank'));
  await waitForComponentPreview(page);
  await page.getByTestId('code-editor-textarea').press('Escape');
  await expect(page.getByTestId('code-editor-error')).toHaveCount(0);
});
