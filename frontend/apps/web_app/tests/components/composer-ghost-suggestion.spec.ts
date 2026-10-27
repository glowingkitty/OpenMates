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
    await expect(ghost).toHaveCount(0);
    await expect(editor).toHaveText('');
    await editor.click();
    await expect(ghost).toHaveText('Could you compare the two approaches for me?');
    await expect(page.getByTestId('composer-ghost-actions')).toContainText('Press Tab to accept suggestion');
    await editor.press('Shift+Tab');
    await expect(editor).not.toBeFocused();
    await expect(editor).toHaveText('');
    await editor.click();
    await editor.press('Tab');
    await expect(editor).toContainText('Could you compare the two approaches for me?');
    await expect(ghost).toHaveCount(0);
    await editor.press('End');
    await editor.type(' Please include costs.');
    await expect(editor).toContainText('Please include costs.');
  });

  // contract-test: direct surface=gui.web assertions=message-input.suggestion.editable-acceptance,message-input.suggestion.draft-priority,message-input.actions.visibility
  test('shows the suggestion only in a focused empty composer and preserves minimized drafts', async ({ page }) => {
    await page.goto(previewUrl);
    await waitForComponentPreview(page);
    const field = page.getByTestId('message-field');
    const editor = page.getByTestId('message-editor').locator('.ProseMirror');
    const ghost = page.getByTestId('composer-ghost-suggestion');
    const placeholder = editor.locator('p.is-editor-empty').first();

    await test.step('The minimized empty input retains its normal placeholder', async () => {
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(field).toHaveClass(/compact/);
      await expect(field).not.toHaveClass(/has-ghost-suggestion/);
      await expect(ghost).toHaveCount(0);
      await expect(placeholder).toHaveAttribute('data-placeholder', /.+/);
      await expect.poll(() => placeholder.evaluate((element) => getComputedStyle(element, '::before').opacity)).toBe('1');
    });
    await test.step('Opening the empty input reveals a readable suggestion', async () => {
      await editor.click();
      await expect(field).toHaveAttribute('data-focused', 'true');
      await expect(ghost).toBeVisible();
      await expect(editor).toHaveText('');
      const ghostBox = await ghost.boundingBox();
      const fieldBox = await field.boundingBox();
      expect(ghostBox).not.toBeNull();
      expect(fieldBox).not.toBeNull();
      expect(ghostBox!.y).toBeGreaterThanOrEqual(fieldBox!.y);
      expect(ghostBox!.y + ghostBox!.height).toBeLessThanOrEqual(fieldBox!.y + fieldBox!.height);
    });
    await test.step('Clicking outside restores the minimized placeholder', async () => {
      await page.mouse.click(4, 4);
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(ghost).toHaveCount(0);
      await expect(field).not.toHaveClass(/has-ghost-suggestion/);
      await expect.poll(() => placeholder.evaluate((element) => getComputedStyle(element, '::before').opacity)).toBe('1');
    });
    await test.step('A user draft wins while focused and while minimized', async () => {
      await editor.click();
      await expect(ghost).toBeVisible();
      await editor.fill('My own next question');
      await expect(ghost).toHaveCount(0);
      await page.mouse.click(4, 4);
      await expect(page.getByTestId('message-draft-summary-text')).toContainText('My own next question');
      await expect(ghost).toHaveCount(0);
      await field.click();
      await expect(editor).toHaveText('My own next question');
      await expect(ghost).toHaveCount(0);
      await editor.fill('');
      await expect(editor).toHaveText('');
      // Typing dismisses this turn's suggestion; clearing must not revive it.
      await expect(ghost).toHaveCount(0);
    });
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
      await expect(page.getByTestId('composer-ghost-suggestion')).toHaveCount(0);
      await editor.tap();
      await expect(page.getByTestId('composer-ghost-suggestion')).toBeVisible();
      await page.getByTestId('composer-ghost-use').tap();
      await expect(editor).toContainText('Could you compare the two approaches for me?');
      await expect(page.getByTestId('composer-ghost-suggestion')).toHaveCount(0);
    });
  });
});
