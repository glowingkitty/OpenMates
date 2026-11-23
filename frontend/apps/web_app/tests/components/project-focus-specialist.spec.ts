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
  // The long Project part is truncated; the full identity stays in the title.
  expect(await label.evaluate((element) => [element, ...element.children].some((part) => part.scrollWidth > part.clientWidth))).toBe(true);
  const pill = page.getByTestId('focus-pill');
  expect(await pill.evaluate((element) => element.getBoundingClientRect().right <= innerWidth)).toBe(true);
  await pill.locator('button.focus-pill-body').focus();
  await expect(pill.locator('button.focus-pill-body')).toBeFocused();
});

// contract-test: direct surface=gui.web assertions=focus-modes.project-layering
for (const width of [390, 720]) {
  test(`a layered focus stays readable next to its Project at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`/dev/preview/enter_message/MessageInput?chrome=0&variant=layeredWriteSpecification&width=${width}`);
    await waitForComponentPreview(page);
    const label = page.getByTestId('focus-pill-label');
    await expect(label).toHaveText('Garden planner: green island | Write specification');
    await expect(label).toHaveAttribute('title', 'Garden planner: green island | Write specification');
    const layer = page.getByTestId('focus-pill-layer');
    await expect(layer).toBeVisible();
    expect(await layer.evaluate((element) => element.scrollWidth <= element.clientWidth), 'the layered focus name is not cut off').toBe(true);
    expect(await layer.evaluate((element) => element.getBoundingClientRect().right
      <= (element.parentElement as HTMLElement).getBoundingClientRect().right + 0.5), 'the label does not clip the layered focus').toBe(true);
    const pill = page.getByTestId('focus-pill');
    expect(await pill.evaluate((element) => element.getBoundingClientRect().right <= innerWidth)).toBe(true);
    await testInfo.attach(`layered-pill-${width}`, { body: await pill.screenshot(), contentType: 'image/png' });
  });
}
