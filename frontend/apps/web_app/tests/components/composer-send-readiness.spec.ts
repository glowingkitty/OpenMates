// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant?: string, width = 680, theme = 'light') =>
  `/dev/preview/enter_message/ActionButtons?${new URLSearchParams({ chrome: '0', theme, background: '#dbeafe', width: String(width), ...(variant ? { variant } : {}) })}`;

test.describe('Composer Send readiness', () => {
  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,ai-model-routing.chat-selection.encrypted-user-chat-scope
  test('shows model loading while ordinary Send stays available', async ({ page }) => {
    await page.goto(preview('restoringModel'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-model-selector')).toBeDisabled();
    await expect(page.getByTestId('composer-model-selector')).toHaveAttribute('data-loading', 'true');
    await expect(page.getByTestId('composer-send-button')).toBeEnabled();
    await expect(page.getByTestId('composer-send-button')).toHaveAttribute('aria-busy', 'false');

    await page.goto(preview());
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-model-selector')).toBeEnabled();
    await expect(page.getByTestId('composer-send-button')).toBeEnabled();
    await expect(page.getByTestId('composer-send-button')).toHaveAttribute('aria-busy', 'false');
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership
  test('keeps queued-edit Send available during model restoration', async ({ page }) => {
    await page.goto(preview('queuedEdit'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-model-selector')).toBeDisabled();
    await expect(page.getByTestId('composer-send-button')).toBeEnabled();
    await expect(page.getByTestId('composer-send-button')).toHaveAttribute('aria-busy', 'false');
  });

  for (const width of [390, 1280]) {
    // contract-test: supporting surface=gui.web assertions=message-input.layout.responsive-parity,message-input.recording.lifecycle
    test(`keeps the microphone beside speech and before Send at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      for (const theme of ['light', 'dark']) {
        for (const variant of [undefined, 'emptyDraft']) {
          await page.goto(preview(variant, Math.min(width, 680), theme));
          await waitForComponentPreview(page);
          const speech = page.getByTestId('assistant-speech-toggle');
          const mic = page.getByTestId('record-audio-button');
          const send = page.getByTestId('composer-send-button');
          await expect(speech).toBeVisible();
          await expect(mic).toBeVisible();
          await expect(mic).toBeEnabled();
          await expect(send).toHaveCount(variant ? 0 : 1);
          const expectedGap = await mic.locator('..').evaluate(element =>
            Number.parseFloat(getComputedStyle(element).columnGap));

          await speech.hover();
          await speech.focus();
          await expect(speech).toBeFocused();
          await speech.press('Enter');
          await expect(speech).toHaveAttribute('aria-pressed', 'true');
          await speech.press('Enter');
          await expect(speech).toHaveAttribute('aria-pressed', 'false');
          await page.keyboard.press('Tab');
          await expect(mic).toBeFocused();

          await test.step(`${theme}: ${variant ? 'microphone is rightmost' : 'speech, microphone, Send'}`, async () => {
            await expect.poll(async () => {
              const [speechBox, micBox, sendBox, actionsBox] = await Promise.all([
                speech.boundingBox(), mic.boundingBox(), variant ? null : send.boundingBox(),
                page.getByTestId('action-buttons').boundingBox(),
              ]);
              if (!speechBox || !micBox || !actionsBox) return false;
              const gap = micBox.x - (speechBox.x + speechBox.width);
              const trailingBox = variant ? micBox : sendBox;
              return Math.abs(gap - expectedGap) <= 1 && !!trailingBox
                && Math.abs(speechBox.y + speechBox.height / 2 - micBox.y - micBox.height / 2) <= 1
                && (variant ? true : !!sendBox && micBox.x + micBox.width <= sendBox.x)
                && Math.abs(trailingBox.x + trailingBox.width - actionsBox.x - actionsBox.width) <= 1
                && actionsBox.x >= 0 && actionsBox.x + actionsBox.width <= width;
            }).toBe(true);
          });
        }
      }
    });
  }
});
