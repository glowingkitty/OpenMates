import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// contract-test: direct surface=gui.web assertions=app-memories.transparency.loaded-set,app-memories.definition.context-documents
test('shows short app and project memory pills, disclosing exact guides on request', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/LoadedMemoryPills?chrome=0&theme=light&background=%23dbeafe&width=350');
  await waitForComponentPreview(page);
  const pills = page.getByTestId('loaded-memory-pill');
  await expect(pills).toHaveCount(2);
  await expect(pills.first()).toHaveText('Flowchart');
  const iconAppearance = await pills.locator('.icon').evaluateAll((icons) => icons.map((icon) => ({
    background: getComputedStyle(icon).backgroundImage,
    image: getComputedStyle(icon, '::before').backgroundImage,
    source: (icon as HTMLElement).style.getPropertyValue('--icon-url'),
    circle: getComputedStyle(icon.parentElement!).borderRadius,
  })));
  expect(iconAppearance).toHaveLength(2);
  expect(iconAppearance[0].background).toContain('gradient');
  expect(iconAppearance[0].source).toContain('--icon-url-diagram');
  expect(iconAppearance[0].image).toContain('data:image/svg+xml');
  expect(iconAppearance[0].circle).toBe('50%');
  expect(iconAppearance[1].background).toContain('gradient');
  expect(iconAppearance[1].source).toContain('--icon-url-project');
  expect(iconAppearance[1].image).toContain('data:image/svg+xml');
  expect(iconAppearance[1].circle).toBe('50%');
  await expect(page.getByTestId('applied-memory-body').first()).toBeHidden();
  await expect(page.getByTestId('applied-rule-revision').first()).toBeHidden();
  await pills.first().focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('applied-memory-body').first()).toHaveText('- Use clear direction.\n- Keep labels short.');
  await expect(page.getByTestId('applied-rule-revision').first()).toContainText('a'.repeat(64));
  await pills.last().click();
  await expect(page.getByTestId('applied-memory').last()).toContainText('Fictional Project');
  expect(await page.getByTestId('loaded-memory-pills').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});
