import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// The full speech journey verifies runtime provider metadata reaches this action.
// contract-test: supporting surface=gui.web assertions=assistant-speech.on-demand.generate-missing-only,assistant-speech.failure.nonblocking-visible-resumable
test('offers an accessible speech action only when playback is available', async ({ page }) => {
  await page.goto('/dev/preview/ChatMessage?variant=speechAvailable&chrome=0&width=650');
  await waitForComponentPreview(page);
  const action = page.getByTestId('assistant-message-speak');
  await expect(action).toBeVisible();
  await expect(action).toHaveAccessibleName('Speak response');
  await action.hover();
  await action.focus();
  await expect(action).toBeFocused();
  await action.press('Enter');
  await expect(page.locator('html')).toHaveAttribute('data-preview-speech-requested', 'true');
  await page.goto('/dev/preview/ChatMessage?variant=speechUnavailable&chrome=0&width=650');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('mate-message-content')).toContainText('A response ready to speak.');
  await expect(action).toHaveCount(0);
});
