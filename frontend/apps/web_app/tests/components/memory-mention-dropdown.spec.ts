import {expect, test} from '../helpers/cookie-audit';
import {waitForComponentPreview} from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=app-memories.compatibility.legacy-documents,app-memories.conversation.explicit-approval
test('selects a migrated private Memory explicitly at phone width', async ({page}, testInfo) => {
  const diagnostics: string[] = [];
  page.on('console', message => {
    if (['warning', 'error'].includes(message.type())) diagnostics.push(message.text().slice(0, 800));
  });
  page.on('pageerror', error => diagnostics.push(error.message.slice(0, 800)));
  try {
  await page.setViewportSize({width: 390, height: 844});
  await page.addInitScript(() => window.addEventListener('preview-memory-selected', event => {
    (window as unknown as {selectedMemory: unknown}).selectedMemory = (event as CustomEvent).detail;
  }));
  await page.goto('/dev/preview/enter_message/MentionDropdown?chrome=0&theme=light&background=%23dbeafe&width=350');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('mention-dropdown')).toBeVisible();
  const row = page.getByRole('option', {name: /Mobile preference/});
  await expect(row).toBeVisible();
  const bounds = await row.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await expect(page.getByText('Synthetic private memory; select this entry explicitly.')).toHaveCount(0);
  await page.getByTestId('mention-dropdown').focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => page.evaluate(() => (window as unknown as {selectedMemory: {mentionSyntax?: string}}).selectedMemory?.mentionSyntax)).toBe('@memory-entry:openmates:memories:account-memory-preview-mobile');
  await testInfo.attach('private-memory-explicit-selection', {body: await page.screenshot(), contentType: 'image/png'});
  } finally {
    await testInfo.attach('mention-preview-diagnostics', {body: Buffer.from(diagnostics.join('\n').slice(0, 8_000)), contentType: 'text/plain'});
  }
});

// contract-test: supporting surface=gui.web assertions=app-memories.conversation.explicit-approval
test('expands a private category and selects only its named Memory', async ({page}) => {
  await page.addInitScript(() => window.addEventListener('preview-memory-selected', event => {
    (window as unknown as {selectedMemory: unknown}).selectedMemory = (event as CustomEvent).detail;
  }));
  await page.goto('/dev/preview/enter_message/MentionDropdown?chrome=0&theme=light&background=%23dbeafe&width=600&variant=category');
  await waitForComponentPreview(page);
  const category = page.getByRole('option', {name: /Memories.*Personal/});
  await expect(category).toBeVisible();
  await expect(category.getByTestId('mention-entry-count')).toHaveText('1');
  await category.getByTestId('mention-expand-button').click();
  await page.getByRole('option', {name: /Mobile preference/}).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as {selectedMemory: {mentionSyntax?: string}}).selectedMemory?.mentionSyntax)).toBe('@memory-entry:openmates:memories:account-memory-preview-mobile');
});
