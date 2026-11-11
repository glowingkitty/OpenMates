import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

const PREVIEW = '/dev/preview/EmbedUpdatedEventNotice?chrome=0&width=360';
test.use({ trace: 'retain-on-failure' });

const states = [
  { variant: '', text: 'Image enhanced · version 3', assertion: 'embed-user-edits.event.chat-notice' },
  { variant: 'edit', text: 'Document edited · version 2', assertion: 'embed-user-edits.event.chat-notice' },
  { variant: 'restore', text: 'Sheet restored to version 2 · version 5', assertion: 'embed-user-edits.event.chat-notice' },
  { variant: 'crop', text: 'Image cropped · version 4', assertion: 'embed-user-edits.event.chat-notice' },
  { variant: 'collapsedEdits', text: 'Slides edited 4 times · version 7', assertion: 'embed-user-edits.event.collapse' },
  { variant: 'collapsedMixed', text: 'Image updated, 3 changes · version 6', assertion: 'embed-user-edits.event.collapse' },
];

for (const theme of ['light', 'dark']) {
  for (const state of states) {
    // contract-test: supporting surface=gui.web assertions=embed-user-edits.event.chat-notice,embed-user-edits.event.collapse
    test(`renders "${state.text}" as one quiet centred line (${theme})`, async ({ page }, testInfo) => {
      await page.goto(`${PREVIEW}&theme=${theme}${state.variant ? `&variant=${state.variant}` : ''}`);
      await waitForComponentPreview(page);
      const row = page.getByTestId('embed-updated-event');
      await expect(row).toBeVisible();
      await expect(row.getByRole('button')).toContainText(state.text);
      const note = row.getByRole('note');
      const box = (await note.boundingBox())!;
      const rowBox = (await row.boundingBox())!;
      expect(box.height).toBeLessThan(60);
      expect(Math.abs(box.x + box.width / 2 - (rowBox.x + rowBox.width / 2))).toBeLessThanOrEqual(2);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await testInfo.attach(`${state.variant || 'enhance'}-${theme}`, { body: await row.screenshot(), contentType: 'image/png' });
    });
  }
}

// contract-test: supporting surface=gui.web assertions=embed-user-edits.event.chat-notice
test('is keyboard focusable with an Open hint, and is plain text without an open action', async ({ page }) => {
  await page.goto(`${PREVIEW}&theme=light`);
  await waitForComponentPreview(page);
  const button = page.getByTestId('embed-updated-event').getByRole('button');
  await button.focus();
  await expect(button).toBeFocused();
  await expect(button).toHaveAccessibleName('Image enhanced · version 3. Open');
  await page.goto(`${PREVIEW}&theme=light&variant=readOnly`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('embed-updated-event')).toContainText('Image enhanced · version 3');
  await expect(page.getByTestId('embed-updated-event').getByRole('button')).toHaveCount(0);
});
