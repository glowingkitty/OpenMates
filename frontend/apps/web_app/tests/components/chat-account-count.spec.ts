// playwright-account: not_required reason=isolated_component_preview
import { expect, test } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const preview = '/dev/preview/chats/ChatAccountCount?chrome=0&theme=light&background=%23dbeafe&width=325';

// contract-test: supporting surface=gui.web assertions=sync.startup.recent-metadata-cap
test('account chat count displays the full total above the recent window', async ({ page }, testInfo) => {
  await page.goto(preview, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  const count = page.getByTestId('chat-account-total');
  await expect(count).toBeVisible();
  await expect(count).toHaveAttribute('data-chat-count', '1284');
  await expect(count).toContainText('1,284');
  await testInfo.attach('account-chat-count', { body: await count.screenshot(), contentType: 'image/png' });

  await page.goto(`${preview}&variant=atRecentLimit`, { waitUntil: 'domcontentloaded' });
  await waitForComponentPreview(page);
  await expect(count).toHaveCount(0);
});
