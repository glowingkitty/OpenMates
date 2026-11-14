import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=plans.chat-settings.active-plan
test('Chat settings show the active Plan with its Tasks, Checks, assumptions and approval', async ({ page }) => {
  await page.goto('/dev/preview/chats/ChatSettingsPreviewHarness?chrome=0');
  await waitForComponentPreview(page);
  const panel = page.getByTestId('chat-active-plan-panel');
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute('data-approval-state', 'approved');
  await expect(page.getByTestId('chat-active-plan-task')).toHaveCount(3);
  await expect(page.locator('[data-testid="chat-active-plan-task"][data-status="in_progress"]')).toHaveCount(1);
  await expect(page.getByTestId('chat-active-plan-check')).toHaveCount(3);
  await expect(page.locator('[data-testid="chat-active-plan-check"][data-status="waiting_for_confirmation"]')).toHaveCount(1);
  await expect(page.getByTestId('chat-active-plan-assumption')).toHaveCount(2);
  await expect(page.getByTestId('chat-active-plan-open')).toBeVisible();
});
