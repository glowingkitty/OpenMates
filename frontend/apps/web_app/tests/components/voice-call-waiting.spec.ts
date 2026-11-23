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
    // contract-test: direct surface=gui.web assertions=video-call.waiting.spoken-intent-and-merge
    test(`the Waiting for you label fits beside the call controls at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.goto(preview('waiting', width));
      await waitForComponentPreview(page);
      const box = async (id: string) => (await page.getByTestId(id).boundingBox())!;
      const apart = (a: { x: number; width: number }, b: { x: number; width: number }) => a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5;
      const label = await box('voice-call-waiting'), video = await box('voice-call-video'), mute = await box('voice-call-mute');
      const hangup = await box('voice-call-hangup');
      const left = (await page.getByTestId('voice-call-screen-share').count()) ? await box('voice-call-screen-share') : video;
      const pairs: [typeof label, typeof label][] = [[video, label], [left, label], [label, mute], [label, hangup], [mute, hangup]];
      if (width <= 700) {
        await expect(page.getByTestId('voice-call-timer')).toBeHidden();
      } else {
        const timer = await box('voice-call-timer');
        pairs.push([video, timer], [left, timer], [timer, label]);
      }
      for (const [a, b] of pairs) expect(apart(a, b)).toBe(true);
      const lineHeight = await page.getByTestId('voice-call-waiting').evaluate((el) => {
        const style = getComputedStyle(el);
        return style.lineHeight === 'normal' ? parseFloat(style.fontSize) * 1.5 : parseFloat(style.lineHeight);
      });
      expect(label.height).toBeLessThanOrEqual(lineHeight * 2 + 1);
      expect(hangup.x + hangup.width).toBeLessThanOrEqual(width);
      await test.info().attach(`waiting-${width}`, { body: await page.screenshot(), contentType: 'image/png' });
    });

  }
});
