// playwright-account: not_required reason=isolated_component_preview
// Web reference screenshots for the Apple call controls (Native Swift counterpart:
// apple/OpenMatesUITests/NativeVoiceCallControlsUITests.swift, same states and width).
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const bar = (width: number, variant?: string) =>
  `/dev/preview/voicecall/VoiceCallBarPreview?${new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:String(width),props:JSON.stringify({fixed:false,realAudio:false}),...(variant?{variant}:{})})}`;
const media = (width: number, variant: string) =>
  `/dev/preview/voicecall/VoiceCallMediaPreview?${new URLSearchParams({chrome:'0',theme:'light',background:'#dbeafe',width:String(width),variant})}`;

// contract-test: supporting surface=gui.web assertions=video-call.video.input-and-output
// Written into the test output folder so CI evidence keeps the PNGs next to the Apple ones.
const shot = async (page: import('@playwright/test').Page, testInfo: import('@playwright/test').TestInfo, name: string) => {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({path});
  await testInfo.attach(name, {path, contentType:'image/png'});
};

test('live call strip and camera preview at 390px for the Apple comparison', async ({page}, testInfo) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto(bar(390));
  await waitForComponentPreview(page);
  const strip = page.getByTestId('voice-call-bar');
  const video = page.getByTestId('voice-call-video');
  await expect(strip).toBeVisible();
  await expect(video).toBeVisible();
  const [stripBox, videoBox] = await Promise.all([strip.boundingBox(), video.boundingBox()]);
  expect(videoBox && stripBox && videoBox.y >= stripBox.y - .5 && videoBox.y + videoBox.height <= stripBox.y + stripBox.height + .5).toBe(true);
  await shot(page, testInfo, 'parity-live-call-controls-390');
  await page.goto(media(390,'camera'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('voice-call-camera-preview')).toBeVisible();
  await shot(page, testInfo, 'parity-camera-preview-expanded-390');
  await page.getByTestId('voice-call-media-expand').click();
  await expect(page.getByTestId('voice-call-media')).toHaveAttribute('data-expanded','false');
  await shot(page, testInfo, 'parity-camera-preview-collapsed-390');
});
