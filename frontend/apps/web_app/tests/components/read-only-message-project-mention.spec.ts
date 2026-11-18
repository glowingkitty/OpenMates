import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
const preview = (theme: 'light' | 'dark') =>
  `/dev/preview/ReadOnlyMessage?theme=${theme}&background=%23dbeafe&width=520&chrome=0&variant=projectMention`;

// contract-test: supporting surface=gui.web assertions=focus-modes.project-specialist-composition
for (const theme of ['light', 'dark'] as const) {
  test(`a sent Project mention shows a readable access chip (${theme})`, async ({ page }, testInfo) => {
    await page.goto(preview(theme));
    await waitForComponentPreview(page);
    const message = page.getByTestId('message-content');
    const mention = message.getByTestId('project-mention-link');
    await expect(mention).toBeVisible();
    const chip = mention.locator('.project-access-chip');
    await expect(chip).toHaveText('Read');
    // The chip label must paint: the link rule makes link text transparent for its gradient.
    const fill = await chip.evaluate((node) => getComputedStyle(node).webkitTextFillColor);
    expect(fill, 'access chip label is not transparent').not.toMatch(/^(transparent|rgba\(0, 0, 0, 0\))$/);
    await testInfo.attach(`project-mention-${theme}`, { body: await message.screenshot(), contentType: 'image/png' });
  });
}
