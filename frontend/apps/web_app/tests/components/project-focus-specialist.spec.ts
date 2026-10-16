import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
// playwright-account: not_required reason=isolated_component_preview

// contract-test: direct surface=gui.web assertions=focus-modes.project-specialist-composition
test('one active specialist displays its Project and full Focus identity', async ({ page }) => {
  await page.goto('/dev/preview/enter_message/MessageInput?chrome=0&variant=projectSpecialist&width=720');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('focus-pill')).toHaveCount(1);
  await expect(page.getByTestId('focus-pill-label')).toHaveText('OpenMates | Debugging');
  await expect(page.getByTestId('focus-pill-label')).toHaveAttribute('title', 'OpenMates | Debugging');
  await expect(page.getByText('Work on OpenMates', { exact: true })).toHaveCount(0);
});

// contract-test: direct surface=gui.web assertions=focus-modes.project-specialist-composition
test('phone truncation preserves the full identity for details', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/enter_message/MessageInput?chrome=0&variant=longProjectSpecialist&width=390');
  await waitForComponentPreview(page);
  const label = page.getByTestId('focus-pill-label');
  const identity = 'A very long Project title for a narrow phone screen | Investigating a complicated application failure';
  await expect(label).toHaveText(identity);
  await expect(label).toHaveAttribute('title', identity);
  expect(await label.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  const pill = page.getByTestId('focus-pill');
  expect(await pill.evaluate((element) => element.getBoundingClientRect().right <= innerWidth)).toBe(true);
  await pill.locator('button.focus-pill-body').focus();
  await expect(pill.locator('button.focus-pill-body')).toBeFocused();
});
