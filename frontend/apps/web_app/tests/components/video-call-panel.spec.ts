// playwright-account: not_required reason=isolated_component_preview
/**
 * Bare component proof for the isolated video call panel.
 * Preview fixtures use local synthetic MP4 clips and no real account.
 * The spec exercises voice controls, pricing and clip continuity on desktop.
 * All capture navigations keep the preview chrome hidden.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant?: string, width = 1180) =>
  `/dev/preview/videocall/VideoCallPanel?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: String(width), ...(variant ? { variant } : {}) })}`;

test.use({ launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] } });

test.describe('Video call experiment panel', () => {
  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.user-stop,video-call.experiment.privacy
  test('starts and ends a voice call without recording controls', async ({ page }) => {
    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('video-call-panel')).toBeVisible();
    await expect(page.getByText('Via Google Gemini')).toBeVisible();
    await expect(page.getByTestId('call-start')).toBeVisible();
    await expect(page.getByTestId('call-usage')).toContainText('Audio only');
    await expect(page.getByTestId('call-active-rate')).toContainText('28 credits/min');
    await expect(page.getByTestId('call-billing-note')).toContainText('Billed per second, minimum 1 credit');
    await expect(page.getByTestId('video-call-panel')).not.toContainText('Download');
    await expect(page.getByTestId('video-call-panel')).not.toContainText('Replay');
    await page.getByTestId('call-start').focus();
    await expect(page.getByTestId('call-start')).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('call-hangup')).toBeVisible();
    await expect(page.getByTestId('call-transcript')).toContainText('What would you like to explore?');
    await page.getByTestId('call-hangup').click();
    await expect(page.getByText('Call ended. Your audio and visuals were released.')).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.billing,video-call.experiment.generated-visuals,video-call.experiment.user-stop
  test('shows server rates and lets the caller stop and allow visuals independently', async ({ page }) => {
    await page.goto(preview('visuals'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('call-active-rate')).toContainText('1,108 credits/min');
    await expect(page.getByTestId('call-usage')).toContainText('Credits charged');
    await expect(page.getByTestId('call-usage')).toContainText('10s');
    await page.getByText('Token and context usage').click();
    await expect(page.getByTestId('call-usage')).toContainText('Billed input/context 684');
    await page.getByTestId('call-stop-video').click();
    await expect(page.getByTestId('call-active-rate')).toContainText('28 credits/min');
    await expect(page.getByTestId('call-hangup')).toBeVisible();
    await page.getByTestId('call-allow-video').click();
    await expect(page.getByTestId('video-call-stage')).toContainText('Creating a visual');
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.generated-visuals,video-call.experiment.audio-mix,video-call.experiment.user-stop
  test('keeps an active visual during generation, advances clips and clears media on stop and restart', async ({ page }) => {
    await page.goto(preview('visuals'));
    await waitForComponentPreview(page);
    const video = page.getByTestId('call-video');
    await expect(video).toBeVisible();
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState >= 2)).toBe(true);
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.volume)).toBe(0.2);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'model_speaking' } })));
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.volume)).toBe(0.04);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'user_speaking' } })));
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.volume)).toBe(0.04);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'silence' } })));
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.volume)).toBe(0.2);
    const firstSrc = await video.getAttribute('src');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'queued' } })));
    await expect(video).toHaveAttribute('src', firstSrc!);
    await expect(page.getByText('Next visual is rendering…')).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'ready' } })));
    await expect(page.getByText('Next visual is rendering…')).toBeHidden();
    await expect.poll(() => video.getAttribute('src'), { timeout: 10_000 }).not.toBe(firstSrc);
    await expect(page.getByAltText('Waiting for next visual…')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId('call-stop-video').click();
    await expect(page.getByTestId('call-video')).toHaveCount(0);
    await expect(page.getByAltText('Waiting for next visual…')).toHaveCount(0);
    await page.getByTestId('call-hangup').click();
    await page.getByTestId('call-start').click();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'ready' } })));
    await expect(page.getByTestId('call-video')).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=video-call.experiment.live-voice,video-call.experiment.generated-visuals,video-call.experiment.audio-mix
  test('lets accepted clips finish while voice continues after idle generation stops', async ({ page }) => {
    await page.goto(preview('visuals'));
    await waitForComponentPreview(page);
    const video = page.getByTestId('call-video');
    await expect(video).toBeVisible();
    const firstSrc = await video.getAttribute('src');
    await page.evaluate(() => {
      for (const type of ['model_speaking', 'idle_pending', 'ready', 'drain_complete']) {
        window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type } }));
      }
    });
    await expect(page.getByTestId('call-stop-video')).toBeVisible();
    await expect(page.getByTestId('call-active-rate')).toContainText('Audio only');
    await expect(video).toHaveAttribute('src', firstSrc!);
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.volume)).toBe(0.04);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'audio_interrupted' } })));
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.volume)).toBe(0.2);
    await expect.poll(() => video.getAttribute('src'), { timeout: 10_000 }).not.toBe(firstSrc);
    await expect(video).toBeVisible();
    await expect(page.getByTestId('call-video')).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByTestId('call-allow-video')).toBeVisible();
    await expect(page.getByTestId('call-hangup')).toBeVisible();

    await page.getByTestId('call-allow-video').click();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'ready' } })));
    await expect(page.getByTestId('call-video')).toBeVisible();
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'idle_pending' } })));
    await page.getByTestId('call-stop-video').click();
    await expect(page.getByTestId('call-video')).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('video-call-preview-event', { detail: { type: 'ready' } })));
    await expect(page.getByTestId('call-video')).toHaveCount(0);
  });

});
