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
