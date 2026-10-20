import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=language-preferences.content-language,daily-inspiration.opened-state
test('German personalized inspiration carousel preserves opened chat actions', async ({ page }) => {
  await page.goto('/dev/preview/DailyInspirationBanner?chrome=0&variant=germanPersonalized&width=1100');
  await waitForComponentPreview(page);
  const banner = page.getByTestId('daily-inspiration-banner');
  const phrase = page.getByTestId('daily-inspiration-phrase');
  await expect(banner).toHaveAttribute('data-inspiration-source', 'personalized');
  await expect(phrase).toContainText('sechs Frauen');
  await page.getByTestId('daily-inspiration-previous').click();
  await expect(phrase).toContainText('Gehirn ganze Welten');
  await expect(page.getByTestId('daily-inspiration-cta-text')).toContainText('Chat öffnen');
  await page.getByTestId('daily-inspiration-next').focus();
  await page.keyboard.press('Enter');
  await expect(phrase).toContainText('sechs Frauen');
  await expect(page.getByTestId('daily-inspiration-cta-text')).not.toContainText('Chat öffnen');
});

// contract-test: direct surface=gui.web assertions=language-preferences.content-language,daily-inspiration.public-defaults
test('Japanese static wiki card opens its canonical source edition', async ({ page }) => {
  await page.goto('/dev/preview/DailyInspirationBanner?theme=light&background=%23dbeafe&chrome=0&variant=japaneseWiki&width=1100');
  await waitForComponentPreview(page);
  const phrase = page.getByTestId('daily-inspiration-phrase');
  await expect(phrase).toBeVisible();
  await expect(phrase).toContainText(/[ぁ-ゖァ-ヺ一-龯]/);
  await page.evaluate(() => {
    document.addEventListener('wikifullscreen', (event) => {
      (window as Window & { openedWiki?: unknown }).openedWiki = (event as CustomEvent).detail;
    });
  });
  await page.locator('.banner-embed-wrapper').click();
  const opened = await page.evaluate(() => (window as Window & { openedWiki?: { language: string; wikiTitle: string; displayText: string } }).openedWiki);
  expect(opened).toMatchObject({ language: 'en', wikiTitle: 'Antikythera_mechanism', displayText: 'Antikythera mechanism' });
  await expect(phrase).toContainText(/[ぁ-ゖァ-ヺ一-龯]/);
});
