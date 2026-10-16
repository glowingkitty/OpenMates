import { expect, type Page } from '@playwright/test';

/** Dismiss the focused composer through its document-level outside pointer handler. */
export async function dismissComposerFocus(page: Page): Promise<void> {
  const field = page.getByTestId('message-field');
  await expect(field, 'The composer must own focus before dismissal').toHaveAttribute('data-focused', 'true');
  await page.mouse.click(5, 5);
  await expect(field, 'Conversation controls must be reachable after dismissal').toHaveAttribute('data-focused', 'false');
}
