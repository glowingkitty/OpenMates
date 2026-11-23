import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/projects/ProjectReferenceEmbedPreview?chrome=0&width=320';

async function open(page: import('@playwright/test').Page, variant: string) {
  await page.goto(`${PREVIEW}&variant=${variant}`);
  await waitForComponentPreview(page);
  return page.getByTestId('project-reference-preview');
}

// contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
test('one read file shows the Project name then the file, with the Read files title and an eye icon', async ({ page }, testInfo) => {
  const card = await open(page, 'readOne');
  await expect(page.getByTestId('project-reference-project')).toHaveText('Recipe Manager');
  await expect(page.getByTestId('project-reference-row')).toHaveText(['README.md']);
  await expect(page.locator('body')).toContainText('Read files');
  await expect(page.locator('body')).not.toContainText('Read Project File');
  await expect(page.locator('body')).not.toContainText('file references');
  await testInfo.attach('project-read-one', { body: await page.screenshot(), contentType: 'image/png' });
  await expect(card).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
test('several read files are listed as a folder tree', async ({ page }, testInfo) => {
  await open(page, 'readSeveral');
  await expect(page.getByTestId('project-reference-project')).toHaveText('Recipe Manager');
  await expect(page.getByTestId('project-reference-row')).toHaveText(
    ['docs', 'guide.md', 'README.md', 'src', 'main.py']);
  await expect(page.getByTestId('project-reference-more')).toHaveCount(0);
  await testInfo.attach('project-read-several', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
test('more files than fit show +N more', async ({ page }, testInfo) => {
  await open(page, 'readMany');
  await expect(page.getByTestId('project-reference-more')).toHaveText('+5 more');
  // The "+N more" line must be visible inside the fixed-height card, not cut off below it.
  const card = await page.getByTestId('project-reference-preview').locator('xpath=ancestor::*[@data-testid="embed-preview"][1]').boundingBox()
    ?? await page.getByTestId('project-reference-preview').boundingBox();
  const more = await page.getByTestId('project-reference-more').boundingBox();
  expect(card && more && more.y + more.height <= card.y + card.height, 'the +N more line fits inside the card').toBeTruthy();
  await testInfo.attach('project-read-many', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
test('search counts use proper singular and plural', async ({ page }) => {
  await page.goto(`${PREVIEW}&variant=searchOne`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-reference-preview')).toContainText('1 file reference');
  await expect(page.getByTestId('project-reference-preview')).not.toContainText('1 file references');
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('project-reference-preview')).toContainText('2 file references');
});
