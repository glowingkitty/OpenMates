/**
 * Opening the collapsed activity summaries of assistant replies.
 *
 * A finished reply folds its skill embeds into the collapsed activity summary
 * ("Thought & used the Plans app"); open the summaries of the newest replies, where a
 * new Specification, Check or Plan embed lands, so the real embed nodes render.
 * Older replies are left alone: scrolling to them remounts them collapsed.
 */
import { expect, type Page } from '@playwright/test';

export async function expandActivity(page: Page): Promise<void> {
  const replies = page.getByTestId('message-assistant');
  const total = await replies.count();
  for (let r = Math.max(0, total - 2); r < total; r += 1) {
    const toggles = replies.nth(r).getByTestId('assistant-activity-toggle');
    for (let t = 0; t < await toggles.count(); t += 1) {
      const toggle = toggles.nth(t);
      await expect(async () => {
        if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
        await expect(toggle).toHaveAttribute('aria-expanded', 'true', { timeout: 2_000 });
      }).toPass({ timeout: 20_000 });
    }
  }
}
