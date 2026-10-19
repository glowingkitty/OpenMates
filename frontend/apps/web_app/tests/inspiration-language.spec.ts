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
