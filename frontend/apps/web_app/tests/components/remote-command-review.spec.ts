import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/projects/RemoteCommandReviewCard?chrome=0&width=350';

// contract-test: supporting surface=gui.web assertions=code-run.remote.explicit-approval,code-run.remote.managed-jobs,projects.surface.semantic-parity
test('reviews the exact command, requires approval, and provides Stop while running', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    window.addEventListener('remote-command-preview-decision', (event) => {
      document.documentElement.dataset.commandDecision = (event as CustomEvent<string>).detail;
    });
  });
  await page.goto(PREVIEW);
  await waitForComponentPreview(page);
  const card = page.getByTestId('remote-command-review-card');
  await expect(card).toContainText('Runs the greeting test suite');
  await expect(page.getByTestId('remote-command-target')).toContainText('Greeting app · Development laptop');
  await expect(page.getByTestId('remote-command-argv')).toContainText('src/greeting.test.ts');
  await expect(card).toContainText('Read and write');
  await expect(page.locator('html')).not.toHaveAttribute('data-command-decision');
  await page.getByTestId('remote-command-approve').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-command-decision', 'approve');
  await testInfo.attach('remote-command-review-mobile', { body: await card.screenshot(), contentType: 'image/png' });

  await page.goto(`${PREVIEW}&variant=running`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('remote-command-approve')).toHaveCount(0);
  await expect(page.getByTestId('remote-command-output')).toContainText('Running greeting tests');
  await page.getByTestId('remote-command-stop').click();
  await expect(page.locator('html')).toHaveAttribute('data-command-decision', 'stop');

  await page.goto(`${PREVIEW}&variant=succeeded`);
  await waitForComponentPreview(page);
  await expect(card).toHaveAttribute('data-status', 'succeeded');
  await expect(page.getByTestId('remote-command-stop')).toHaveCount(0);
  await expect(page.getByTestId('remote-command-output')).toContainText('2 tests passed');
});
