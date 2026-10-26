import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (variant: string) =>
  `/dev/preview/ReadOnlyMessage?theme=light&background=%23dbeafe&width=520&chrome=0&variant=${variant}`;

// contract-test: supporting surface=gui.web assertions=video-call.audio.spoken-rich-response,video-call.privacy
test('hides speech delivery cues while preserving sources and literal code', async ({ page }) => {
  await page.goto(preview('voiceDeliveryCues'));
  await waitForComponentPreview(page);
  const message = page.getByTestId('message-content');
  await expect(message).toContainText('Read the guide. Then continue.');
  await expect(message.getByRole('link', { name: 'the guide', exact: true }))
    .toHaveAttribute('href', 'https://example.org/guide');
  await expect(message).not.toContainText('voice:curious');
  await expect(message).not.toContainText('voice:short pause');
  await expect(message.locator('code')).toContainText('<!-- voice:excited -->');

  await page.goto(preview('pendingVoiceDeliveryCue'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('message-content')).toContainText('A useful spoken answer.');
  await expect(page.getByTestId('message-content')).not.toContainText('voice:');
});
