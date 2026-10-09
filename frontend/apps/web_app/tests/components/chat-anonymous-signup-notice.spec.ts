import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

test.describe('Anonymous chat signup notice', () => {
  // contract-test: supporting surface=gui.web assertions=landing-onboarding.signup-cta
  test('keeps the translated notice readable and opens signup at laptop and phone widths', async ({ page }) => {
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 850 });
      await page.goto(`/dev/preview/ChatMessage?theme=light&background=%23dbeafe&width=${width}&chrome=0&variant=anonymousFeatureNotice`);
      await waitForComponentPreview(page);

      const notice = page.getByTestId('anonymous-feature-notice');
      const link = page.getByTestId('anonymous-signup-link');
      await expect(notice).toHaveText('Signup now to unlock all features and to keep your chats and access them across your devices.');
      await expect(link).toHaveAttribute('href', '/#signup/basics');
      await expect(link).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

      await link.focus();
      await expect(link).toBeFocused();
      await expect(link).toHaveCSS('outline-style', 'solid');
      await page.evaluate(() => {
        (window as Window & { __signupNoticeEvents?: number }).__signupNoticeEvents = 0;
        window.addEventListener('openSignupInterface', () => {
          const target = window as Window & { __signupNoticeEvents?: number };
          target.__signupNoticeEvents = (target.__signupNoticeEvents ?? 0) + 1;
        }, { once: true });
      });
      await link.click();
      expect(await page.evaluate(() => (window as Window & { __signupNoticeEvents?: number }).__signupNoticeEvents)).toBe(1);
      await page.screenshot({ path: test.info().outputPath(`anonymous-signup-notice-${width}.png`) });
    }
  });
});
