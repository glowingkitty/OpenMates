// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context
test('loads a missing canonical boundary reply when compressed history has a partial local cache', async ({ page }) => {
  const timestamp = 1788870532;
  let archiveReads = 0;
  await page.route('**/v1/share/chat/demo-preview-compressed-history/messages?**', async route => {
    const query = new URL(route.request().url()).searchParams;
    expect(query.get('checkpoint_id')).toBe('preview-compressed-checkpoint');
    expect(query.get('before_timestamp')).toBe(String(timestamp + 4));
    expect(query.has('before_message_id'), 'Initial canonical archive read includes the checkpoint boundary row').toBe(false);
    archiveReads += 1;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({
      chat_id: 'demo-preview-compressed-history', checkpoint_id: 'preview-compressed-checkpoint',
      messages: [...Array.from({ length: 4 }, (_, index) => ({ message_id: `preview-cached-${index}`,
        chat_id: 'demo-preview-compressed-history', role: index % 2 ? 'assistant' : 'user',
        content: `Cached fictional history ${index}.`, created_at: timestamp + index, status: 'synced' })),
      { message_id: 'preview-boundary-reply', chat_id: 'demo-preview-compressed-history', role: 'assistant',
        content: 'The archived boundary reply is still readable.', created_at: timestamp + 4, status: 'synced' }],
      has_more: false,
    }) });
  });
  await page.goto('/dev/preview/ChatHistory?variant=partialCompressedHistory&theme=light&width=680&chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-history-content')).toHaveAttribute('data-source-message-count', '4');
  const boundaryReply = page.locator('[data-testid="message-assistant"][data-message-id="preview-boundary-reply"]');
  await expect(boundaryReply).toHaveCount(0);
  const toggle = page.getByTestId('show-forgotten-messages');
  await expect(toggle).toContainText('Show old forgotten messages');
  await toggle.click();
  await expect(toggle).toContainText('Hide old forgotten messages');
  await expect.poll(() => archiveReads).toBe(1);
  await expect(boundaryReply).toHaveCount(1);
  // Archived bodies initialize when their actual message enters the clipped
  // history scrollport; reveal the issued row before checking its full text.
  await boundaryReply.scrollIntoViewIfNeeded();
  await expect(boundaryReply).toContainText('The archived boundary reply is still readable.');
  await expect(boundaryReply).toHaveAttribute('data-forgotten', 'true');
  await expect(boundaryReply).toBeVisible();
  await expect(page.locator('[data-forgotten="true"]')).toHaveCount(5);
  await toggle.click();
  await expect(boundaryReply).toHaveCount(0);
});

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
