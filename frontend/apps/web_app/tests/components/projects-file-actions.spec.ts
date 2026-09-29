import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (variant: string) => `/dev/preview/projects/ProjectsPage?theme=dark&background=%23181818&width=1512&chrome=0&variant=${variant}`;

// contract-test: supporting surface=gui.web assertions=projects.files.connected-embed-previews
test('connected file cards and list rows expose transfer actions without opening the file', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview('connectedSource'));
  await waitForComponentPreview(page);
  await page.getByTestId('project-remote-entry').filter({ hasText: 'README.md' }).waitFor();

  const file = page.getByTestId('project-remote-entry').filter({ hasText: 'README.md' });
  await file.click({ button: 'right' });
  await expect(page.getByRole('button', { name: 'Download', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Copy', exact: true }).click();
  await expect(page.getByTestId('project-file-commit-transfer')).toHaveText('Paste');
  await page.getByTestId('project-file-cancel-transfer').click();

  await page.getByTestId('project-file-select').click();
  await file.click();
  await expect(file).toHaveClass(/selected/);
  await expect(page.getByTestId('project-embed-viewer')).toHaveCount(0);
  await page.getByTestId('project-remote-entry').filter({ hasText: 'frontend' }).click();
  await expect(page.locator('.selected-count')).toHaveText('2 selected');
  await page.getByTestId('project-file-move-selected').click();
  await expect(page.getByTestId('project-file-commit-transfer')).toHaveText('Move here');
  await page.getByTestId('project-file-cancel-transfer').click();

  await page.getByRole('button', { name: 'List', exact: true }).click();
  await page.getByTestId('project-remote-entry').filter({ hasText: 'frontend' }).click({ button: 'right' });
  await expect(page.getByRole('button', { name: 'Move', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download', exact: true })).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
test('stored Project items offer copy and move selection in the same Files toolbar', async ({ page }) => {
  await page.setViewportSize({ width: 1512, height: 921 });
  await page.goto(preview('folders'));
  await waitForComponentPreview(page);
  const item = page.getByTestId('project-item-card').first();
  await item.waitFor();
  // The shared menu closes on scroll. Bring the card into view before opening
  // it so Playwright does not scroll while moving to the menu action.
  await item.scrollIntoViewIfNeeded();
  await item.click({ button: 'right', position: { x: 12, y: 12 } });
  await expect(page.getByRole('button', { name: 'Move', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Copy', exact: true }).click();
  await expect(page.getByTestId('project-file-commit-transfer')).toHaveText('Paste');
  await page.getByTestId('project-file-cancel-transfer').click();
  await page.getByTestId('project-file-select').click();
  await item.click();
  await expect(page.locator('.stored-item-entry.selected')).toHaveCount(1);
  await expect(page.getByTestId('project-file-copy-selected')).toBeEnabled();
});
