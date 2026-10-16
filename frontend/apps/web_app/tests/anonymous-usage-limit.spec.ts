/* eslint-disable @typescript-eslint/no-require-imports */
export {};
const { test, expect } = require('./helpers/cookie-audit');
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// These browser fixtures exercise client limit handling without provider inference.
for (const partial of [false, true]) {
  // contract-test: direct surface=gui.web assertions=billing.anonymous.hard-capped-provider-metering,message-input.privacy-context,chats.streaming.ordered-final,billing.anonymous.local-only-content
  test(`guest limit ${partial ? 'after partial work' : 'before provider dispatch'} shows notification and Sign up`, async ({ page }: { page: any }) => {
    const availability = { active: true, can_send_text: true, reason: null,
      reset_at: new Date(Date.now() + 3600000).toISOString() };
    await page.route('**/v1/settings/server-status', (route: any) => route.fulfill({ json: {
      is_self_hosted: false, server_edition: 'development', ai_models_configured: true,
      anonymous_free_usage: availability,
    } }));
    // Deliberately leave this stale: the stream's admission decision is authoritative.
    await page.route('**/v1/anonymous/free-usage/status**', (route: any) => route.fulfill({ json: availability }));
    let sends = 0;
    const partialContent = 'Completed useful work.\u0085Preserved line separator\u2028and paragraph separator\u2029content.\n\nMedical advice is informational; consult a qualified professional.';
    await page.route('**/v1/anonymous/chat/stream', async (route: any) => {
      sends++;
      const body = route.request().postDataJSON();
      const taskId = `anonymous-task-${body.client_message_id}`;
      const messageId = 'anonymous-limit-assistant';
      const chunk = { type: 'ai_message_chunk', chat_id: body.client_chat_id,
        user_message_id: body.client_message_id, message_id: messageId, task_id: taskId };
      const frames = [
        { type: 'ai_task_initiated', chat_id: body.client_chat_id, user_message_id: body.client_message_id, ai_task_id: taskId, status: 'processing_started' },
        { type: 'ai_typing_started', chat_id: body.client_chat_id, user_message_id: body.client_message_id,
          message_id: messageId, task_id: taskId, category: 'general_knowledge', model_name: null,
          provider_name: null, server_region: null },
        ...(partial ? [{ ...chunk, sequence: 1, is_final_chunk: false, full_content_so_far: partialContent }] : []),
        { ...chunk, sequence: partial ? 2 : 1, is_final_chunk: true, rejection_reason: 'anonymous_usage_limit',
          full_content_so_far: `${partial ? `${partialContent}\n\n` : ''}Create an account to keep using OpenMates.` },
        { type: 'ai_task_ended', chatId: body.client_chat_id, taskId, status: 'failed' },
      ];
      await route.fulfill({ status: 200, contentType: 'text/event-stream',
        body: frames.map(frame => `data: ${JSON.stringify(frame)}\n\n`).join('') });
    });
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
    await editor.click();
    await editor.pressSequentially('A guest request');
    await expect(editor).toBeFocused();
    await expect(editor).toHaveText('A guest request');
    await page.locator('[data-action="send-message"]').click();
    const answer = page.getByTestId('message-assistant').last();
    await expect(answer).toHaveAttribute('data-streaming', 'false', { timeout: 30000 });
    await expect(answer).toContainText('Create an account to keep using OpenMates.');
    if (partial) {
      await expect(answer).toContainText('Completed useful work.');
      await expect(answer).toContainText('Preserved line separator');
      await expect(answer).toContainText('and paragraph separator');
      await expect(answer).toContainText('Medical advice is informational');
    }
    await expect(answer).not.toContainText('The AI service encountered an error');
    const notice = page.getByTestId('notification').filter({ hasText: "You've reached the free usage limit." });
    await expect(notice).toBeVisible();
    await expect(notice.getByTestId('notification-action')).toHaveText('Sign up');
    await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
    await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
    await editor.click();
    await editor.pressSequentially('Continue this chat');
    await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
    const signup = page.locator('[data-action="sign-up-to-send"]');
    await expect(signup).toBeVisible();
    expect(sends).toBe(1);
    await signup.click();
    await expect(page.getByTestId('login-tabs')).toBeVisible();
    await expect(page.getByTestId('tab-signup')).toHaveClass(/\bactive\b/);
  });
}
