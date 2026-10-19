import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=marketing-landing.destinations,marketing-landing.language-theme,language-preferences.manual-choice
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
      await expect(header.getByTestId('landing-language-panel').locator('.language-options button[lang]')).toHaveCount(2);
      await expect(header.getByTestId('landing-language-auto')).toBeVisible();
      await header.getByTestId('landing-language-panel').getByRole('button', { name: language === 'en' ? 'English' : 'Deutsch', exact: true }).click();
      const github = header.getByRole('link', { name: 'OpenMates on GitHub' });
      await expect(github).toBeVisible();
      await expect(github).toHaveAttribute('href', 'https://github.com/glowingkitty/OpenMates');
      await expect(github).toHaveAttribute('target', '_blank');
      await expect(github.locator('svg path')).toHaveCount(1);
      await expect(header.locator('.wordmark')).toHaveText('OpenMates');
      await expect(header.locator('.wordmark')).toHaveCSS('font-size', '20px');
      await expect(header.getByTestId('landing-open-web-app')).toHaveText(language === 'en' ? 'Open Web App' : 'Web-App öffnen');
      await expect(header.getByTestId('landing-open-web-app')).toHaveAttribute('href', `https://app.dev.openmates.org/?lang=${language}`);
      expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe(language);
      await expect.poll(async () => {
        const cookies = await page.context().cookies();
        return decodeURIComponent(cookies.find(cookie => cookie.name === 'om_language')?.value ?? '');
      }).toBe(`manual:${language}`);
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

// contract-test: direct surface=gui.web assertions=marketing-landing.language-theme,language-preferences.manual-choice,language-preferences.resolution
test('Automatic language uses the browser and clears a previous manual selection', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/v1/settings/server-status', route => route.fulfill({ json: {} }));
  const props = JSON.stringify({ initialLanguage: 'de', initialLanguageMode: 'manual' });
  await page.goto(`/dev/preview/landing/LandingPage?chrome=0&props=${encodeURIComponent(props)}`);
  await waitForComponentPreview(page, 30_000);
  const header = page.getByTestId('public-site-header');
  await expect(header.getByTestId('landing-open-web-app')).toHaveText('Web-App öffnen');
  await header.getByTestId('landing-language-button').click();
  await header.getByTestId('landing-language-auto').click();
  await expect(header.getByTestId('landing-open-web-app')).toHaveText('Open Web App');
  await expect(header.getByTestId('landing-open-web-app')).toHaveAttribute('href', 'https://app.dev.openmates.org/');
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem('openmatesLanguageMode'))).toBe('auto');
  await header.getByTestId('landing-language-button').click();
  await expect(header.getByTestId('landing-language-auto')).toHaveAttribute('aria-pressed', 'true');
});
