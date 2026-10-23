import { expect, type Page } from '@playwright/test';

/** Focus only once the mounted composer can accept deliberate editor input. */
export async function focusComposer(page: Page): Promise<void> {
  const field = page.getByTestId('message-field');
  await expect(field, 'The composer editor must finish its initial focus guard').toHaveAttribute('data-editor-ready', 'true');
  // An inactive draft displays a summary and hides its editable document.
  await field.click();
  const editor = page.getByTestId('message-editor').getByRole('textbox');
  await editor.focus();
  await expect(editor, 'The mounted editor must own keyboard focus').toBeFocused();
  await expect(field).toHaveAttribute('data-focused', 'true');
}

/** Dismiss the focused composer through its document-level outside pointer handler. */
export async function dismissComposerFocus(page: Page): Promise<void> {
  const field = page.getByTestId('message-field');
  await expect(field, 'The composer must own focus before dismissal').toHaveAttribute('data-focused', 'true');
  await page.mouse.click(5, 5);
  await expect(field, 'Conversation controls must be reachable after dismissal').toHaveAttribute('data-focused', 'false');
}
