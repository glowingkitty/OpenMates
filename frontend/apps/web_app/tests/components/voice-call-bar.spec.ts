// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant?: string, width = 1180) =>
  `/dev/preview/voicecall/VoiceCallBar?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), ...(variant ? { variant } : {}) })}`;

test.describe('Integrated voice call controls', () => {
  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.audio.single-owner,video-call.lifecycle.recovery-and-billing
  test('shows a ready call, usage and keyboard-accessible audio controls', async ({ page }) => {
    await page.goto(preview());
    await waitForComponentPreview(page);
    const bar = page.getByTestId('voice-call-bar');
    await expect(bar).toBeVisible();
    await expect(bar).toContainText('Via Google Gemini');
    await expect(page.getByTestId('voice-call-timer')).toHaveText('0:32');
    await expect(page.getByTestId('voice-call-usage')).toContainText('28 credits/min');
    await expect(bar).toHaveCSS('background-image', /linear-gradient/);
    await expect(bar).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(page.getByTestId('voice-call-mute')).toHaveCSS('color', 'rgb(255, 255, 255)');
    const indicator = page.getByTestId('voice-call-indicator');
    await expect(indicator).toBeVisible();
    await expect(indicator).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    expect((await indicator.boundingBox())!.width).toBeGreaterThanOrEqual(10);
    expect((await bar.boundingBox())!.height).toBeLessThan(140);
    await page.getByTestId('voice-call-mute').focus();
    await expect(page.getByTestId('voice-call-mute')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('voice-call-mute')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('voice-call-status')).toContainText('Microphone muted');
    await page.getByTestId('voice-call-minimize').click();
    await expect(bar).toHaveClass(/compact/);
    await expect(page.getByTestId('voice-call-hangup')).toBeVisible();
    await page.getByTestId('voice-call-hangup').click();
    await expect(bar).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.chat.fixed-binding
  test('keeps Connecting and estimated Gemini rate visible before ready', async ({ page }) => {
    await page.addInitScript(() => {
      window.addEventListener('voice-call-preview-return', (event) => {
        (window as unknown as { voiceCallReturn?: string }).voiceCallReturn = (event as CustomEvent<{ chatId: string }>).detail.chatId;
      });
    });
    await page.goto(preview('connecting'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('voice-call-status')).toContainText('Wait to speak');
    await expect(page.getByTestId('voice-call-usage')).toContainText('28 credits/min');
    await expect(page.getByTestId('voice-call-mute')).toHaveCount(0);
    await expect(page.getByTestId('voice-call-bar')).toHaveCSS('color', 'rgb(255, 255, 255)');
    expect((await page.getByTestId('voice-call-bar').boundingBox())!.height).toBeLessThan(140);
    await page.getByTestId('voice-call-return').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { voiceCallReturn?: string }).voiceCallReturn)).toBe('preview-chat');
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.fixed-binding,video-call.audio.single-owner
  test('retains return and hangup controls in compact phone and away states', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      window.addEventListener('voice-call-preview-return', (event) => {
        (window as unknown as { voiceCallReturn?: string }).voiceCallReturn = (event as CustomEvent<{ chatId: string }>).detail.chatId;
      });
    });
    await page.goto(preview('away', 390));
    await waitForComponentPreview(page);
    const bar = page.getByTestId('voice-call-bar');
    await expect(bar).toHaveClass(/compact/);
    const bounds = await bar.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(391);
    expect(bounds!.height).toBeLessThan(240);
    await expect(bar).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(page.getByTestId('voice-call-indicator')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    await expect(page.getByTestId('voice-call-return')).toBeVisible();
    await expect(page.getByTestId('voice-call-hangup')).toBeVisible();
    await page.getByTestId('voice-call-return').click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { voiceCallReturn?: string }).voiceCallReturn)).toBe('preview-chat');
  });

  // contract-test: direct surface=gui.web assertions=video-call.chat.launch-and-provider,video-call.audio.single-owner
  test('keeps expanded phone controls, timer and rate inside the viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview(undefined, 390));
    await waitForComponentPreview(page);
    const bar = page.getByTestId('voice-call-bar');
    await expect(bar).toBeVisible();
    await expect(page.getByTestId('voice-call-status')).toContainText('Listening');
    await expect(page.getByTestId('voice-call-timer')).toBeVisible();
    await expect(page.getByTestId('voice-call-usage')).toContainText('28 credits/min');
    await expect(bar).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(page.getByTestId('voice-call-hangup')).toHaveCSS('color', 'rgb(255, 255, 255)');
    await expect(page.getByTestId('voice-call-indicator')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
    expect((await bar.boundingBox())!.height).toBeLessThan(220);
    for (const name of ['voice-call-mute', 'voice-call-minimize', 'voice-call-hangup']) {
      const control = page.getByTestId(name);
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    }
  });
});
