import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/RuleDocumentManager?chrome=0&theme=light&background=%23dbeafe';

// First preview load in a fresh CI Vite server compiles and optimizes dependencies on demand.
const COLD_START_MS = 75_000;

test.beforeEach(async ({ page }) => {
  test.setTimeout(COLD_START_MS + 30_000);
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
  await waitForComponentPreview(page, COLD_START_MS);
  const manager = page.getByTestId('rule-document-manager');
  await page.getByTestId('memory-row').filter({ hasText: 'Testing best practices' }).click();
  await expect(page.getByTestId('memories-editor')).toHaveAttribute('data-page', 'entry');
  await expect(page.getByTestId('rule-title')).toHaveValue('Testing best practices');
  const body = page.getByTestId('rule-body');
  await expect(body).toContainText('Assert caller-visible outcomes.');
  await expect(body).toContainText('Keep disposable test data separate.');
  await body.click();
  await page.keyboard.press('Control+A');
  for (const [index, line] of ['- Assert caller-visible outcomes.', '- Exercise error paths.', '- Keep disposable test data separate.'].entries()) {
    if (index) await page.keyboard.press('Enter');
    await page.keyboard.type(line);
  }
  await page.getByTestId('rule-save').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('rule-saved-notice')).toHaveText('Memory saved.');
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-source', 'personal');
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', /when_to_use:.*\n---\n- Assert caller-visible outcomes\./s);
  // Saving stamps the save times and returns to the list.
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', /\ncreated_at: \d+\nupdated_at: \d+\n/);
  await expect(page.getByTestId('memories-editor')).toHaveAttribute('data-page', 'list');
  await expect(manager).not.toContainText('[T:');
  await testInfo.attach('personal-rule-edit-save', { body: await manager.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted,app-memories.definition.context-documents
test('keeps scope, labels and fields usable on a narrow Project layout', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREVIEW}&variant=project&width=350`);
  await waitForComponentPreview(page, COLD_START_MS);
  const manager = page.getByTestId('rule-document-manager');
  await expect(page.getByTestId('rule-scope-project')).toHaveAttribute('aria-pressed', 'true');
  await expect(manager).toContainText('Project Memories are encrypted Markdown files and load when relevant while this chat has active Project access.');
  await expect(page.getByTestId('memory-row')).toHaveCount(1);
  await page.getByTestId('memory-create').click();
  await expect(page.getByTestId('memory-entry-page')).toHaveAttribute('data-new', 'true');
  await expect(page.getByLabel('When to use')).toBeVisible();
  await expect(page.getByTestId('rule-save')).toBeVisible();
  expect(await manager.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.getByTestId('rule-scope-personal').click();
  await expect(page.getByTestId('rule-scope-personal')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('memories-editor')).toHaveAttribute('data-page', 'list');
  await testInfo.attach('rule-scope-manager-mobile', { body: await manager.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.privacy.client-encrypted
test('shows failed persistence without a false saved notice', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=error&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  await page.getByTestId('memory-row').click();
  await page.getByTestId('rule-save').click();
  await expect(page.getByTestId('memory-error')).toHaveText('Could not load or save the Memories. Please try again.');
  await expect(page.getByTestId('rule-saved-notice')).toHaveCount(0);
  await expect(page.getByTestId('rule-save')).toBeEnabled();
});

// contract-test: supporting surface=gui.web assertions=app-memories.load-modes,app-memories.expiry.client-enforced
test('edits load mode and expiry, shows Private label, budget and a Renew action for expired memories', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=expired&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('memory-char-budget')).toContainText('/ 64000 characters used');
  const rows = page.getByTestId('memory-row');
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: 'Testing best practices' })).toContainText('Private');
  await expect(rows.filter({ hasText: 'Testing best practices' })).not.toContainText('Expired');
  await expect(rows.filter({ hasText: 'Old travel plan' })).toContainText('Private · Expired');
  await expect(page.getByTestId('memory-renew')).toHaveCount(1);
  await page.getByTestId('memory-renew').click();
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', /title: Old travel plan\nload_mode: ask_first\nvalid_until: 20\d\d-/);
  await expect(page.getByTestId('memories-editor')).toHaveAttribute('data-page', 'list');
  await page.getByTestId('memory-row').first().click();
  await page.getByTestId('memory-load-mode').selectOption('mention_only');
  await page.getByTestId('memory-valid-until').fill('2099-01-31');
  await page.getByTestId('rule-save').click();
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', /load_mode: mention_only\nvalid_until: 2099-01-31T23:59:59/);
});

// contract-test: supporting surface=gui.web assertions=app-memories.definition.context-documents
test('deep link draft is shown as an unsaved diff and not saved automatically', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=deeplink&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  await expect(page.getByTestId('memory-draft-banner')).toBeVisible();
  await expect(page.getByTestId('rule-title')).toHaveValue('Testing habits');
  await expect(page.getByTestId('memory-draft-diff-title')).toContainText('Testing best practices');
  await expect(page.locator('html')).not.toHaveAttribute('data-rule-saved-document', /.+/);
});

// contract-test: direct surface=gui.web assertions=app-memories.references.embeds
test('references embeds inline in the Memory text, with no separate reference field', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&variant=embed&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  const manager = page.getByTestId('rule-document-manager');
  await page.getByTestId('memory-row').filter({ hasText: 'Launch plan' }).click();
  const body = page.getByTestId('rule-body');
  await expect(body).toContainText('Check the launch page:');
  await expect(body).toContainText('Then announce it.');
  await expect(body.getByRole('button')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Add embed by ID' })).toHaveCount(0);
  await expect(manager).not.toContainText('[T:');
  await page.getByTestId('rule-save').click();
  await expect(page.getByTestId('rule-saved-notice')).toHaveText('Memory saved.');
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', /references:\s+- kind: embed\s+id: preview-embed/);
  await testInfo.attach('memory-inline-embed', { body: await manager.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=app-memories.document.canonical-shape,app-memories.lifecycle.encrypted-crud
test('creates a memory on its own page with an optional app and returns to the sorted list', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&width=650`);
  await waitForComponentPreview(page, COLD_START_MS);
  const manager = page.getByTestId('rule-document-manager');
  await expect(page.getByTestId('rule-document-form')).toHaveCount(0);
  await expect(page.getByTestId('rule-title')).toHaveCount(0);
  await page.getByTestId('memory-create').click();
  await expect(page.getByTestId('memory-entry-page')).toHaveAttribute('data-new', 'true');
  await expect(page.getByTestId('memory-delete')).toHaveCount(0);
  await expect(manager).toContainText('Memory');
  await expect(manager).not.toContainText('Markdown)');
  await page.getByTestId('rule-title').fill('Kitchen renovation');
  await page.getByTestId('rule-body').click();
  await page.keyboard.type('Keep the oak floor.');
  const app = page.getByTestId('memory-app');
  await expect(app).toHaveValue('');
  const firstApp = await app.locator('option').nth(1).getAttribute('value');
  expect(firstApp).toMatch(/^[a-z][a-z0-9_]*$/);
  await app.selectOption(firstApp!);
  await testInfo.attach('memory-create-page', { body: await manager.screenshot(), contentType: 'image/png' });
  await page.getByTestId('rule-save').click();
  await expect(page.locator('html')).toHaveAttribute('data-rule-saved-document', new RegExp(`\\ncreated_at: (\\d+)\\nupdated_at: \\1\\napp_id: ${firstApp}\\n---\\nKeep the oak floor\\.`));
  await expect(page.getByTestId('rule-saved-notice')).toHaveText('Memory saved.');
  const row = page.getByTestId('memory-row').filter({ hasText: 'Kitchen renovation' });
  await expect(row).toContainText(/Private · Modified /);
  await expect(page.getByTestId('memory-sort')).toHaveValue('modified');
  await testInfo.attach('memory-list-after-create', { body: await manager.screenshot(), contentType: 'image/png' });
});
