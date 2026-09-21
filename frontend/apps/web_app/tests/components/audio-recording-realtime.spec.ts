import { expect, test } from '../helpers/cookie-audit';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=message-input.embeds.gated-send
test('audio preview keeps the raw transcript visible during auto correction', async ({ page }) => {
  await page.goto('/dev/preview/embeds/audio/RecordingEmbedPreview?variant=correcting&chrome=0');

  const preview = page.getByTestId('recording-preview');
  await expect(preview).toBeVisible();
  await expect(preview).toContainText('Please schedule the project review for Thursday afternoon.');
  await expect(preview.getByTestId('recording-auto-correction')).toContainText('Auto correction');
  await expect(preview.locator('.correction-spinner')).toBeVisible();
});
