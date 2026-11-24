import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed

const BASE = '/dev/preview/embeds/shared/LiveHeaderStatus?chrome=0&theme=light&background=%23dbeafe&width=420';
const STATES = ['saved', 'saving', 'offline', 'read_only', 'access_revoked'] as const;

// contract-test: supporting surface=gui.web assertions=live-collab.saving.automatic,live-collab.presence.who-and-where
test('the header status shows every state and who is present', async ({ page }, testInfo) => {
  for (const status of STATES) {
    await page.goto(`${BASE}&props=${encodeURIComponent(JSON.stringify({ status }))}`);
    await waitForComponentPreview(page);
    const header = page.getByTestId('live-header-status');
    await expect(header).toHaveAttribute('data-status', status);
    await expect(page.getByTestId('live-status')).toBeVisible();
    await expect(page.getByTestId('live-status')).not.toHaveText('');
    await expect(page.getByTestId('live-peer')).toHaveCount(2);
    await expect(page.getByTestId('live-peer').first()).toHaveText('M');
    await testInfo.attach(`${status}-420`, { body: await header.screenshot(), contentType: 'image/png' });
  }
});

// contract-test: supporting surface=gui.web assertions=live-collab.presence.who-and-where
test('shows the assistant editing even when it has no cursor', async ({ page }, testInfo) => {
  const peers = [{ user_id: 'assistant', display_name: 'Assistant', mate_name: 'Assistant', color: '#1c7ed6' }];
  await page.goto(`${BASE}&props=${encodeURIComponent(JSON.stringify({ peers }))}`);
  await waitForComponentPreview(page);
  const header = page.getByTestId('live-header-status');
  await expect(header.getByTestId('live-assistant-editing')).toHaveText('Assistant is editing here');
  await testInfo.attach('assistant-editing-420', { body: await header.screenshot(), contentType: 'image/png' });
});
