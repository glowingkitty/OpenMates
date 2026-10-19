import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=language-preferences.manual-choice,settings-ui.composition.canonical-and-accessible
for (const width of [390, 1440]) {
  test(`language settings apply an explicit choice and Automatic (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'languages', { value: ['de-DE', 'en'] });
      Object.defineProperty(navigator, 'language', { value: 'de-DE' });
    });
    const query = new URLSearchParams({ theme: 'light', background: '#dbeafe', width: String(width), chrome: '0' });
    await page.goto(`/dev/preview/settings/interface/SettingsLanguage?${query}`);
    await waitForComponentPreview(page);
    const automatic = page.getByTestId('language-option-auto');
    await expect(automatic).toContainText('Automatisch');
    await expect(automatic.locator('input')).toBeChecked();
    await page.getByTestId('language-option-en').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByTestId('language-option-en').locator('input')).toBeChecked();
    await expect(automatic.locator('input')).not.toBeChecked();
    // German matches the browser, but selecting it must still apply and save it.
    await page.getByTestId('language-option-de').click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    await expect(page.getByTestId('language-option-de').locator('input')).toBeChecked();
    expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBe('de');
    await page.reload();
    await waitForComponentPreview(page);
    await expect(page.getByTestId('language-option-de').locator('input')).toBeChecked();
    await automatic.click();
    await expect(automatic.locator('input')).toBeChecked();
    await expect(page.locator('html')).toHaveAttribute('lang', 'de');
    expect(await page.evaluate(() => localStorage.getItem('preferredLanguage'))).toBeNull();
    expect(await page.locator('body').evaluate(element => element.scrollWidth <= window.innerWidth)).toBe(true);
    await page.goto(`/dev/preview/settings/SettingsAccount?${query}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('account-language')).toContainText('Sprache');
    await expect(page.getByTestId('account-language')).toContainText('Deutsch');
    await expect(page.getByTestId('account-language')).toBeInViewport();
    expect(await page.locator('body').evaluate(element => element.scrollWidth <= window.innerWidth)).toBe(true);
  });
}
