// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: direct surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('renders saved assistant history without live turn metadata or pending feedback', async ({ page }) => {
  const rendererErrors: string[] = [];
  page.on('pageerror', error => rendererErrors.push(error.name));
  await page.goto('/dev/preview/ChatHistory?variant=savedAssistant&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  const history = page.getByTestId('chat-history-content');
  await expect(history).toHaveAttribute('data-source-message-count', '3');
  await expect(history).toHaveAttribute('data-rendered-message-count', '3');
  await expect(page.getByTestId('message-user')).toHaveCount(2);
  await expect(page.getByTestId('message-assistant')).toHaveCount(1);
  await expect(page.getByTestId('message-assistant')).toContainText('Here is the saved photography reply.');
  await expect(page.getByTestId('message-user').last()).toContainText('Please shorten that reply.');
  await expect(page.getByTestId('pending-assistant-response')).toHaveCount(0);
  expect(rendererErrors).toEqual([]);
});

// contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle,chat-processing-feedback.response-container-glow
test('keeps the first assistant active while a newer follow-up sends and becomes queued', async ({ page }) => {
  for (const variant of ['activeResponseSendingFollowUp', 'activeResponseQueuedFollowUp']) {
    await page.goto(`/dev/preview/ChatHistory?variant=${variant}&theme=light&width=680&chrome=0`);
    await waitForComponentPreview(page);
    const assistant = page.getByTestId('message-assistant');
    await expect(assistant.getByTestId('mate-message-content')).toHaveClass(/assistant-response-active/);
    await expect(assistant.getByTestId('using-model')).toBeVisible();
    await expect(assistant.getByTestId('generated-by')).toHaveCount(0);
    await expect(page.getByTestId('message-user').last()).toContainText('Please shorten that reply.');
  }
});
