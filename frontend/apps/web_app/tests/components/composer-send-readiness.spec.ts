// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = (variant?: string) =>
  `/dev/preview/enter_message/ActionButtons?${new URLSearchParams({ chrome: '0', theme: 'light', background: '#dbeafe', width: '680', ...(variant ? { variant } : {}) })}`;

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
});
