import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/RuleDocumentManager?chrome=0&theme=light&background=%23dbeafe';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('rule-preview-saved', (event) => {
      const saved = (event as CustomEvent<{ source: string; document: string }>).detail;
      document.documentElement.dataset.ruleSavedSource = saved.source;
      document.documentElement.dataset.ruleSavedDocument = saved.document;
    });
  });
});

// contract-test: supporting surface=gui.web assertions=app-memories.definition.context-documents,app-memories.privacy.client-encrypted
test('edits one coherent personal guide and saves all practices together', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&width=650`);
  await waitForComponentPreview(page);
  const manager = page.getByTestId('rule-document-manager');
  await page.getByTestId('rule-document-edit').click();
  await expect(page.getByTestId('rule-title')).toHaveValue('Testing best practices');
  await expect(page.getByTestId('rule-body')).toHaveValue('- Assert caller-visible outcomes.\n- Keep disposable test data separate.');
  await page.getByTestId('rule-body').fill('- Assert caller-visible outcomes.\n- Exercise error paths.\n- Keep disposable test data separate.');
  await page.getByTestId('rule-save').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('rule-saved-notice')).toHaveText('Memory saved.');
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-source', 'personal');
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', /when_to_use:.*\n---\n- Assert caller-visible outcomes\./s);
  await expect(manager).not.toContainText('[T:');
  await testInfo.attach('personal-rule-edit-save', { body: await manager.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted,app-memories.definition.context-documents
test('keeps scope, labels and fields usable on a narrow Project layout', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREVIEW}&variant=project&width=350`);
  await waitForComponentPreview(page);
  const manager = page.getByTestId('rule-document-manager');
  await expect(page.getByTestId('rule-scope-project')).toHaveAttribute('aria-pressed', 'true');
  await expect(manager).toContainText('Project Memories are encrypted Markdown files and load when relevant while this chat has active Project access.');
  await expect(page.getByLabel('When to use')).toBeVisible();
  await expect(page.getByTestId('rule-save')).toBeVisible();
  expect(await manager.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.getByTestId('rule-scope-personal').click();
  await expect(page.getByTestId('rule-scope-personal')).toHaveAttribute('aria-pressed', 'true');
  await testInfo.attach('rule-scope-manager-mobile', { body: await manager.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted
test('shows failed persistence without a false saved notice', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=error&width=650`);
  await waitForComponentPreview(page);
  await page.getByTestId('rule-document-edit').click();
  await page.getByTestId('rule-save').click();
  await expect(page.getByRole('alert')).toHaveText('Could not load or save the Memories. Please try again.');
  await expect(page.getByTestId('rule-saved-notice')).toHaveCount(0);
  await expect(page.getByTestId('rule-save')).toBeEnabled();
});
