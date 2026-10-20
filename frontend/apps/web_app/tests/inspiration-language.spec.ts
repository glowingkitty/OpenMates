import { expect, test } from './helpers/cookie-audit';

// playwright-account: not_required
// contract-test: direct surface=gui.web assertions=language-preferences.content-language,daily-inspiration.public-defaults
test('German public inspirations remain localized through carousel navigation and reload', async ({ page }) => {
  const api = process.env.PLAYWRIGHT_TEST_API_URL || 'https://api.dev.openmates.org';
  const response = await page.request.get(`${api}/v1/default-inspirations?lang=de`);
  expect(response.ok()).toBe(true);
  const { inspirations } = await response.json();
  expect(inspirations).toHaveLength(10);
  expect(inspirations.every((item: { language: string }) => item.language === 'de')).toBe(true);
  for (const item of inspirations) {
    expect(item.phrase.trim()).not.toBe('');
    expect(['video', 'wiki', 'feature']).toContain(item.content_type);
    // Editorial decisions stay internal; the public feed retains its source-backed shape.
    expect(item).not.toHaveProperty('editorial_score');
    expect(item).not.toHaveProperty('editorial_category');
    if (item.content_type === 'wiki') expect(item.wiki.wiki_title.trim()).not.toBe('');
    if (item.content_type === 'video') expect(item.video.youtube_id).toMatch(/^[\w-]{11}$/);
  }
  const phrases = inspirations.map((item: { phrase: string }) => item.phrase);
  expect(phrases).not.toContain('Want stronger privacy controls? Add personal details that OpenMates should hide.');
  expect(phrases).not.toContain('An ancient shipwreck held a machine that predicted the sky.');

  await page.goto('/?lang=de');
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
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
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect.poll(async () => phrases.includes((await phrase.innerText()).trim())).toBe(true);
});

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
