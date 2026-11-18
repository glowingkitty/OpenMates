/**
 * Inactive composer drafts with embeds minimize to one summary line (issue 4L9S5).
 * Embeds appear as chat-list tokens such as "[Image]"; focusing the composer
 * restores the rendered embed preview and its controls, blurring minimizes again.
 */
// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

for (const width of [390, 1280]) {
  // contract-test: direct surface=gui.web assertions=message-input.drafts.preview-persistence,message-input.actions.visibility
  test(`blurred image draft minimizes to an [Image] summary and expands on focus at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const params = new URLSearchParams({ chrome: '0', theme: 'dark', background: '#dbeafe',
      width: String(Math.min(width, 680)), variant: 'imageDraft' });
    await page.goto(`/dev/preview/enter_message/MessageInputFocusFixture?${params}`);
    await waitForComponentPreview(page);
    await expect(page.getByTestId('composer-focus-fixture')).toHaveAttribute('data-ready', 'true');
    const field = page.getByTestId('message-field');
    const embed = page.getByTestId('message-editor').getByTestId('embed-preview');
    const summary = page.getByTestId('message-draft-summary-text');

    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(summary).toHaveText('Unsent multiline second line [Image]');
    await expect(embed).toHaveCount(1);
    await expect(embed).toBeHidden();
    await expect(field.getByTestId('action-buttons')).toHaveCount(0);
    await expect(field).toHaveCSS('height', '48px');
    await testInfo.attach(`embed-draft-minimized-${width}`, { body: await field.screenshot(), contentType: 'image/png' });

    await field.click({ position: { x: 8, y: 8 } });
    await expect(field).toHaveAttribute('data-focused', 'true');
    await expect(summary).toHaveCount(0);
    await expect(embed).toBeVisible();
    await expect(field.getByTestId('action-buttons')).toBeVisible();
    await testInfo.attach(`embed-draft-expanded-${width}`, { body: await field.screenshot(), contentType: 'image/png' });

    await page.mouse.click(2, 2);
    await expect(field).toHaveAttribute('data-focused', 'false');
    await expect(summary).toHaveText('Unsent multiline second line [Image]');
    await expect(embed).toBeHidden();
  });
}
