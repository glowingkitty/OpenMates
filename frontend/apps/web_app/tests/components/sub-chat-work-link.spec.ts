import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=plans.sub-chats.assumption-and-task-chats
test('A sub-chat names the assumption it checks or the Task it works on and links back', async ({ page }) => {
  await page.goto('/dev/preview/chats/SubChatWorkLink?chrome=0');
  await waitForComponentPreview(page);
  const link = page.getByTestId('sub-chat-work-link');
  await expect(link).toHaveAttribute('data-kind', 'assumption');
  await expect(link).toContainText('Checks: The announcement channel is available');
  await expect(page.getByTestId('sub-chat-work-link-back')).toBeVisible();
  await link.screenshot({ path: test.info().outputPath('sub-chat-checks.png') });

  await page.goto('/dev/preview/chats/SubChatWorkLink?chrome=0&variant=task');
  await waitForComponentPreview(page);
  await expect(link).toHaveAttribute('data-kind', 'task');
  await expect(link).toContainText('Works on: Review the release checklist');
  await link.screenshot({ path: test.info().outputPath('sub-chat-works-on.png') });
});
