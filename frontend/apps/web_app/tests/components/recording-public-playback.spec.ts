import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
test('public recording plays in preview and fullscreen', async ({ page }) => {
  const fixture = '/store-examples/transcription-demo-voice-note.wav';
  const mediaResponse = await page.request.get(fixture);
  expect(mediaResponse.ok()).toBe(true);
  expect(mediaResponse.headers()['content-type']).toContain('audio/wav');
  expect((await mediaResponse.body()).byteLength).toBeGreaterThan(0);

  await page.goto('/dev/preview/embeds/audio/RecordingEmbedPreview?variant=guest&theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);

  const preview = page.getByTestId('recording-preview');
  const audio = page.getByTestId('recording-preview-audio');
  await expect(preview).toBeVisible();
  await expect(audio).toHaveAttribute('src', fixture);
  await expect.poll(() => audio.evaluate((element) => (element as HTMLAudioElement).duration))
    .toBeGreaterThan(0);
  await page.getByTestId('recording-preview-play-button').click();
  await expect.poll(() => audio.evaluate((element) => (element as HTMLAudioElement).currentTime))
    .toBeGreaterThan(0);
  await expect(page.getByTestId('recording-preview-play-button')).toHaveAttribute('aria-label', 'Pause');

  await page.goto('/dev/preview/embeds/audio/RecordingEmbedFullscreen?theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  const fullscreenAudio = page.locator('.recording-fullscreen audio');
  await expect(fullscreenAudio).toHaveAttribute('src', fixture);
  await expect.poll(() => fullscreenAudio.evaluate((element) => (element as HTMLAudioElement).duration))
    .toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(() => fullscreenAudio.evaluate((element) => (element as HTMLAudioElement).currentTime))
    .toBeGreaterThan(0);
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
});
