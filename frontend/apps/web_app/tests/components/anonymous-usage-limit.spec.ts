// playwright-account: not_required reason=isolated_component_preview
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 680]) {
// contract-test: direct surface=gui.web assertions=billing.anonymous.hard-capped-provider-metering,message-input.privacy-context
test(`guest limit replaces Send with Sign up and a notification at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width: width === 390 ? 390 : 1280, height: 900 });
  let exhausted = false;
  const availability = () => ({ active: !exhausted, can_send_text: !exhausted,
    reason: exhausted ? (width === 390 ? 'per_identity_exhausted' : 'daily_exhausted') : null });
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {
    is_self_hosted: false, server_edition: 'development', ai_models_configured: true,
    anonymous_free_usage: availability(),
  } }));
  await page.route('**/v1/anonymous/free-usage/status**', route => route.fulfill({ json: availability() }));
  const streamRequests: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/v1/anonymous/chat/stream')) streamRequests.push(request.url());
  });
  await page.goto(`/dev/preview/enter_message/MessageInputNotificationPreview?chrome=0&theme=light&background=%23dbeafe&width=${width}`);
  await waitForComponentPreview(page);
  const editor = page.getByTestId('message-editor').locator('[contenteditable="true"]').first();
  await editor.click();
  await editor.pressSequentially('Continue this chat');
  await expect(editor).toBeFocused();
  await expect(editor).toHaveText('Continue this chat');
  await expect(page.locator('[data-action="send-message"]')).toBeVisible();
  exhausted = true;
  await page.locator('[data-action="send-message"]').click();
  const notice = page.getByTestId('notification').filter({ hasText: "You've reached the free usage limit." });
  await expect(notice).toBeVisible();
  await expect(notice.getByTestId('notification-action')).toHaveText('Sign up');
  await expect(page.locator('[data-action="send-message"]')).toHaveCount(0);
  await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
  await expect(editor).toContainText('Continue this chat');
  await editor.blur();
  await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
  await editor.click();
  await editor.fill('');
  await editor.blur();
  await expect(page.locator('[data-action="sign-up-to-send"]')).toBeVisible();
  expect(streamRequests).toEqual([]);
  const signup = page.locator('[data-action="sign-up-to-send"]');
  await signup.focus();
  await expect(signup).toBeFocused();
  await signup.hover();
  const bounds = await signup.boundingBox();
  expect(bounds && bounds.width > 0 && bounds.height > 0).toBeTruthy();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  await page.evaluate(() => {
    window.addEventListener('openSignupInterface', () => {
      (window as typeof window & { __limitSignupRequested?: boolean }).__limitSignupRequested = true;
    }, { once: true });
  });
  await (width === 390 ? signup : notice.getByTestId('notification-action')).click();
  await expect.poll(() => page.evaluate(() =>
    (window as typeof window & { __limitSignupRequested?: boolean }).__limitSignupRequested
  )).toBe(true);
});
}
