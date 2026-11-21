// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant: string | undefined, width: number) =>
  `/dev/preview/voicecall/VoiceCallBarPreview?${new URLSearchParams({
    chrome: '0', theme: 'light', background: '#dbeafe', width: String(width),
    props: JSON.stringify({ fixed: false, realAudio: false }), ...(variant ? { variant } : {}),
  })}`;

test.describe('Voice call waiting state', () => {
  for (const width of [390, 1280]) {
    // contract-test: direct surface=gui.web assertions=video-call.waiting.hold-button
    test(`hold button enters and leaves waiting with its ready-made line at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.goto(preview(undefined, width));
      await waitForComponentPreview(page);
      const hold = page.getByTestId('voice-call-hold');
      const shot = async (name: string) => test.info().attach(`${name}-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
      await shot('default');
      await expect(hold).toHaveAttribute('aria-pressed', 'false');
      await expect(page.getByTestId('voice-call-waiting')).toHaveCount(0);
      await hold.click();
      await expect(hold).toHaveAttribute('aria-pressed', 'true');
      await expect(page.getByTestId('voice-call-waiting')).toHaveText('Waiting for you');
      await expect(page.getByTestId('voice-call-waiting-line')).toHaveText("Okay, I'm waiting.");
      await expect(hold).toBeInViewport({ ratio: 1 });
      const box = async (id: string) => (await page.getByTestId(id).boundingBox())!;
      const apart = (a: { x: number; width: number }, b: { x: number; width: number }) => a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5;
      const label = await box('voice-call-waiting'), video = await box('voice-call-video');
      const holdBox = await box('voice-call-hold'), mute = await box('voice-call-mute');
      const left = (await page.getByTestId('voice-call-screen-share').count()) ? await box('voice-call-screen-share') : video;
      const pairs: [typeof label, typeof label][] = [[video, label], [left, label], [label, mute], [label, holdBox], [mute, holdBox]];
      if (width <= 700) {
        // Narrow bars: "Waiting for you" takes the timer's place.
        await expect(page.getByTestId('voice-call-timer')).toBeHidden();
      } else {
        const timer = await box('voice-call-timer');
        pairs.push([video, timer], [left, timer], [timer, label]);
      }
      for (const [a, b] of pairs) expect(apart(a, b)).toBe(true);
      // At most two short lines, never a three-line stack squeezed against the mic.
      // line-height is "normal" on wide bars; a line is then at most 1.5x the font size.
      const lineHeight = await page.getByTestId('voice-call-waiting').evaluate((el) => {
        const style = getComputedStyle(el);
        return style.lineHeight === 'normal' ? parseFloat(style.fontSize) * 1.5 : parseFloat(style.lineHeight);
      });
      expect(label.height).toBeLessThanOrEqual(lineHeight * 2 + 1);
      expect(holdBox.x + holdBox.width).toBeLessThanOrEqual(width);
      await shot('waiting');
      await hold.click();
      await expect(hold).toHaveAttribute('aria-pressed', 'false');
      await expect(page.getByTestId('voice-call-waiting')).toHaveCount(0);
      await expect(page.getByTestId('voice-call-waiting-line')).toHaveText('Okay, go on.');
      await shot('after-resume');
    });

    // contract-test: direct surface=gui.web assertions=video-call.waiting.hold-button
    test(`a call that starts waiting shows Waiting for you at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.goto(preview('waiting', width));
      await waitForComponentPreview(page);
      await expect(page.getByTestId('voice-call-waiting')).toHaveText('Waiting for you');
      await expect(page.getByTestId('voice-call-hold')).toHaveAttribute('aria-pressed', 'true');
    });
  }
});
