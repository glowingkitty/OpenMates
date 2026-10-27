// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// The fixture intercepts startup after the real ActiveChat/MessageInput controls.
// Registration, providers and exact persisted draft ownership use voice-call.spec.ts.
for (const { width, direction } of [
  { width: 390, direction: 'ltr' },
  { width: 1280, direction: 'ltr' },
  { width: 390, direction: 'rtl' },
]) {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.audio.single-owner,video-call.chat.project-context
  test(`starts once from the focused welcome composer at ${width}px ${direction}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/dev/preview/voicecall/ActiveChatCallHeaderPreview?${new URLSearchParams({
      chrome: '0', theme: 'light', background: '#dbeafe', width: String(width),
      variant: direction === 'rtl' ? 'focusedDraftRtl' : 'focusedDraft',
    })}`);
    await waitForComponentPreview(page);
    const fixture = page.getByTestId('active-chat-call-header-preview');
    const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]');
    await expect(fixture).toHaveAttribute('data-start-count', '0');
    await expect(fixture).toHaveAttribute('data-call-status', 'idle');
    await editor.click();
    await expect(editor).toBeFocused();
    const handset = page.locator('.welcome-focused-call-actions [data-testid="voice-call-start"]');
    await expect(handset).toBeVisible();
    await expect(handset).toBeEnabled();
    await expect.poll(() => handset.evaluate(node => node.closest('[inert]') === null)).toBe(true);
    for (const hiddenWelcome of ['welcome-content', 'daily-inspiration-area']) {
      await expect(page.getByTestId(hiddenWelcome)).toBeHidden();
      await expect(page.getByTestId(hiddenWelcome)).toHaveAttribute('inert', '');
    }
    await expect(handset.getByTestId('voice-call-handset')).toHaveAttribute('data-icon', 'audiocall');
    const bounds = await handset.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    await handset.focus();
    await expect(handset).toBeFocused();
    await editor.click();
    await expect(editor).toBeFocused();
    await expect(handset).toBeVisible();
    // Native click includes pointerdown; its focus change must not replace the
    // focused toolbar before the subsequent click reaches startup.
    await handset.click();
    await expect(fixture).toHaveAttribute('data-start-count', '1');
    await expect(fixture).toHaveAttribute('data-start-target', 'new-chat');
    await expect(fixture).toHaveAttribute('data-call-status', 'connecting');
    await expect(page.getByTestId('voice-call-bar')).toBeVisible();
    await expect(page.getByTestId('chat-top-actions')).toBeHidden();
    await expect(page.getByTestId('chat-top-actions')).toHaveAttribute('inert', '');
    await expect(page.getByTestId('voice-call-composer-hint')).toHaveCount(0);
    await expect.poll(async () => {
      const [bar, chat] = await Promise.all([
        page.getByTestId('voice-call-bar').boundingBox(), page.getByTestId('chat-side').boundingBox(),
      ]);
      return bar && chat ? Math.abs(bar.y - chat.y) : Infinity;
    }, { message: 'Connecting controls must start at the top of the new chat' }).toBeLessThanOrEqual(1);
    await expect(page.getByTestId('assistant-speech-player')).toHaveCount(0);
    await expect(page.getByTestId('assistant-message-speak')).toHaveCount(0);
    const cancel = page.getByTestId('voice-call-hangup');
    await expect(cancel).toBeVisible();
    await expect(cancel).toBeEnabled();
    for (const hiddenWelcome of ['welcome-content', 'daily-inspiration-area']) {
      await expect(page.getByTestId(hiddenWelcome)).toBeHidden();
      await expect(page.getByTestId(hiddenWelcome)).toHaveAttribute('inert', '');
    }
    await expect.poll(() => cancel.evaluate(button => {
      const bounds = button.getBoundingClientRect();
      const hit = document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
      return hit === button || (hit !== null && button.contains(hit));
    })).toBe(true);
    await cancel.click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
    await expect(fixture).toHaveAttribute('data-call-status', 'ended');
    await expect(fixture).toHaveAttribute('data-start-count', '1');
  });
}
