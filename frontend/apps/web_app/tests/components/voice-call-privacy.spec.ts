// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
const preview='/dev/preview/voicecall/VoiceCallPrivacyPreview?chrome=0&theme=light';
for(const viewport of [{name:'phone',width:390,height:844},{name:'laptop',width:1440,height:900}]){
  test.describe(viewport.name,()=>{
    test.use({viewport:{width:viewport.width,height:viewport.height}});
    // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
    test('shows attributed processing terms and cancels without saving',async({page},testInfo)=>{
      await page.goto(preview);await waitForComponentPreview(page);
      const modal=page.getByRole('dialog',{name:'Before your first voice call'});
      await expect(modal).toBeVisible();
      await expect(modal).toHaveAccessibleDescription('Google processes your voice and the conversation context shared with this call. Google states that data sent through its paid Gemini API is not used to train its models.');
      await expect(modal.getByRole('link',{name:'Google Gemini API terms'})).toHaveAttribute('href','https://ai.google.dev/gemini-api/terms#paid-services');
      await expect(page.getByTestId('voice-call-privacy-cancel')).toBeFocused();
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('0');
      const box=await modal.boundingBox();expect(box).not.toBeNull();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(viewport.width);
      await page.screenshot({path:testInfo.outputPath(`voice-call-privacy-${viewport.name}-before-cancel.png`)});
      await page.getByTestId('voice-call-privacy-cancel').click();
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Cancelled');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('0');
      await expect(modal).toHaveCount(0);
    });
    // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
    test('continues only after its explicit save action',async({page})=>{
      await page.goto(preview);await waitForComponentPreview(page);
      await page.getByTestId('voice-call-privacy-continue').click();
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Saved');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('1');
      await expect(page.getByTestId('voice-call-privacy-dialog')).toHaveCount(0);
    });
    // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
    test('keeps the warning on save failure and retries explicitly',async({page},testInfo)=>{
      await page.goto(preview+'&variant=saveFailure');await waitForComponentPreview(page);
      await page.getByTestId('voice-call-privacy-continue').click();
      await expect(page.getByRole('alert')).toHaveText('Your acknowledgement could not be saved. Try again to start the call.');
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Pending');
      await expect(page.getByTestId('voice-call-privacy-cancel')).toBeEnabled();
      await page.screenshot({path:testInfo.outputPath(`voice-call-privacy-${viewport.name}-failed-save-before-retry.png`)});
      await page.getByTestId('voice-call-privacy-continue').click();
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Saved');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('2');
    });
  });
}
// contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
test('traps keyboard focus and treats Escape as Cancel',async({page})=>{
  await page.goto(preview);await waitForComponentPreview(page);
  const cancel=page.getByTestId('voice-call-privacy-cancel');const proceed=page.getByTestId('voice-call-privacy-continue');
  await expect(cancel).toBeFocused();await page.keyboard.press('Tab');await expect(proceed).toBeFocused();
  const terms=page.getByRole('link',{name:'Google Gemini API terms'});
  await page.keyboard.press('Tab');await expect(terms).toBeFocused();
  await page.keyboard.press('Shift+Tab');await expect(proceed).toBeFocused();
  await page.keyboard.press('Shift+Tab');await expect(cancel).toBeFocused();
  await page.keyboard.press('Shift+Tab');await expect(terms).toBeFocused();
  await page.keyboard.press('Escape');await expect(page.getByTestId('privacy-preview-result')).toHaveText('Cancelled');
  await expect(page.getByTestId('privacy-preview-saves')).toHaveText('0');
});
