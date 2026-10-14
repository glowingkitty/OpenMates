import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.language-theme
test('mobile public header keeps GitHub between the full logo and language control', async ({ page }, testInfo) => {
  test.setTimeout(60_000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: { anonymous_free_usage: { active: false, can_send_text: false } } }));
  for (const width of [320, 340, 360, 381, 390, 460]) {
    await page.setViewportSize({ width, height: 720 });
    const query = new URLSearchParams({ theme: 'dark', background: '#161616', width: String(width), chrome: '0' });
    await page.goto(`/dev/preview/landing/LandingPage?${query}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page, 30_000);
    await page.evaluate(() => document.fonts.ready.then(() => true));
    const header = page.getByTestId('public-site-header');
    for (const language of ['en', 'de']) {
      await header.getByTestId('landing-language-button').click();
      await header.getByTestId('landing-language-panel').getByRole('button', { name: language === 'en' ? 'English' : 'Deutsch', exact: true }).click();
      const github = header.getByRole('link', { name: 'OpenMates on GitHub' });
      await expect(github).toBeVisible();
      await expect(github).toHaveAttribute('href', 'https://github.com/glowingkitty/OpenMates');
      await expect(github).toHaveAttribute('target', '_blank');
      await expect(github.locator('.github-mask')).toHaveCSS('mask-image', /github\.svg/);
      await expect(header.locator('.wordmark')).toHaveText('OpenMates');
      await expect(header.locator('.wordmark')).toHaveCSS('font-size', '20px');
      await expect(header.getByTestId('landing-open-web-app')).toHaveText(language === 'en' ? 'Open Web App' : 'Web-App öffnen');
      const layout = await header.evaluate(element => ({
        items: ['.wordmark', '.github-link', '.language-control', '.header-link'].map(selector => element.querySelector(selector)!.getBoundingClientRect().toJSON()),
        overflow: element.scrollWidth > element.clientWidth,
      }));
      expect(layout.overflow).toBe(false);
      expect(layout.items[0].left).toBeGreaterThanOrEqual(0);
      expect(layout.items[0].right).toBeLessThanOrEqual(layout.items[1].left - 3);
      for (let i = 1; i < layout.items.length; i++) {
        expect(layout.items[i].right).toBeLessThanOrEqual(width);
        expect(layout.items[i - 1].right).toBeLessThanOrEqual(layout.items[i].left);
      }
      await page.mouse.move(1, 1);
      await header.screenshot({ path: testInfo.outputPath(`header-${width}-${language}.png`) });
    }
  }
});
