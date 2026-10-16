// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Shared Playwright helpers use CommonJS. */
export {};

import { waitForComponentPreview } from '../helpers/component-preview';
const { test, expect } = require('../helpers/cookie-audit');

// contract-test: supporting surface=gui.web assertions=sync.deletion.partial-window-not-authoritative
test('confirmed chat deletion survives old and fresh stale list reads', async ({ page }) => {
  await page.goto(`/dev/preview/chats/ChatListDeletionPreview?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: '325', chrome: '0',
  })}`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(page.getByTestId('preview-toolbar')).toHaveCount(0);

  const rows = page.getByTestId('chat-list-deletion-preview').getByTestId('chat-item-wrapper');
  const deleted = rows.filter({ hasText: 'README review' });
  await expect(rows).toHaveCount(2);
  await expect(deleted).toBeVisible();

  await page.getByTestId('preview-start-chat-read').click();
  await page.getByTestId('preview-delete-chat').click();
  await expect(deleted).toHaveCount(0);
  await expect(rows).toHaveCount(1);

  await page.getByTestId('preview-complete-old-read').click();
  await expect(deleted).toHaveCount(0);
  await expect(rows).toHaveCount(1);

  await page.getByTestId('preview-refresh-after-delete').click();
  await expect(deleted).toHaveCount(0);
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('Launch copy');
  await expect(rows.last()).toContainText('Saved notes');
  await rows.first().screenshot({ path: test.info().outputPath('chat-list-deletion-kept-row.png') });
});
