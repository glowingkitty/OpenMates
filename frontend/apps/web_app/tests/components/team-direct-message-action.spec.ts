// playwright-account: not_required reason=isolated_component_preview
import { test, expect, type Page, type TestInfo } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const path = '/dev/preview/settings/TeamMemberMessageAction?theme=light&background=%23dbeafe&chrome=0';

async function visitPreview(page: Page, testInfo: TestInfo, url: string): Promise<void> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.stack ?? error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const response = await page.goto(url);
  if (!response?.ok()) {
    const body = await page.locator('body').innerText().catch(() => 'Body unavailable');
    const diagnosis = `HTTP ${response?.status() ?? 'no response'} at ${url}\n${body}\n${errors.join('\n')}`;
    await testInfo.attach('preview-load-error', { body: diagnosis, contentType: 'text/plain' });
    throw new Error(diagnosis);
  }
  try {
    await waitForComponentPreview(page);
  } catch (error) {
    const body = await page.locator('body').innerText().catch(() => 'Body unavailable');
    await testInfo.attach('preview-readiness-error', {
      body: `Preview did not become ready at ${url}\n${body}\n${errors.join('\n')}`,
      contentType: 'text/plain',
    });
    throw error;
  }
}

// contract-test: supporting surface=gui.web assertions=teams.direct-chat.member-entry-and-notifications,settings-ui.composition.canonical-and-accessible
test('private member action labels its scope and pending secure setup', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1200, height: 900 });
  await visitPreview(page, testInfo, `${path}&width=1200&variant=pending`);
  const button = page.getByRole('button', { name: 'Message', exact: true });
  await expect(button).toBeVisible();
  await expect(page.getByText('Only you and this member can read this chat.')).toBeVisible();
  await button.focus();
  await expect(button).toBeFocused();
  await button.press('Enter');
  await expect(page.getByRole('alert')).toContainText('Secure messaging setup is pending');
  await expect(button).toBeEnabled();
  await testInfo.attach('team-direct-member-pending-desktop', { body: await page.screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=teams.direct-chat.member-entry-and-notifications,settings-ui.composition.canonical-and-accessible
test('private member action keeps loading and failure readable on a phone', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await visitPreview(page, testInfo, `${path}&width=390&variant=loading`);
  const button = page.getByRole('button', { name: 'Message', exact: true });
  await expect(button).toBeVisible();
  await button.click();
  await expect(button).toBeDisabled();
  await expect(button).toHaveAttribute('aria-busy', 'true');
  const box = await button.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await visitPreview(page, testInfo, `${path}&width=390&variant=unavailable`);
  await page.getByRole('button', { name: 'Message', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Could not open a private message');
});

// contract-test: supporting surface=gui.web assertions=teams.direct-chat.member-entry-and-notifications
test('direct chat header keeps the two-person scope visible on desktop and phone', async ({ page }, testInfo) => {
  for (const width of [1200, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await visitPreview(page, testInfo, `/dev/preview/ChatHeader?theme=light&background=%23dbeafe&width=${width}&chrome=0&variant=teamDirect`);
    await expect(page.getByTestId('chat-header-title')).toContainText('Private Team message');
    const badge = page.getByTestId('direct-chat-badge');
    await expect(badge).toHaveText('Only you and this member can read this chat.');
    const box = await badge.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    if (width === 390) await testInfo.attach('team-direct-chat-header-phone', { body: await page.screenshot(), contentType: 'image/png' });
  }
});
