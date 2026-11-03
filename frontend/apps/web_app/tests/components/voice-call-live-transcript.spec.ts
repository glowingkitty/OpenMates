// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// contract-test: direct surface=gui.web assertions=video-call.chat.transcripts
test('live call transcript is translucent, fades in new words and stays display-only', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const variant of ['default', 'submitted', 'belowDraft'] as const) {
    const params = new URLSearchParams({ chrome: '0', theme: 'light', width: '390' });
    if (variant !== 'default') params.set('variant', variant);
    await page.goto(`/dev/preview/enter_message/VoiceCallLiveTranscript?${params}`);
    const canvas = await waitForComponentPreview(page);
    const live = canvas.getByTestId('voice-call-live-transcript');
    await expect(live).toBeVisible();
    await expect(live).toHaveAttribute('aria-live', 'polite');
    await expect(live).toHaveAttribute('data-submitted', String(variant === 'submitted'));
    await expect(live).toHaveText(variant === 'submitted'
      ? 'What is the weather in Berlin tomorrow?' : 'What is the weather in Berlin');
    const style = await live.evaluate((node) => {
      const computed = getComputedStyle(node);
      return { opacity: Number(computed.opacity), pointerEvents: computed.pointerEvents, gridArea: computed.gridArea };
    });
    // Translucent but readable; more opaque once sent for processing.
    expect(style.opacity).toBeGreaterThan(0.3);
    expect(style.opacity).toBeLessThan(variant === 'submitted' ? 0.7 : 0.5);
    expect(style.pointerEvents).toBe('none');
    if (variant === 'belowDraft') expect(style.gridArea).not.toContain('1 / 1');
    const word = canvas.getByTestId('voice-call-live-word').first();
    const animation = await word.evaluate((node) => getComputedStyle(node).animationName);
    if (await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)) expect(animation).toBe('none');
    else expect(animation).toContain('call-live-word-in');
    await page.screenshot({ path: testInfo.outputPath(`live-transcript-${variant}-390.png`) });
  }
});
