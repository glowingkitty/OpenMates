// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { focusComposer } from '../helpers/composer-focus';

test.setTimeout(120_000);

for (const fixture of [
  { embedId: '7512b6cf-f568-4197-a008-1f0aea7431b6', chatId: 'example-ai-workshops-meetups-berlin', title: 'OpenClaw Anonymous Berlin #9', type: 'event' },
  { embedId: '0dd5bef4-2dd6-4374-96ed-e8130bc7270d', chatId: 'example-habit-garden-web-application', title: 'main.js', type: 'code' },
]) {
  // contract-test: direct surface=gui.web assertions=message-input.suggestions.contextual,public-example-chats.transcript.safe-rendering
  test(`opens public ${fixture.type} content without replacing the draft`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto('/dev/preview/ActiveChat?chrome=0&width=1200&theme=dark');
    await waitForComponentPreview(page);
    const chat = page.getByTestId('active-chat-container');
    const editor = page.getByTestId('message-editor').getByRole('textbox', { includeHidden: true });
    const field = page.getByTestId('message-field');
    await focusComposer(page);
    await expect(editor).toBeVisible();
    await editor.fill('Keep my draft while I inspect this public result');
    // Dismiss through the real draft flush before capturing the new local chat.
    await page.getByTestId('input-dismiss-button').click();
    await expect(field).toHaveAttribute('data-focused', 'false');
    await focusComposer(page);
    await expect(editor).toHaveText('Keep my draft while I inspect this public result');
    const currentChatId = await chat.getAttribute('data-current-chat-id');

    await page.evaluate(({ embedId, chatId, type }) => {
      document.dispatchEvent(new CustomEvent('embedfullscreen', { detail: {
        embedId, embedType: type, exampleChatId: chatId,
        hasChatContext: false, sourceChatId: null,
      } }));
    }, fixture);
    const fullscreen = page.getByTestId('embed-fullscreen-container');
    await expect(fullscreen).toBeVisible({ timeout: 30000 });
    await expect(fullscreen).toContainText(fixture.title, { timeout: 30000 });
    if (fixture.type === 'code') await expect(fullscreen.getByTestId('code-fullscreen-code')).toContainText("import { mount } from 'svelte';");
    await expect(chat).not.toHaveAttribute('data-current-chat-id', fixture.chatId);
    if (currentChatId) await expect(chat).toHaveAttribute('data-current-chat-id', currentChatId);
    await fullscreen.getByTestId('embed-minimize').click();
    await expect(fullscreen).toHaveCount(0);
    await expect(editor).toHaveText('Keep my draft while I inspect this public result');
    await expect(chat).not.toHaveAttribute('data-current-chat-id', fixture.chatId);
    if (currentChatId) await expect(chat).toHaveAttribute('data-current-chat-id', currentChatId);
  });
}
