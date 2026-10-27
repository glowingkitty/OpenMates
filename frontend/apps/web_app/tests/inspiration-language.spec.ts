import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required
for (const language of ['de', 'ja']) {
// contract-test: direct surface=gui.web assertions=language-preferences.content-language,daily-inspiration.public-defaults
test(`${language} public inspirations remain localized through carousel navigation and reload`, async ({ page }) => {
  const api = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
  const response = await page.request.get(`${api}/v1/default-inspirations?lang=${language}`);
  expect(response.ok()).toBe(true);
  const { inspirations } = await response.json();
  expect(inspirations).toHaveLength(10);
  expect(inspirations.every((item: { language: string }) => item.language === language)).toBe(true);
  for (const item of inspirations) {
    expect(item.phrase.trim()).not.toBe('');
    expect(item.assistant_response.trim()).not.toBe('');
    // Static wiki/feature recovery intentionally has no generated follow-ups.
    // The writer's exact-three admission contract is tested at generation.
    expect(Array.isArray(item.follow_up_suggestions)).toBe(true);
    expect(item.follow_up_suggestions.length).toBeLessThanOrEqual(3);
    for (const suggestion of item.follow_up_suggestions) expect(suggestion.trim()).not.toBe('');
    expect(['video', 'wiki', 'feature']).toContain(item.content_type);
    // Editorial decisions stay internal; the public feed retains its source-backed shape.
    expect(item).not.toHaveProperty('editorial_score');
    expect(item).not.toHaveProperty('editorial_category');
    // Granular rejection codes and source-repair metadata remain server-internal.
    expect(item).not.toHaveProperty('rejection_feedback');
    expect(item).not.toHaveProperty('_review_identity');
    expect(item).not.toHaveProperty('pending_source_ids');
    if (item.content_type === 'wiki') expect(item.wiki.wiki_title.trim()).not.toBe('');
    if (item.content_type === 'video') expect(item.video.youtube_id).toMatch(/^[\w-]{11}$/);
  }
  if (language === 'ja') {
    expect(inspirations.some((item: { phrase: string }) => /[ぁ-ゖァ-ヺ一-龯]/.test(item.phrase))).toBe(true);
  }
  if (language === 'de') {
    const locales = ['en', 'de', 'zh', 'es', 'fr', 'pt', 'ru', 'ja', 'ko', 'it', 'tr', 'vi', 'id', 'pl', 'nl', 'ar', 'hi', 'th', 'cs', 'sv'];
    for (const locale of locales) {
      const localizedResponse = await page.request.get(`${api}/v1/default-inspirations?lang=${locale}`);
      expect(localizedResponse.ok()).toBe(true);
      const localized = (await localizedResponse.json()).inspirations;
      expect(localized).toHaveLength(10);
      expect(localized.every((item: { language: string }) => item.language === locale)).toBe(true);
      if (locale !== 'en') {
        expect(localized.map((item: { phrase: string }) => item.phrase)).not.toContain('An ancient shipwreck held a machine that predicted the sky.');
      }
    }
  }
  const phrases = inspirations.map((item: { phrase: string }) => item.phrase);
  expect(phrases).not.toContain('Want stronger privacy controls? Add personal details that OpenMates should hide.');
  expect(phrases).not.toContain('An ancient shipwreck held a machine that predicted the sky.');

  await page.goto(`/?lang=${language}`);
  await expect(page.locator('html')).toHaveAttribute('lang', language);
  const phrase = page.getByTestId('daily-inspiration-phrase').first();
  const banner = page.getByTestId('daily-inspiration-banner').first();
  await expect.poll(async () => (await banner.getAttribute('data-visible-inspiration-ids') || '').split(',').length).toBe(10);
  await expect.poll(async () => phrases.includes((await phrase.innerText()).trim())).toBe(true);
  const visited = new Set<string>();
  for (let index = 0; index < 10; index += 1) {
    const text = (await phrase.innerText()).trim();
    expect(phrases).toContain(text);
    visited.add(text);
    if (index < 9) {
      await page.getByTestId('daily-inspiration-next').first().click();
      await expect(phrase).not.toHaveText(text);
    }
  }
  expect(visited.size).toBe(10);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', language);
  await expect.poll(async () => phrases.includes((await phrase.innerText()).trim())).toBe(true);
});

}

// contract-test: direct surface=gui.web assertions=daily-inspiration.guest-isolated,daily-inspiration.public-defaults
test('Withheld editorial inventory keeps the ten-card guest fallback usable', async ({ page }) => {
  await page.route('**/v1/default-inspirations?*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ inspirations: [] }) })
  );
  await page.goto('/?lang=de');
  const banner = page.getByTestId('daily-inspiration-banner').first();
  const phrase = page.getByTestId('daily-inspiration-phrase').first();
  await expect.poll(async () => (await banner.getAttribute('data-visible-inspiration-ids') || '').split(',').length).toBe(10);
  await expect(phrase).toBeVisible();
  const first = (await phrase.innerText()).trim();
  expect(first).not.toBe('');
  await page.getByTestId('daily-inspiration-next').first().click();
  await expect(phrase).not.toHaveText(first);
  await page.reload();
  await expect(phrase).toBeVisible();
  await expect.poll(async () => (await banner.getAttribute('data-visible-inspiration-ids') || '').split(',').length).toBe(10);
});
