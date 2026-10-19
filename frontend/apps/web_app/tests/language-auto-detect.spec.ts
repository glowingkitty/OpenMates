import { expect, test } from './helpers/cookie-audit';
import { germanDictionaryPath, waitForNeutralLanguageStartup } from './helpers/language-readiness';

// playwright-account: not_required reason=guest_language_startup
// contract-test: direct surface=gui.web assertions=language-preferences.resolution,language-preferences.first-paint,language-preferences.manual-choice

async function observeWelcome(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    (window as any).__welcomeLanguages = [];
    const record = () => {
      const heading = document.querySelector('[data-testid="chat-welcome-heading"]');
      if (heading?.textContent?.trim()) {
        const sample = { lang: document.documentElement.lang, text: heading.textContent.trim() };
        const samples = (window as any).__welcomeLanguages;
        if (samples.length < 100 && samples.at(-1)?.text !== sample.text) samples.push(sample);
      }
    };
    new MutationObserver(record).observe(document, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['lang'] });
    record();
  });
}

for (const entry of [
  { locale: 'de-DE', expected: 'de', heading: 'Hallo!' },
  { locale: 'de-AT', expected: 'de', heading: 'Hallo!' },
  { locale: 'fr-CA', expected: 'fr', heading: 'Salut toi!' },
  { locale: 'sw-TZ', expected: 'en', heading: 'Hey there!' },
]) {
  // contract-test: direct surface=gui.web assertions=language-preferences.resolution,language-preferences.first-paint,language-preferences.manual-choice
  test(`first app text uses supported browser language ${entry.locale}`, async ({ browser }) => {
    const context = await browser.newContext({ baseURL: test.info().project.use.baseURL, locale: entry.locale, recordVideo: { dir: test.info().outputPath('browser-video') } });
    const page = await context.newPage();
    try {
      await observeWelcome(page);
      await page.goto('/');
      await expect(page.getByTestId('chat-welcome-heading')).toBeVisible({ timeout: 30_000 });
      await expect(page.locator('html')).toHaveAttribute('lang', entry.expected);
      const samples = await page.evaluate(() => (window as any).__welcomeLanguages);
      expect(samples.length).toBeGreaterThan(0);
      expect(samples.every((sample: { lang: string; text: string }) => sample.lang === entry.expected && sample.text === entry.heading)).toBe(true);
      await expect(page.getByTestId('chat-welcome-heading')).toHaveText(entry.heading);
      await expect(page.getByText('Language Detected', { exact: true })).toHaveCount(0);
      await page.reload();
      await expect(page.getByTestId('chat-welcome-heading')).toBeVisible();
      await expect(page.locator('html')).toHaveAttribute('lang', entry.expected);
    } finally {
      const video = page.video();
      await context.close();
      if (video) await test.info().attach('video', { path: await video.path(), contentType: 'video/webm' });
    }
  });
}

// contract-test: direct surface=gui.web assertions=language-preferences.resolution,language-preferences.first-paint,language-preferences.manual-choice
test('a saved English choice wins over German and an explicit URL can change it', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL, locale: 'de-DE', recordVideo: { dir: test.info().outputPath('browser-video') } });
  const page = await context.newPage();
  try {
    await page.addInitScript(() => localStorage.setItem('preferredLanguage', 'en'));
    await observeWelcome(page);
    await page.goto('/');
    await expect(page.getByTestId('chat-welcome-heading')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await page.goto('/?lang=de');
    await expect(page.getByTestId('chat-welcome-heading')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  } finally {
      const video = page.video();
      await context.close();
      if (video) await test.info().attach('video', { path: await video.path(), contentType: 'video/webm' });
    }
});

// contract-test: direct surface=gui.web assertions=language-preferences.resolution,language-preferences.first-paint,language-preferences.manual-choice
test('a delayed German dictionary exposes only a neutral shell before German text', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('preferredLanguage', 'de'));
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let dictionaryRequested = false;
  const dictionaryPath = await germanDictionaryPath(testInfo);
  await page.route(url => url.pathname === dictionaryPath, async route => {
    dictionaryRequested = true;
    await gate;
    await route.continue();
  });
  await observeWelcome(page);
  try {
    await page.goto('/', { waitUntil: 'commit' });
    await expect.poll(() => dictionaryRequested, { message: 'German dictionary response intercepted', timeout: 15_000 }).toBe(true);
    await waitForNeutralLanguageStartup(page, testInfo);
    release();
    await expect(page.getByTestId('chat-welcome-heading')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    const samples = await page.evaluate(() => (window as any).__welcomeLanguages);
    expect(samples.length).toBeGreaterThan(0);
    expect(samples.every((sample: {lang: string; text: string}) => sample.lang === 'de' && sample.text === 'Hallo!')).toBe(true);
  } finally {
    release();
    // All intercepted module requests must finish before the page is torn down.
    await page.unrouteAll({ behavior: 'wait' });
  }
});

// contract-test: direct surface=gui.web assertions=language-preferences.manual-choice,language-preferences.resolution
test('an explicit selection supersedes an incoming German URL hint', async ({ page }) => {
  await page.goto('/?lang=de#settings/interface/language');
  await expect(page.getByTestId('language-option-en')).toBeVisible({ timeout: 30_000 });
  await page.getByTestId('language-option-en').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  expect(new URL(page.url()).searchParams.has('lang')).toBe(false);
  await page.reload();
  await expect(page.getByTestId('chat-welcome-heading')).toHaveText('Hey there!', { timeout: 30_000 });
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  // Startup consumes ordinary settings deep links. Reopen the control to inspect
  // persisted language; URL/hash preservation is covered by languageCoordinator.
  await page.goto('/#settings/interface/language');
  await expect(page.getByTestId('language-option-en').locator('input')).toBeChecked({ timeout: 30_000 });
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

// contract-test: direct surface=gui.web assertions=language-preferences.first-paint
test('an existing local German account locale is ready before the first app text', async ({ page }) => {
  // Seed only the existing local preference store; no network account or personal data is used.
  await page.goto('/dev/preview/settings/interface/SettingsLanguage?chrome=0');
  await page.evaluate(async () => {
    localStorage.removeItem('preferredLanguage');
    localStorage.removeItem('openmatesLanguageMode');
    localStorage.removeItem('openmatesAccountLanguage');
    document.cookie = 'om_language=; Max-Age=0; Path=/';
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('user_db');
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains('user_data')) request.result.createObjectStore('user_data');
      };
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction('user_data', 'readwrite');
        transaction.objectStore('user_data').put('language-proof-local-account', 'id');
        transaction.objectStore('user_data').put('de', 'language');
        transaction.oncomplete = () => { database.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  });
  await observeWelcome(page);
  await page.goto('/');
  await expect(page.getByTestId('chat-welcome-heading')).toHaveText('Hallo!', { timeout: 30_000 });
  const samples = await page.evaluate(() => (window as any).__welcomeLanguages);
  expect(samples.length).toBeGreaterThan(0);
  expect(samples.every((sample: {lang: string; text: string}) => sample.lang === 'de' && sample.text === 'Hallo!')).toBe(true);
});
