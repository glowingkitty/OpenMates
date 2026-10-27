// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (width: number, variant = 'pendingHeader') =>
  `/dev/preview/voicecall/VoiceCallBarPreview?${new URLSearchParams({
    chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), variant,
  })}`;

for (const { width, reducedMotion } of [
  { width: 390, reducedMotion: 'no-preference' as const },
  { width: 1280, reducedMotion: 'no-preference' as const },
  { width: 390, reducedMotion: 'reduce' as const },
]) {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-strip-layout,video-call.chat.transcripts,video-call.audio.single-owner
  test(`reveals ready chat metadata above the same live call at ${width}px with ${reducedMotion} motion`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion });
    await page.goto(preview(width));
    await waitForComponentPreview(page);
    const header = page.getByTestId('chat-header-wrapper');
    const history = page.getByTestId('chat-history-container');
    const strip = page.getByTestId('voice-call-strip');
    const mute = page.getByTestId('voice-call-mute');
    const hangup = page.getByTestId('voice-call-hangup');
    await expect(header).toHaveCount(0);
    await expect(page.getByTestId('chat-header-title')).toHaveCount(0);
    await expect(strip).toBeVisible();
    await expect.poll(async () => {
      const [callBounds, historyBounds] = await Promise.all([strip.boundingBox(), history.boundingBox()]);
      return Math.abs(callBounds!.y - historyBounds!.y);
    }, { message: 'The initial calling UI must sit flush with the chat top' }).toBeLessThanOrEqual(1);
    await mute.click();
    await expect(mute).toHaveAttribute('aria-pressed', 'true');
    await page.screenshot({ path: testInfo.outputPath('voice-call-before-title.png') });
    // An early title alone cannot expose a partially generated header.
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('preview:call-header-metadata', {
      detail: { title: 'Cooking ramen together' },
    })));
    await expect(header).toHaveCount(0);
    const heights = await page.evaluate(async () => {
      window.dispatchEvent(new CustomEvent('preview:call-header-metadata', {
        detail: { category: 'food', icon: 'cooking-pot', summary: 'Broth, noodles and toppings.', generating: false },
      }));
      const heights: number[] = [];
      for (let index = 0; index < 24; index++) {
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
        heights.push(document.querySelector('[data-testid="chat-header-wrapper"]')?.getBoundingClientRect().height ?? 0);
      }
      return heights;
    });
    await expect(header).toBeVisible();
    await expect(page.getByTestId('chat-header-title')).toHaveText('Cooking ramen together');
    await expect(page.getByTestId('chat-header-summary')).toContainText('Broth, noodles and toppings.');
    const finalHeight = heights.at(-1)!;
    expect(finalHeight).toBeGreaterThan(100);
    if (reducedMotion === 'reduce') {
      expect(heights.every(height => Math.abs(height - finalHeight) < 1)).toBe(true);
    } else {
      expect(heights.some(height => height > 1 && height < finalHeight - 1),
        'The real header height must expand through intermediate values').toBe(true);
    }
    // Late translated metadata updates the mounted header rather than replacing
    // the live strip, its focus, or its mute state.
    await mute.focus();
    await mute.evaluate(button => button.setAttribute('data-retained-call-control', 'true'));
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('preview:call-header-metadata', {
      detail: { title: 'Gemeinsam Ramen kochen', summary: 'Brühe, Nudeln und Zutaten.', locale: 'de' },
    })));
    await expect(page.getByTestId('chat-header-title')).toHaveText('Gemeinsam Ramen kochen');
    await expect(mute).toHaveAttribute('data-retained-call-control', 'true');
    await expect(mute).toHaveAttribute('aria-pressed', 'true');
    await expect(mute).toBeFocused();
    await expect(page.getByTestId('voice-call-timer')).toHaveText('00:15');
    await history.evaluate(root => { root.scrollTop = root.scrollHeight; });
    await expect(strip).toHaveClass(/stuck/);
    await expect(mute).toBeInViewport({ ratio: 1 });
    await expect(hangup).toBeInViewport({ ratio: 1 });
    await mute.click();
    await expect(mute).toHaveAttribute('aria-pressed', 'false');
    await page.screenshot({ path: testInfo.outputPath('voice-call-ready-header-sticky.png') });
    await hangup.click();
    await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
  });
}

// contract-test: supporting surface=gui.web assertions=video-call.chat.call-strip-layout
test('keeps existing titled calls and normal text-chat loading headers visible', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  // Existing titled chats may have no category or icon metadata.
  await page.goto(preview(1280, 'constrainedMedia'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-header-title')).toHaveText('Call sizing fixture');
  await expect(page.getByTestId('voice-call-bar')).toBeVisible();
  await page.goto(preview(1280));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-header-wrapper')).toHaveCount(0);
  await page.evaluate(() => window.dispatchEvent(new Event('preview:call-header-text-chat')));
  await expect(page.getByTestId('chat-header-wrapper')).toBeVisible();
  await expect(page.getByTestId('voice-call-bar')).toHaveCount(0);
});
