// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant?: string, width = 680) =>
  `/dev/preview/chats/QueuedFollowupControls?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), ...(variant ? { variant } : {}) })}`;

test.describe('Queued follow-up controls', () => {
  // contract-test: direct surface=gui.web assertions=chat-queued-followups.admission.synced,chat-queued-followups.steering.safe-boundary
  test('shows queued state and exposes separate edit and steer actions', async ({ page }) => {
    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('queued-followup-controls')).toHaveAttribute('data-queue-mode', 'follow_up');
    await expect(page.getByTestId('queued-followup-status')).toHaveText('Queued');
    await page.evaluate(() => {
      (window as typeof window & { queuedPreviewActions?: string[] }).queuedPreviewActions = [];
      window.addEventListener('queuedFollowupPreviewAction', (event) => {
        (window as typeof window & { queuedPreviewActions: string[] }).queuedPreviewActions.push((event as CustomEvent).detail.action);
      });
    });
    await page.getByTestId('queued-followup-edit').click();
    await page.getByTestId('queued-followup-steer').click();
    await expect.poll(() => page.evaluate(() => (window as typeof window & { queuedPreviewActions: string[] }).queuedPreviewActions)).toEqual(['edit', 'steer']);
  });

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.steering.safe-boundary,chat-queued-followups.editing.stable-revision
  test('shows steering state and blocks actions while a revision is pending', async ({ page }) => {
    await page.goto(preview('steering', 390));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('queued-followup-status')).toHaveText('Steering current response');
    await expect(page.getByTestId('queued-followup-steer')).toHaveCount(0);
    await page.goto(preview('updating', 390));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('queued-followup-controls')).toHaveAttribute('aria-busy', 'true');
    await expect(page.getByTestId('queued-followup-edit')).toBeDisabled();
    await expect(page.getByTestId('queued-followup-steer')).toBeDisabled();
  });

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.editing.stable-revision
  test('keeps a revision conflict visible near the queued message', async ({ page }) => {
    await page.goto(preview('conflict'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('queued-followup-error')).toHaveAttribute('role', 'alert');
    await expect(page.getByTestId('queued-followup-error')).toContainText('another device');
    await expect(page.getByTestId('queued-followup-edit')).toBeEnabled();
  });

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.access.scoped
  test('hides queued edit and steer actions for another Team member', async ({ page }) => {
    await page.goto('/dev/preview/ChatMessage?variant=teamRemoteQueued&chrome=0&theme=light&background=%23dbeafe');
    const canvas = await waitForComponentPreview(page);
    const remoteMessage = canvas.getByTestId('remote-human-message');
    await expect(remoteMessage).toContainText('queued follow-up');
    await expect(remoteMessage.getByTestId('queued-followup-controls')).toHaveCount(0);
    await remoteMessage.getByTestId('mate-message-content').click({ button: 'right' });
    await expect(page.getByTestId('message-context-menu')).toBeVisible();
    await expect(page.getByTestId('message-context-menu').locator('.menu-item.edit')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=chat-queued-followups.admission.synced
  test('shows a saved message whose assistant handoff paused without queued actions', async ({ page }) => {
    await page.goto('/dev/preview/ChatMessage?variant=teamOwnPaused&chrome=0&theme=light&background=%23dbeafe');
    const canvas = await waitForComponentPreview(page);
    const message = canvas.locator('.chat-message');
    await expect(message.getByTestId('queued-followup-paused')).toContainText('assistant could not continue');
    await expect(message.getByTestId('queued-followup-controls')).toHaveCount(0);
    await message.getByTestId('user-message-content').click({ button: 'right' });
    await expect(page.getByTestId('message-context-menu')).toBeVisible();
    await expect(page.getByTestId('message-context-menu').locator('.menu-item.edit')).toHaveCount(0);
  });
});
