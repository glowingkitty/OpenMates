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

// contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,public-example-chats.navigation.static-public-link
test('anonymous settings block Share deep links while public examples keep static links', async ({ page }) => {
  const shareRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/v1\/(?:share|short-url)/.test(request.url())) shareRequests.push(request.url());
  });
  await page.setViewportSize({ width: 390, height: 844 });
  const preview = '/dev/preview/chats/ChatSettingsPreviewHarness?theme=light&background=%23dbeafe&width=390&chrome=0';
  await page.goto(`${preview}&variant=anonymous`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-settings-title')).toHaveText('Launch preparation');
  await expect(page.getByTestId('chat-settings-tab-share')).toHaveCount(0);
  await expect(page.getByTestId('chat-settings-tabpanel-share')).toHaveCount(0);
  await expect(page.getByTestId('chat-settings-tabpanel-plan')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('anonymous-share-blocked.png') });

  await page.goto(`${preview}&variant=public`);
  await waitForComponentPreview(page);
  await expect(page.getByTestId('chat-settings-tab-share')).toBeVisible();
  await expect(page.getByTestId('share-copy-link')).toBeVisible();
  await expect(page.getByTestId('share-generate-link')).toHaveCount(0);
  await page.getByTestId('chat-settings-share-show-url').click();
  await expect(page.getByTestId('chat-settings-share-url')).toContainText('/#chat-id=example-gigantic-airplanes');
  await page.getByTestId('chat-settings-share-show-qr').click();
  await expect(page.getByTestId('chat-settings-share-qr')).toBeFocused();
  await expect(page.getByTestId('chat-settings-share-qr').getByRole('img')).toBeVisible();
  expect(shareRequests).toEqual([]);
  await page.screenshot({ path: test.info().outputPath('public-example-share-preserved.png') });
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

// contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content
test('anonymous chat context menu keeps local actions and hides Share', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dev/preview/chats/ChatContextMenu?theme=light&background=%23dbeafe&width=390&chrome=0');
  await waitForComponentPreview(page);
  const menu = page.getByTestId('context-menu');
  await expect(menu).toBeVisible();
  await expect(menu).toContainText('This conversation stays in the current tab.');
  await expect(page.getByTestId('chat-context-share')).toHaveCount(0);
  const copy = menu.locator('button.copy');
  await expect(copy).toBeVisible();
  await copy.focus();
  await expect(copy).toBeFocused();
  const bounds = await menu.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath('anonymous-context-share-hidden.png') });
});
