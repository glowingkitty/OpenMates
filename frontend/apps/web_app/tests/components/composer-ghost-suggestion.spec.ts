// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const previewUrl = '/dev/preview/enter_message/MessageInput?theme=light&background=%23dbeafe&width=680&chrome=0&variant=ghostSuggestion';

test.describe('Contextual composer suggestion', () => {
  // contract-test: direct surface=gui.web assertions=message-input.suggestion.editable-acceptance,message-input.suggestion.keyboard-ownership
  test('Tab inserts editable text without sending; Shift+Tab keeps normal navigation', async ({ page }) => {
    await page.goto(previewUrl);
    await waitForComponentPreview(page);
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    const ghost = page.getByTestId('composer-ghost-suggestion');
    await expect(ghost).toHaveText('Could you compare the two approaches for me?');
    await expect(editor).toHaveText('');
    await editor.click();
    await expect(page.getByTestId('composer-ghost-actions')).toContainText('Press Tab to accept suggestion');
    await editor.press('Shift+Tab');
    await expect(ghost).toBeVisible();
    await editor.click();
    await editor.press('Tab');
    await expect(editor).toContainText('Could you compare the two approaches for me?');
    await expect(ghost).toHaveCount(0);
    await editor.press('End');
    await editor.type(' Please include costs.');
    await expect(editor).toContainText('Please include costs.');
  });

  // contract-test: direct surface=gui.web assertions=message-input.suggestion.dismissal,message-input.suggestion.draft-priority
  test('Escape dismisses and typing hides the ghost without creating editor content', async ({ page }) => {
    await page.goto(previewUrl);
    await waitForComponentPreview(page);
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    const ghost = page.getByTestId('composer-ghost-suggestion');
    await editor.click();
    await editor.press('Escape');
    await expect(editor).toHaveText('');
    await editor.type('My own question');
    await expect(ghost).toHaveCount(0);
    await expect(editor).toHaveText('My own question');
  });

  test.describe('Touch interaction', () => {
    test.use({ hasTouch: true });

    // contract-test: direct surface=gui.web assertions=message-input.suggestion.touch-acceptance
    test('Use suggestion inserts an editable draft on touch', async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(previewUrl.replace('width=680', 'width=390'));
      await waitForComponentPreview(page);
      const editor = page.getByTestId('message-editor').locator('.ProseMirror');
      await editor.tap();
      await page.getByTestId('composer-ghost-use').tap();
      await expect(editor).toContainText('Could you compare the two approaches for me?');
      await expect(page.getByTestId('composer-ghost-suggestion')).toHaveCount(0);
    });
  });
});
