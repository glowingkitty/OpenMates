// Component preview proof for the helpline card (wellbeing-support.helpline-card).
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const PREVIEW = '/dev/preview/embeds/wellbeing/HelplineCard?chrome=0&theme=light&background=%23dbeafe';
test.use({ trace: 'retain-on-failure' });

for (const width of [350, 700]) {
  // contract-test: supporting surface=gui.web assertions=wellbeing-support.helpline-card
  test(`German card lists two lines with call and chat actions at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: width + 40, height: 844 });
    await page.goto(`${PREVIEW}&width=${width}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('helpline-card');
    await expect(card).toContainText("You don't have to go through this alone");
    await expect(page.getByTestId('helpline-entry')).toHaveCount(2);
    await expect(page.getByTestId('helpline-call')).toHaveCount(2);
    await expect(page.getByTestId('helpline-call').first()).toHaveAttribute('href', 'tel:08000000000');
    await expect(page.getByTestId('helpline-chat')).toHaveCount(1);
    await expect(page.getByTestId('helpline-emergency')).toContainText('112');
    await expect(page.getByTestId('helpline-directory-link')).toHaveAttribute('href', 'https://example.org/helplines');
    expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await testInfo.attach(`de-two-lines-${width}`, { body: await card.screenshot(), contentType: 'image/png' });
  });

  // contract-test: supporting surface=gui.web assertions=wellbeing-support.helpline-card

  test(`US card shows call, text and chat actions at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: width + 40, height: 844 });
    await page.goto(`${PREVIEW}&variant=us&width=${width}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('helpline-card');
    await expect(page.getByTestId('helpline-entry')).toHaveCount(3);
    await expect(page.getByTestId('helpline-sms').first()).toHaveAttribute('href', /^sms:/);
    await expect(page.getByTestId('helpline-chat')).toHaveCount(2);
    await expect(page.getByTestId('helpline-emergency')).toContainText('911');
    expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    await testInfo.attach(`us-three-lines-${width}`, { body: await card.screenshot(), contentType: 'image/png' });
  });

  // contract-test: supporting surface=gui.web assertions=wellbeing-support.helpline-card

  test(`emergency-only card shows just the number and the directory link at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: width + 40, height: 844 });
    await page.goto(`${PREVIEW}&variant=emergency_only&width=${width}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('helpline-card');
    await expect(page.getByTestId('helpline-entry')).toHaveCount(0);
    await expect(page.getByTestId('helpline-emergency')).toContainText('999');
    await expect(page.getByTestId('helpline-directory-link')).toBeVisible();
    await testInfo.attach(`emergency-only-${width}`, { body: await card.screenshot(), contentType: 'image/png' });
  });
}
