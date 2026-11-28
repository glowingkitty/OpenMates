// playwright-account: not_required reason=isolated_component_preview
/**
 * Focused component spec: Specification and Check embeds show the sub-chats of
 * the Plan's assumptions and Tasks. Uses synthetic preview fixtures only.
 */
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const SPEC = '/dev/preview/embeds/specifications/SpecificationEmbedFullscreen?chrome=0&theme=light&variant=with-plan';
const SPEC_CARD = '/dev/preview/embeds/specifications/SpecificationEmbedPreview?chrome=0&theme=light&variant=with-plan&width=420';
const CHECK = '/dev/preview/embeds/checks/CheckEmbedFullscreen?chrome=0&theme=light&variant=with-plan-tasks';
test.use({ viewport: { width: 1000, height: 800 }, trace: 'retain-on-failure' });

const opened = (page: import('@playwright/test').Page) => page.evaluate(() => (window as unknown as { __openedChat?: string }).__openedChat);

// contract-test: supporting surface=gui.web assertions=contracts.ui.human-readable-default
test('Specification fullscreen opens the checking and working chats', async ({ page }, testInfo) => {
  await page.goto(SPEC);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('specification-assumption-open-chat')).toHaveCount(2);
  await expect(page.getByTestId('specification-assumption-status').first()).toBeVisible();
  await expect(page.getByTestId('specification-task-row')).toHaveCount(3);
  await expect(page.getByTestId('specification-task-open-chat')).toHaveCount(2);
  await page.getByTestId('spec-assumptions').scrollIntoViewIfNeeded();
  await testInfo.attach('spec-assumptions', { body: await page.getByTestId('spec-assumptions').screenshot(), contentType: 'image/png' });
  await page.getByTestId('specification-assumption-open-chat').first().click();
  expect(await opened(page)).toBe('preview-chat-assumption-1');
  await page.getByTestId('specification-task-open-chat').nth(1).scrollIntoViewIfNeeded();
  await testInfo.attach('spec-tasks', { body: await page.getByTestId('spec-plan-tasks').screenshot(), contentType: 'image/png' });
  await page.getByTestId('specification-task-open-chat').nth(1).click();
  expect(await opened(page)).toBe('preview-chat-task-2');
});

// contract-test: supporting surface=gui.web assertions=contracts.ui.human-readable-default
test('Specification card shows the assumptions and Tasks count', async ({ page }, testInfo) => {
  await page.goto(SPEC_CARD);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('specification-plan-summary')).toHaveText('1 assumption being checked · 3 Tasks');
  await testInfo.attach('spec-card', { body: await page.getByTestId('specification-embed-card').screenshot(), contentType: 'image/png' });
});

// contract-test: supporting surface=gui.web assertions=contracts.ui.human-readable-default
test('Check fullscreen lists only Tasks naming a covered requirement', async ({ page }, testInfo) => {
  await page.goto(CHECK);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('check-task-row')).toHaveCount(1);
  await expect(page.getByTestId('check-plan-tasks')).toContainText('Build the payment step');
  await testInfo.attach('check-tasks', { body: await page.getByTestId('check-plan-tasks').screenshot(), contentType: 'image/png' });
  await page.getByTestId('check-task-open-chat').click();
  expect(await opened(page)).toBe('preview-chat-task-pay');
});

// contract-test: supporting surface=gui.web assertions=contracts.ui.human-readable-default
test('Check from the chat opens the Plan assumption checking chat', async ({ page }, testInfo) => {
  await page.goto('/dev/preview/embeds/checks/CheckSkillEmbedFullscreen?chrome=0&theme=light&variant=with-checking-chat');
  await waitForComponentPreview(page);
  const assumptions = page.getByTestId('plan-assumptions-list');
  await expect(assumptions).toContainText('Orders reach the checkout service');
  await testInfo.attach('check-assumption', { body: await assumptions.screenshot(), contentType: 'image/png' });
  await assumptions.getByTestId('plan-assumption-open-chat').click();
  await expect(page).toHaveURL(/#chat-id=preview-chat-assumption-delivery$/);
});

// contract-test: supporting surface=gui.web assertions=contracts.ui.human-readable-default
test('Check without matching Tasks shows no Task section', async ({ page }) => {
  await page.goto('/dev/preview/embeds/checks/CheckEmbedFullscreen?chrome=0&theme=light');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('check-plan-tasks')).toHaveCount(0);
});
