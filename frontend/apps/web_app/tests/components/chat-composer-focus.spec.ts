// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

function preview(component: string, width = 680, variant?: string, theme = 'light') {
  return `/dev/preview/${component}?${new URLSearchParams({ theme, background: theme === 'dark' ? '#171717' : '#dbeafe', width: String(width), chrome: '0', ...(variant ? { variant } : {}) })}`;
}

test.describe('Chat composer focus and draft preservation', () => {
  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,message-input.actions.visibility
  test('failed send keeps the expanded draft and accepted retry collapses and blurs', async ({ page }) => {
    const availability = { active: true, can_send_text: true, reason: null };
    await page.route('**/v1/settings/server-status', (route) => route.fulfill({ json: {
      is_self_hosted: false, payment_enabled: true, server_edition: 'development',
      ai_models_configured: true, anonymous_free_usage: availability,
    } }));
    await page.route('**/v1/anonymous/free-usage/status**', (route) => route.fulfill({ json: availability }));
    await page.addInitScript(() => {
      const originalFetch = window.fetch.bind(window);
      const fixture = window as typeof window & { fixtureSendAttempts: number };
      fixture.fixtureSendAttempts = 0;
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        if (!url.includes('/v1/anonymous/chat/stream')) return originalFetch(input, init);
        fixture.fixtureSendAttempts += 1;
        if (fixture.fixtureSendAttempts === 1) return new Response(JSON.stringify({ detail: 'Synthetic send failure' }), {
          status: 503, headers: { 'content-type': 'application/json' },
        });
        await new Promise<void>((resolve) => window.addEventListener('fixtureAcceptSend', () => resolve(), { once: true }));
        return new Response(JSON.stringify({ status: 'completed', messageId: 'synthetic-response', assistant: 'Synthetic response' }), {
          status: 200, headers: { 'content-type': 'application/json' },
        });
      };
    });
    await page.goto(preview('enter_message/MessageInputFocusFixture'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    await field.click();
    await expect(page.getByTestId('composer-send-button')).toBeVisible();
    await expect.poll(async () => {
      const [sendBox, micBox] = await Promise.all([page.getByTestId('composer-send-button').boundingBox(), page.getByTestId('record-audio-button').boundingBox()]);
      return micBox!.x - (sendBox!.x + sendBox!.width);
    }).toBeGreaterThan(0);
    await page.getByTestId('message-expand-button').click();
    await page.getByTestId('composer-send-button').click();
    await expect.poll(() => page.evaluate(() => (window as typeof window & { fixtureSendAttempts: number }).fixtureSendAttempts)).toBe(1);
    await expect(field).toHaveAttribute('data-focused', 'true');
    await expect(field).toHaveClass(/fullscreen-expanded/);
    await expect(editor).toContainText('Unsent multiline');
    await expect(editor).toBeFocused();
    await expect(page.getByTestId('composer-send-button')).toBeVisible();
    await page.getByTestId('composer-send-button').click();
    await expect.poll(() => page.evaluate(() => (window as typeof window & { fixtureSendAttempts: number }).fixtureSendAttempts)).toBe(2);
    await expect(editor).toContainText('second line');
    await page.evaluate(() => window.dispatchEvent(new Event('fixtureAcceptSend')));
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(field).not.toHaveClass(/fullscreen-expanded/);
    await expect(editor).not.toContainText('Unsent multiline');
    await expect(editor).not.toBeFocused();
  });

  // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.layout.responsive-parity,drafts.sync.version-authoritative,drafts.persistence.local-first-encrypted
  test('keeps pending image/audio embeds through autosave, a stale restore and dismissal', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview('enter_message/MessageInputFocusFixture', 390));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    await field.click();
    await expect(field).toHaveAttribute('data-focused', 'true');
    const expand = page.getByTestId('message-expand-button');
    const microphone = page.getByTestId('record-audio-button');
    await expect(expand).toBeVisible();
    await expect(microphone).toBeVisible();
    const [fieldBox, expandBox, micBox] = await Promise.all([field.boundingBox(), expand.boundingBox(), microphone.boundingBox()]);
    expect(expandBox!.x).toBeGreaterThan(fieldBox!.x + fieldBox!.width / 2);
    expect(expandBox!.y).toBeLessThan(micBox!.y);
    await editor.press('ControlOrMeta+End');
    await page.keyboard.type(' autosave change');
    await page.evaluate(() => window.dispatchEvent(new Event('fixtureAddAttachments')));
    await expect(page.getByTestId('embed-full-width-wrapper')).toHaveCount(2);
    // Autosave happens at 1200ms; assert the actual stored draft before replaying an older snapshot.
    await expect.poll(() => page.evaluate(() => (sessionStorage.getItem('draft_synthetic-composer-focus') ?? '').includes('autosave change'))).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event('fixtureRestoreDraft')));
    await expect(page.getByTestId('embed-full-width-wrapper')).toHaveCount(2);
    await expect(editor).toContainText('Unsent multiline');
    await page.getByTestId('fixture-composer-cancel').click();
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(editor).not.toBeFocused();
    await expect(page.getByTestId('embed-full-width-wrapper')).toHaveCount(2);
    await field.click();
    await expand.click();
    await expect(field).toHaveClass(/fullscreen-expanded/);
    await page.mouse.click(2, 2);
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(field).not.toHaveClass(/fullscreen-expanded/);
    await expect(editor).toContainText('second line');
    await expect(page.getByTestId('embed-full-width-wrapper')).toHaveCount(2);
  });

  // contract-test: direct surface=gui.web assertions=drafts.persistence.local-first-encrypted,drafts.draft-only.lifecycle
  test('clears a restored legacy whitespace draft without refilling the field', async ({ page }) => {
    await page.goto(preview('enter_message/MessageInputFocusFixture', 680, 'emptyDraft'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('draft_synthetic-composer-focus'))).toBeNull();
    await expect(page.getByTestId('message-editor').locator('.ProseMirror')).not.toContainText('Unsent multiline');
    await expect(page.getByTestId('embed-full-width-wrapper')).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=drafts.persistence.local-first-encrypted
  test('empty-text cleanup preserves a draft containing a math expression', async ({ page }) => {
    await page.goto(preview('enter_message/MessageInputFocusFixture', 680, 'mathDraft'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    await expect(editor).toContainText('$$x^2 + y^2$$');
    await page.getByTestId('message-field').click();
    await page.getByTestId('fixture-composer-cancel').click();
    await expect(editor).toContainText('$$x^2 + y^2$$');
    await expect.poll(() => page.evaluate(() => (sessionStorage.getItem('draft_synthetic-composer-focus') ?? '').includes('x^2 + y^2'))).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=drafts.persistence.local-first-encrypted,drafts.draft-only.lifecycle
  test('empty-draft cleanup on a chat switch preserves the previous chat draft', async ({ page }) => {
    await page.goto(preview('enter_message/MessageInputFocusFixture'));
    await waitForComponentPreview(page);
    const fixture = page.getByTestId('composer-focus-fixture');
    await expect(fixture).toHaveAttribute('data-ready', 'true');
    await page.getByTestId('message-field').click();
    await expect(page.getByTestId('message-field')).toHaveAttribute('data-focused', 'true');
    await page.getByTestId('message-editor').locator('.ProseMirror').press('ControlOrMeta+End');
    await page.keyboard.type(' saved before switching');
    await page.evaluate(() => window.dispatchEvent(new Event('fixtureSwitchEmptyDraft')));
    await expect(fixture).toHaveAttribute('data-switched', 'true');
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('draft_synthetic-empty-draft'))).toBeNull();
    await expect.poll(() => page.evaluate(() => (sessionStorage.getItem('draft_synthetic-composer-focus') ?? '').includes('saved before switching'))).toBe(true);
    await expect(page.getByTestId('message-editor').locator('.ProseMirror')).not.toContainText('Unsent multiline');
  });

  // contract-test: direct surface=gui.web assertions=drafts.draft-only.presentation,drafts.established-chat.presentation-unchanged
  test('hides the draft-only banner even when a draft title contains attachment JSON', async ({ page }) => {
    await page.goto(preview('ChatHistory', 680, 'draftOnly'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('chat-header-title')).toHaveCount(0);
    await expect(page.getByTestId('draft-chat-badge')).toHaveCount(0);
    await expect(page.locator('.chat-header-wrapper')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('fictional-image');
    await page.goto(preview('ChatHistory'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('chat-header-title')).toContainText('Writing preferences');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  test('shows the first message while the generated chat title is pending', async ({ page }) => {
    await page.goto(preview('ChatHistory', 390, 'titlePending'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('chat-header-provisional-title')).toHaveText(
      'Help me reply to a photography enquiry using my saved writing preferences.'
    );
    await expect(page.getByTestId('chat-header-banner')).not.toContainText('Creating new chat');
    await page.goto(preview('ChatHistory', 390, 'titleReady'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('chat-header-title')).toHaveText('Photography reply');
    await expect(page.getByTestId('chat-header-provisional-title')).toHaveCount(0);
  });

  for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,message-input.layout.responsive-parity
  test(`deep-link prefill hides the empty-chat workspace and outside/Cancel restores it at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.goto(preview('ActiveChatFocusFixture', Math.min(width, 1100), undefined, width === 390 ? 'dark' : 'light'));
    await waitForComponentPreview(page);
    const side = page.getByTestId('chat-side');
    const field = page.getByTestId('message-field');
    // The first guest intro intentionally covers the composer until the visitor
    // advances. Exercise focus restoration on the normal welcome surface.
    await expect(page.getByTestId('landing-intro-expanded')).toBeVisible();
    await page.getByTestId('daily-inspiration-next').click();
    await expect(page.getByTestId('landing-intro-expanded')).toHaveCount(0);
    await expect(page.locator('.chat-wrapper.landing-intro-content-covered')).toHaveCount(0);
    await expect(page.getByTestId('message-input-wrapper')).toHaveCSS('opacity', '1');
    await expect(field).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('docsMessagePrefill', { detail: { text: 'Unsent deep link\nKeep this second line', autoSend: false } })));
    await expect(field).toHaveAttribute('data-focused', 'true');
    await expect(side).toHaveAttribute('inert', '');
    await expect(side).toHaveCSS('opacity', '0');
    await expect(side).toHaveCSS('visibility', 'hidden');
    await expect(side).not.toBeVisible();
    await expect(page.getByTestId('chat-welcome-suggestions')).toHaveCSS('opacity', '0');
    await expect(page.getByTestId('chat-welcome-suggestions')).toHaveAttribute('inert', '');
    await expect(page.getByTestId('new-chat-suggestion-card').first()).toBeHidden();
    await expect(field).toBeVisible();
    await expect(page.getByTestId('input-dismiss-button')).toHaveText('Cancel');
    const cancel = page.getByTestId('input-dismiss-button');
    await expect(cancel).toHaveCSS('border-top-width', '1px');
    await expect.poll(() => page.evaluate(() => {
      const field = document.querySelector('[data-testid="message-field"]')!.getBoundingClientRect();
      const cancel = document.querySelector('[data-testid="input-dismiss-button"]')!.getBoundingClientRect();
      return Math.max(Math.abs(cancel.width - field.width), Math.abs(cancel.x - field.x));
    })).toBeLessThanOrEqual(1);
    const backdrop = page.getByTestId('chat-composer-focus-backdrop');
    await expect.poll(() => backdrop.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const parent = element.parentElement!.getBoundingClientRect();
      return Math.max(Math.abs(box.width - parent.width), Math.abs(box.height - parent.height));
    })).toBeLessThanOrEqual(1);
    await page.screenshot({ path: test.info().outputPath(`chat-welcome-focused-${width}.png`) });
    // Dismiss on the touch gesture itself: iOS may suppress the synthetic click
    // after preventDefault() on pointerdown.
    await backdrop.dispatchEvent('pointerdown', { pointerType: 'touch', button: 0 });
    await expect(backdrop).toHaveCount(0);
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(side).not.toHaveAttribute('inert', '');
    await expect(side).toHaveCSS('opacity', '1');
    await expect(side).toBeVisible();
    await expect(page.getByTestId('message-input-wrapper')).toHaveCSS('opacity', '1');
    await page.screenshot({ path: test.info().outputPath(`chat-welcome-restored-${width}.png`) });
    await expect(page.getByTestId('message-editor').locator('.ProseMirror')).toContainText('Keep this second line');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('docsMessagePrefill', { detail: { text: 'Unsent deep link\nKeep this second line', autoSend: false } })));
    await page.getByTestId('input-dismiss-button').click();
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(page.getByTestId('message-editor').locator('.ProseMirror')).not.toBeFocused();
  });
  }
});
