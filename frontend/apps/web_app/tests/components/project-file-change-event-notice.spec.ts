import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/ProjectFileChangeEventNotice?chrome=0&width=360';

// contract-test: supporting surface=gui.web assertions=projects.files.write-policy-enforcement,projects.surface.semantic-parity
test('shows one projects/change embed row as a quiet chat-history line', async ({ page }, testInfo) => {
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  const row = page.getByTestId('project-file-change-event');
  await expect(row).toContainText('Project file changed: web-app/package.json');
  await expect(row).toHaveAttribute('data-paths', 'web-app/package.json');
  await expect(row.getByTestId('project-file-change-diff')).toHaveCount(0);
  expect((await row.getByRole('note').boundingBox())!.height).toBeLessThan(80);
  await testInfo.attach('project-file-change-one', { body: await row.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.files.write-policy-enforcement,projects.surface.semantic-parity
test('summarises a projects/change embed with several rows in one line', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&variant=several`);
  await waitForComponentPreview(page);
  const row = page.getByTestId('project-file-change-event');
  await expect(row).toContainText('3 Project files changed');
  await expect(row).toHaveAttribute('data-paths', 'web-app/package.json,web-app/package-lock.json,web-app/src/main.ts');
  await testInfo.attach('project-file-change-several', { body: await row.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.files.exact-patch,projects.surface.semantic-parity
test('expands the per-file diff with View changes', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&variant=several`);
  await waitForComponentPreview(page);
  const row = page.getByTestId('project-file-change-event');
  await row.getByRole('button', { name: 'View changes' }).click();
  await expect(row.getByTestId('project-file-change-diff')).toHaveCount(3);
  await expect(row.getByTestId('project-file-change-diff').first()).toContainText('+new');
  await expect(row).toContainText('web-app/src/main.ts');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await testInfo.attach('project-file-change-expanded', { body: await row.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.files.write-policy-enforcement,projects.surface.semantic-parity
test('after a reload there is no live diff, so View changes opens the file instead of expanding', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&variant=reloaded`);
  await waitForComponentPreview(page);
  const row = page.getByTestId('project-file-change-event');
  await expect(row).toContainText('Project file changed: web-app/package.json');
  await row.getByRole('button', { name: 'View changes' }).click();
  await expect(row.getByTestId('project-file-change-diff')).toHaveCount(0);
  await testInfo.attach('project-file-change-reloaded', { body: await row.screenshot(), contentType: 'image/png' });
});
