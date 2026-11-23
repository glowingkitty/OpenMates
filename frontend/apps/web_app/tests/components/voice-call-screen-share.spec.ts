// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (width: number, props: Record<string, unknown>) =>
  `/dev/preview/voicecall/VoiceCallBarPreview?${new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:String(width),props:JSON.stringify({realAudio:false,...props})})}`;

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=video-call.video.web-screen-share
  test(`screen sharing shows its indicator with Stop and ends on the user's tap at ${width}px`, async ({page}, testInfo) => {
    await page.setViewportSize({width, height: 900});
    await page.goto(preview(width, {}));
    await waitForComponentPreview(page);
    const share = page.getByTestId('voice-call-screen-share');
    await expect(share).toBeVisible();
    await expect(share).toHaveAccessibleName('Share screen');
    await expect(page.getByTestId('voice-call-screen-share-indicator')).toHaveCount(0);
    await share.click();
    const indicator = page.getByTestId('voice-call-screen-share-indicator');
    await expect(indicator).toBeVisible();
    await expect(indicator).toContainText('You are sharing your screen');
    await expect(share).toHaveAttribute('aria-pressed', 'true');
    await expect(share).toHaveAccessibleName('Stop sharing screen');
    // Screen sharing has no front/rear camera to flip.
    await expect(page.getByTestId('voice-call-camera-flip')).toHaveCount(0);
    const shareBox = await share.boundingBox();
    const timerBox = await page.getByTestId('voice-call-timer').boundingBox();
    expect(shareBox && timerBox).toBeTruthy();
    const disjoint = shareBox!.x + shareBox!.width <= timerBox!.x || timerBox!.x + timerBox!.width <= shareBox!.x
      || shareBox!.y + shareBox!.height <= timerBox!.y || timerBox!.y + timerBox!.height <= shareBox!.y;
    expect(disjoint, 'screen share button must not overlap the call timer').toBe(true);
    await testInfo.attach(`screen-share-active-${width}`, {body: await page.getByTestId('voice-call-bar').screenshot(), contentType: 'image/png'});
    await page.getByTestId('voice-call-screen-share-stop').click();
    await expect(indicator).toHaveCount(0);
    await expect(share).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('voice-call-bar')).toBeVisible();
  });

  // contract-test: direct surface=gui.web assertions=video-call.video.web-screen-share
  test(`the screen share button is absent where the browser cannot capture a display at ${width}px`, async ({page}) => {
    await page.setViewportSize({width, height: 900});
    await page.goto(preview(width, {screenShareSupported: false}));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('voice-call-video')).toBeVisible();
    await expect(page.getByTestId('voice-call-screen-share')).toHaveCount(0);
  });
}
