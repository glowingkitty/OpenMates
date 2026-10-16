// playwright-account: not_required reason=public_logged_out_example_activity_regression
import { expect, test } from './helpers/cookie-audit';
// eslint-disable-next-line @typescript-eslint/no-require-imports -- Shared E2E helper uses CommonJS.
const { getE2EDebugUrl } = require('./signup-flow-helpers');

// contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,public-example-chats.transcript.safe-rendering,public-example-chats.surface.semantic-parity
test('train example keeps its invocation collapsed while route results stay inline', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(getE2EDebugUrl('/#chat-id=example-deutschlandticket-train-fare-breakdown'), { waitUntil: 'domcontentloaded' });
  const message = page.locator('[data-testid="message-assistant"][data-message-id="9d5fe6e2-bb2b-5491-91fa-7483132bfde0"]');
  await expect(message).toBeVisible({ timeout: 15000 });
  const activity = message.getByTestId('assistant-activity-group');
  const toggle = activity.getByTestId('assistant-activity-toggle');
  const invocation = message.locator('[data-testid="embed-preview"][data-app-id="travel"][data-skill-id="search_connections"]');
  const results = message.getByTestId('embeds-map-view');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(activity.getByTestId('assistant-activity-summary-text')).not.toBeEmpty();
  await expect(activity.getByTestId('assistant-activity-body')).toHaveCount(0);
  await expect(invocation).toHaveCount(0);
  await expect(results).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(activity.getByTestId('assistant-activity-body')).toBeVisible();
  await expect(invocation).toHaveCount(1);
  await expect(invocation).toContainText('5 connections');
  await expect(invocation).toContainText(/Bonn.*M(unich|ünchen)/i);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(invocation).toHaveCount(0);
  await expect(results).toBeVisible();
});
