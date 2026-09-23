import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/ProjectFileApprovalCard?chrome=0';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.addEventListener('project-file-preview-decision', (event) => {
      document.documentElement.dataset.projectFileDecision = String((event as CustomEvent<boolean>).detail);
    });
  });
});

// contract-test: supporting surface=gui.web assertions=projects.files.write-policy-enforcement,projects.files.exact-patch,projects.surface.semantic-parity
test('shows the concrete patch before an explicit keyboard approval', async ({ page }, testInfo) => {
  await page.goto(`${PREVIEW}&width=520`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('project-file-approval-card');
  await expect(card).toContainText('src/greeting.ts');
  await expect(page.getByTestId('project-file-change-diff')).toContainText('+export const greeting = "Hello, world!";');
  await expect(page.locator('html')).not.toHaveAttribute('data-project-file-decision');
  await page.getByTestId('project-file-approve').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-project-file-decision', 'true');
  await testInfo.attach('project-file-write-approval', { body: await card.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=projects.files.ignored-exact-inclusion,projects.files.write-policy-enforcement,projects.surface.semantic-parity
test('limits ignored-read consent to one file and shows applied changes without approval buttons', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREVIEW}&variant=ignoredRead&width=350`);
  await waitForComponentPreview(page);
  const card = page.getByTestId('project-file-approval-card');
  await expect(card).toContainText('logs/build.log');
  await expect(card).toContainText('Other ignored files remain excluded');
  await page.getByTestId('project-file-reject').click();
  await expect(page.locator('html')).toHaveAttribute('data-project-file-decision', 'false');
  await testInfo.attach('project-file-read-approval-mobile', { body: await card.screenshot(), contentType: 'image/png' });
  await page.goto(`${PREVIEW}&variant=applied&width=350`);
  await waitForComponentPreview(page);
  await expect(card).toHaveAttribute('data-status', 'applied');
  await expect(page.getByTestId('project-file-approve')).toHaveCount(0);
  await card.locator('summary').click();
  await expect(page.getByTestId('project-file-change-diff')).toBeVisible();
});
