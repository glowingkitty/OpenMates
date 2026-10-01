import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

// playwright-account: not_required reason=isolated_component_preview

// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
test('Chat Settings header follows viewport changes while the page stays open', async ({ page }) => {
  await page.setViewportSize({ width: 405, height: 874 });
  await page.goto('/dev/preview/chats/ChatSettingsPreviewHarness?chrome=0');
  await waitForComponentPreview(page);
  const header = page.getByTestId('chat-settings-header');
  const height = () => header.evaluate((element) => element.getBoundingClientRect().height);
  await expect.poll(height).toBe(220);
  await page.setViewportSize({ width: 1376, height: 1032 });
  await expect.poll(height).toBe(250);
  await page.setViewportSize({ width: 405, height: 874 });
  await expect.poll(height).toBe(220);
});

// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible,chat-share-settings.shell-navigation
test('Chat Settings preview renders real tabs and share controls without API access', async ({ page }) => {
  const syntheticRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('preview-chat-settings') && request.url().includes('/v1/')) syntheticRequests.push(request.url());
  });
  await page.goto('/dev/preview/chats/ChatSettingsPreviewHarness?chrome=0&variant=share');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-settings-header')).toBeVisible();
  await expect(page.getByTestId('chat-settings-title')).toHaveText('Launch preparation');
  const password = page.getByTestId('chat-settings-share-password');
  await expect(password).toBeVisible();
  await password.click();
  await expect(page.getByTestId('chat-settings-share-password-input')).toBeVisible();
  await page.getByTestId('chat-settings-share-expire').click();
  await page.getByTestId('share-generate-link').click();
  expect(syntheticRequests).toEqual([]);
});

// contract-test: direct surface=gui.web assertions=chat-share-settings.readonly-viewer-controls
test('shared Chat Settings suppresses owner controls', async ({ page }) => {
  await page.goto('/dev/preview/chats/ChatSettingsPreviewHarness?chrome=0&variant=shared');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-settings-share-readonly')).toBeVisible();
  await expect(page.getByTestId('chat-settings-share-password')).toHaveCount(0);
  await expect(page.getByTestId('share-generate-link')).toHaveCount(0);
  await expect(page.getByTestId('chat-settings-share-link-unavailable')).toBeVisible();
});

// contract-test: supporting surface=gui.web assertions=settings-ui.composition.canonical-and-accessible
test('Chat Settings preview renders task and plan fixtures without API access', async ({ page }) => {
  const planningRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/v1\/(?:user-tasks|user-plans)(?:[/?]|$)/.test(request.url())) planningRequests.push(request.url());
  });

  await page.goto('/dev/preview/chats/ChatSettingsPreviewHarness?chrome=0&variant=tasks');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-settings-task-row')).toHaveCount(1);
  await expect(page.getByTestId('chat-settings-task-row')).toContainText('Review the release checklist');
  await expect(page.getByTestId('chat-settings-task-done-toggle')).not.toBeChecked();

  await page.goto('/dev/preview/chats/ChatSettingsPreviewHarness?chrome=0');
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-settings-plan-row')).toHaveCount(1);
  await expect(page.getByTestId('chat-settings-plan-row')).toContainText('Prepare the launch');
  expect(planningRequests).toEqual([]);
});
