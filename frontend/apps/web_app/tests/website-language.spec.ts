import { expect, test } from './helpers/cookie-audit';
import { app, site, useWebsitePreview, watchPrivateStartup, website } from './helpers/website-preview';
import publicationManifest from '../../../packages/public-site/src/publications/publicationManifest.v1.json';

// playwright-account: not_required reason=isolated_runner_local_public_website
useWebsitePreview();
test.use({ locale: 'de-DE' });

test.describe('server-rendered language without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  // contract-test: direct surface=gui.web assertions=language-preferences.first-paint,language-preferences.resolution,language-preferences.content-language
  test('German browser receives German HTML, metadata, cards, and legal destinations', async ({ page, request }) => {
    const response = await request.get(site('/'), { headers: { 'Accept-Language': 'fr-CH;q=1,de-DE;q=0.9,en;q=0.5' } });
    const html = await response.text();
    expect(response.headers()['cache-control']).toContain('private');
    expect(response.headers()['cache-control']).toContain('no-store');
    expect(response.headers().vary.toLowerCase()).toContain('accept-language');
    expect(response.headers().vary.toLowerCase()).toContain('cookie');
    expect(html).toContain('<html lang="de" dir="ltr">');
    expect(html).toContain('Deine KI-Teamkollegen');
    expect(html).not.toContain('Your privacy first');
    await page.goto(site('/'));
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    await expect(page.locator('#hero-title')).toHaveText('Deine KI-Teamkollegenmit Privatsphäre');
    await expect(page).toHaveTitle('OpenMates — Deine KI-Teamkollegen mit Privatsphäre');
    await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /Deine KI-Teamkollegen/);
    await expect(page.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
    await expect(page.locator('.site-footer a[href*="/legal/privacy"]')).toHaveAttribute('href', site('/legal/privacy?lang=de'));
    const germanTitles = publicationManifest.publications.filter(record => record.kind === 'blog').map(record => record.locales.de?.title).filter(Boolean);
    const cardTitles = await page.getByTestId('landing-blog').locator('.publication-card h3').allTextContents();
    expect(cardTitles.length).toBeGreaterThan(0);
    expect(cardTitles.every(title => germanTitles.includes(title))).toBe(true);
    await page.locator('.site-footer a[href*="/legal/privacy"]').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    await expect(page.locator('.legal-document h1')).toContainText('Datenschutz');
    await expect(page.locator('.site-footer a[href*="/legal/imprint"]')).toHaveText('Impressum');
    await expect(page.locator('.site-footer a[href*="/legal/imprint"]')).toHaveAttribute('href', '/legal/imprint?lang=de');
  });

  // contract-test: direct surface=gui.web assertions=language-preferences.first-paint,language-preferences.resolution
  test('manual cookie beats a German browser while explicit URL beats the cookie', async ({ context, page }) => {
    await context.addCookies([{ name: 'om_language', value: 'manual:en', url: website }]);
    await page.goto(site('/'));
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('#hero-title')).toHaveText('Your privacy firstAI team mates');
    await page.goto(site('/?lang=de-DE'));
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    await expect(page.locator('#hero-title')).toHaveText('Deine KI-Teamkollegenmit Privatsphäre');
  });
});

// contract-test: direct surface=gui.web assertions=language-preferences.first-paint,language-preferences.resolution,marketing-landing.language-theme
test('German first paint and hydration keep one language without English text mutations', async ({ page }) => {
  const noPrivateStartup = watchPrivateStartup(page);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (/hydration.*mismatch/i.test(message.text())) errors.push(message.text()); });
  await page.addInitScript(() => {
    const states: { language: string | null; heading: string }[] = [];
    Object.assign(window, { __landingLanguages: states });
    new MutationObserver(() => {
      const root = document.querySelector('[data-testid="landing-page"]');
      const heading = document.querySelector('#hero-title');
      if (root && heading?.textContent) states.push({ language: root.getAttribute('lang'), heading: heading.textContent });
    }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['lang'] });
  });
  await page.goto(site('/'), { waitUntil: 'networkidle' });
  await expect(page.getByTestId('landing-open-web-app')).toHaveText('Web-App öffnen');
  const states = await page.evaluate(() => (window as Window & { __landingLanguages?: { language: string | null; heading: string }[] }).__landingLanguages ?? []);
  expect(states.length).toBeGreaterThan(0);
  expect(states.every(state => state.language === 'de' && !state.heading.includes('Your privacy first'))).toBe(true);
  expect(errors).toEqual([]);
  noPrivateStartup();
});

// contract-test: direct surface=gui.web assertions=language-preferences.manual-choice,language-preferences.resolution,marketing-landing.language-theme
test('manual English survives a reload and Automatic returns to German browser language', async ({ page, context }) => {
  await page.goto(site('/'));
  await page.getByTestId('landing-language-button').click();
  const panel = page.getByTestId('landing-language-panel');
  await expect(panel.locator('button[lang]')).toHaveCount(2);
  await panel.getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.getByTestId('landing-open-web-app')).toHaveText('Open Web App');
  await expect(page).toHaveURL(site('/?lang=en'));
  await page.goto(site('/'));
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('#hero-title')).toHaveText('Your privacy firstAI team mates');
  await page.getByTestId('landing-language-button').click();
  await page.getByTestId('landing-language-auto').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBeNull();
  expect((await context.cookies()).find(cookie => cookie.name === 'om_language')?.value).toBe('auto');
  await page.reload();
  await expect(page.getByTestId('landing-open-web-app')).toHaveText('Web-App öffnen');
});

// contract-test: direct surface=gui.web assertions=language-preferences.first-paint,language-preferences.manual-choice
test('legacy manual English is migrated before visible content and retained on subsequent requests', async ({ page, context }) => {
  await page.addInitScript(() => localStorage.setItem('preferredLanguage', 'en'));
  await page.goto(site('/'), { waitUntil: 'networkidle' });
  await expect(page.locator('#hero-title')).toHaveText('Your privacy firstAI team mates');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('html')).toHaveCSS('visibility', 'visible');
  expect(decodeURIComponent((await context.cookies()).find(cookie => cookie.name === 'om_language')?.value ?? '')).toBe('manual:en');
  const html = await (await context.request.get(site('/'))).text();
  expect(html).toContain('<html lang="en" dir="ltr">');
  expect(html).not.toContain('Deine KI-Teamkollegen');
});

// contract-test: direct surface=gui.web assertions=language-preferences.first-paint,language-preferences.resolution,language-preferences.manual-choice
test('Automatic cookie ignores stale manual storage and account defaults preserve legacy manual choice', async ({ page, context }) => {
  await page.addInitScript(() => localStorage.setItem('preferredLanguage', 'en'));
  let documents = 0;
  page.on('request', request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents += 1; });
  await context.addCookies([{ name: 'om_language', value: 'auto', url: website }]);
  await page.goto(site('/'), { waitUntil: 'networkidle' });
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect(page.locator('#hero-title')).toHaveText('Deine KI-Teamkollegenmit Privatsphäre');
  expect(documents, 'Automatic must not reload to apply stale manual storage').toBe(1);
  await context.addCookies([{ name: 'om_language', value: 'account:de', url: website }]);
  await page.goto(site('/'), { waitUntil: 'networkidle' });
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('#hero-title')).toHaveText('Your privacy firstAI team mates');
  expect(decodeURIComponent((await context.cookies()).find(cookie => cookie.name === 'om_language')?.value ?? '')).toBe('manual:en');
});

// contract-test: direct surface=gui.web assertions=language-preferences.content-language,marketing-landing.destinations
test('German public links preserve document language and Automatic mode when entering the app', async ({ page, context }) => {
  await context.addCookies([{ name: 'om_language', value: 'auto', url: website }]);
  await page.goto(site('/'));
  await expect(page.getByTestId('landing-news').locator('a.text-link')).toHaveAttribute('href', site('/de/news?lang=de'));
  await expect(page.getByTestId('landing-blog').locator('a.text-link')).toHaveAttribute('href', site('/de/blog?lang=de'));
  const prompt = new URL((await page.getByTestId('landing-prompt').getAttribute('href'))!);
  expect(prompt.searchParams.has('lang')).toBe(false);
  expect(prompt.hash).toMatch(/^#chat-id=/);
  await page.locator('.site-footer a[href*="/legal/privacy"]').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect(page.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
  await page.getByTestId('landing-open-web-app').click();
  await expect(page).toHaveURL(`${app}/`);
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect(page.getByTestId('profile-container')).toBeVisible();
  expect((await context.cookies()).find(cookie => cookie.name === 'om_language')?.value).toBe('auto');
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBeNull();
});

// contract-test: direct surface=gui.web assertions=language-preferences.manual-choice,language-preferences.resolution,marketing-landing.destinations
test('a fresh browser keeps Automatic mode while a manual English choice survives app entry', async ({ page, context }) => {
  await page.goto(site('/'));
  await expect(page.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/`);
  await page.getByTestId('landing-open-web-app').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect(page.getByTestId('profile-container')).toBeVisible();
  const freshCookie = (await context.cookies()).find(cookie => cookie.name === 'om_language');
  expect(freshCookie ? decodeURIComponent(freshCookie.value) : '').not.toMatch(/^manual:/);
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBeNull();
  await page.goto(site('/'));
  await page.getByTestId('landing-language-button').click();
  await page.getByTestId('landing-language-panel').getByRole('button', { name: 'English', exact: true }).click();
  await expect(page.getByTestId('landing-open-web-app')).toHaveAttribute('href', `${app}/?lang=en`);
  await page.getByTestId('landing-open-web-app').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByTestId('profile-container')).toBeVisible();
  expect(decodeURIComponent((await context.cookies()).find(cookie => cookie.name === 'om_language')?.value ?? '')).toBe('manual:en');
  expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe('en');
});
