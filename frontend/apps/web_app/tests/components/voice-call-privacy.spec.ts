// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
const preview = '/dev/preview/voicecall/VoiceCallPrivacyPreview?chrome=0&theme=light';
const title = 'Before your first voice call';
const description = 'Google processes your voice and the conversation context shared with this call. Google states that data sent through its paid Gemini API is not used to train its models.';
for (const viewport of [{ name: 'phone', width: 390, height: 844 }, { name: 'laptop', width: 1440, height: 900 }]) {
  test.describe(viewport.name, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });
    // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
    test('uses the shared global notification and cancels without saving', async ({ page }, testInfo) => {
      await page.goto(preview); await waitForComponentPreview(page);
      const notice = page.getByTestId('notification').filter({ hasText: title });
      await expect(page.getByTestId('notification-stack')).toBeVisible(); await expect(notice).toBeVisible();
      await expect(notice).toContainText(description);
      await expect(notice.getByRole('link', { name: 'Google Gemini API terms' })).toHaveAttribute('href', 'https://ai.google.dev/gemini-api/terms#paid-services');
      await expect(page.getByTestId('privacy-preview-reads')).toHaveText('1');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('0');
      await expect(page.getByTestId('privacy-preview-gestures')).toHaveText('0');
      await expect(notice).toBeInViewport({ ratio: 1 });
      await page.screenshot({ path: testInfo.outputPath(`voice-call-privacy-${viewport.name}-before-cancel.png`) });
      await notice.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Cancelled');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('0'); await expect(notice).toHaveCount(0);
    });
    // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
    test('continues only after its explicit save action', async ({ page }) => {
      await page.goto(preview); await waitForComponentPreview(page);
      const notice = page.getByTestId('notification').filter({ hasText: title });
      await notice.getByRole('button', { name: 'Continue', exact: true }).click();
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Saved');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('1');
      await expect(page.getByTestId('privacy-preview-gestures')).toHaveText('1'); await expect(notice).toHaveCount(0);
    });
    // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
    test('keeps the notification on save failure and retries explicitly', async ({ page }, testInfo) => {
      await page.goto(preview + '&variant=saveFailure'); await waitForComponentPreview(page);
      const notice = page.getByTestId('notification').filter({ hasText: title });
      await notice.getByRole('button', { name: 'Continue', exact: true }).click();
      await expect(notice).toContainText('Your acknowledgement could not be saved. Try again to start the call.');
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Pending');
      await expect(notice.getByRole('button', { name: 'Cancel', exact: true })).toBeEnabled();
      await page.screenshot({ path: testInfo.outputPath(`voice-call-privacy-${viewport.name}-failed-save-before-retry.png`) });
      await notice.getByRole('button', { name: 'Continue', exact: true }).click();
      await expect(page.getByTestId('privacy-preview-result')).toHaveText('Saved');
      await expect(page.getByTestId('privacy-preview-saves')).toHaveText('2');
    });
  });
}
// contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
test('keeps the shared notification visible with disabled actions while saving', async ({ page }) => {
  await page.goto(preview + '&variant=saving'); await waitForComponentPreview(page);
  const notice = page.getByTestId('notification').filter({ hasText: title });
  await notice.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(notice.getByTestId('notification-action')).toBeDisabled();
  await expect(notice.getByTestId('notification-secondary-action')).toBeDisabled();
  await expect(notice.getByTestId('notification-activity')).toBeVisible();
  await expect(page.getByTestId('privacy-preview-result')).toHaveText('Pending');
  await page.getByTestId('privacy-preview-release').click();
  await expect(page.getByTestId('privacy-preview-result')).toHaveText('Saved');
});
for (const action of ['dismiss', 'abort']) {
  // contract-test: direct surface=gui.web assertions=video-call.privacy.first-call-warning
  test(`cancels pending launch on ${action} without saving`, async ({ page }) => {
    await page.goto(preview); await waitForComponentPreview(page);
    const notice = page.getByTestId('notification').filter({ hasText: title }); await expect(notice).toBeVisible();
    if (action === 'dismiss') await notice.getByRole('button', { name: 'Dismiss notification' }).click();
    else await page.getByTestId('privacy-preview-abort').click();
    await expect(page.getByTestId('privacy-preview-result')).toHaveText('Cancelled');
    await expect(page.getByTestId('privacy-preview-saves')).toHaveText('0');
    await expect(page.getByTestId('privacy-preview-gestures')).toHaveText('0'); await expect(notice).toHaveCount(0);
  });
}
