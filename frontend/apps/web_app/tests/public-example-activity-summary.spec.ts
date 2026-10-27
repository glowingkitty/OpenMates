// playwright-account: not_required reason=public_logged_out_example_activity_regression
import { expect, test } from './helpers/cookie-audit';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- Shared E2E helper uses CommonJS.
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
test('retained search example keeps its invocation collapsed while answer text stays inline', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(getE2EDebugUrl('/#chat-id=example-gigantic-airplanes'), { waitUntil: 'domcontentloaded' });
  const message = page.locator('[data-testid="message-assistant"][data-message-id="5f815be6-96ef-42c6-a4aa-1b07a2840a16"]');
  await expect(message).toBeVisible({ timeout: 15000 });
  const activity = message.getByTestId('assistant-activity-group');
  const toggle = activity.getByTestId('assistant-activity-toggle');
  const invocation = message.locator('[data-testid="embed-preview"][data-app-id="web"][data-skill-id="search"]');
  const results = message.getByRole('heading', { name: '1. Antonov An-225 Mriya' });
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(activity.getByTestId('assistant-activity-summary-text')).not.toBeEmpty();
  await expect(activity.getByTestId('assistant-activity-body')).toHaveCount(0);
  await expect(invocation).toHaveCount(0);
  await expect(results).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
  await expect(invocation).toHaveCount(1);
  await expect.poll(async () => {
      const remaining = Number((await invocation.getByTestId('search-preview-remaining-count').innerText()).match(/\d+/)?.[0]);
      return remaining + await invocation.locator('img.favicon').count();
    }).toBe(6);
  await expect(invocation).toContainText(/gigantic airplane/i);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(invocation).toHaveCount(0);
  await expect(results).toBeVisible();
});
