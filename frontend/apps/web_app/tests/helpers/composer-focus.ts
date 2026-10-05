import { expect, type Page } from '@playwright/test';

/** Dismiss the focused composer through its normal outside-click control. */
export async function dismissComposerFocus(page: Page): Promise<void> {
  const backdrop = page.getByTestId('chat-composer-focus-backdrop');
  await expect(backdrop, 'The composer must own focus before dismissal').toBeVisible();
  await backdrop.click({ position: { x: 40, y: 40 } });
  await expect(backdrop, 'Conversation controls must be reachable after dismissal').toBeHidden();
}
