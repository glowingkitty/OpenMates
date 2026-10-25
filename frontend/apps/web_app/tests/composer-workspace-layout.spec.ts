// playwright-account: required reason=actual_tasks_and_workflows_routes
/* eslint-disable @typescript-eslint/no-require-imports -- Existing browser helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';

const { expect, test } = require('./helpers/cookie-audit');
const { loginToTestAccount, startNewChat } = require('./helpers/chat-test-helpers');
const { skipIfFeaturesDisabled } = require('./helpers/env-guard');
const { getE2EDebugUrl, getTestAccount } = require('./signup-flow-helpers');

function apiUrl(): string {
  const url = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL || 'https://app.dev.openmates.org');
  return url.hostname === 'localhost'
    ? 'http://localhost:8000'
    : `${url.protocol}//${url.hostname.replace(/^app\./, 'api.')}`;
}

async function expectBalancedPanelGutters(page: Page, surface: 'chat' | 'tasks' | 'workflows' | 'editor') {
  const panelSelector = surface === 'chat' ? '.chat-container > .chat-wrapper'
    : surface === 'tasks' ? '.tasks-wrapper' : '[data-testid="workflows-page"]';
  const parentSelector = surface === 'chat' ? '.chat-container'
    : surface === 'tasks' ? '.tasks-container' : '.workflows-container';
  const panel = page.locator(panelSelector);
  const parent = page.locator(parentSelector);
  const geometry = await page.evaluate(({ panelSelector, parentSelector }) => {
    const panel = document.querySelector(panelSelector);
    const parent = document.querySelector(parentSelector);
    if (!panel || !parent) throw new Error('Workspace panel and container must exist.');
    const panelBox = panel.getBoundingClientRect();
    const parentBox = parent.getBoundingClientRect();
    const style = getComputedStyle(parent);
    return {
      left: panelBox.left - parentBox.left,
      right: parentBox.right - panelBox.right,
      bottom: parentBox.bottom - panelBox.bottom,
      paddingLeft: Number.parseFloat(style.paddingLeft),
      paddingRight: Number.parseFloat(style.paddingRight),
      paddingBottom: Number.parseFloat(style.paddingBottom),
      viewportBottom: window.innerHeight - parentBox.bottom,
    };
  }, { panelSelector, parentSelector });
  await expect(panel).toBeVisible();
  await expect(parent).toBeVisible();
  // Desktop chat has extra inline-end padding; compare physical bounds so
  // the same check also follows that spacing in RTL layouts.
  expect(Math.abs(geometry.left - geometry.paddingLeft)).toBeLessThanOrEqual(1);
  expect(Math.abs(geometry.right - geometry.paddingRight)).toBeLessThanOrEqual(1);
  expect(geometry.bottom).toBeLessThanOrEqual(Math.max(geometry.left, geometry.right) + 1);
  expect(Math.abs(geometry.bottom - geometry.paddingBottom)).toBeLessThanOrEqual(1);
  expect(Math.abs(geometry.viewportBottom)).toBeLessThanOrEqual(1);
}

async function checkFocusedLayout(page: Page, surface: 'tasks' | 'workflows' | 'editor', height: number) {
  const ids = surface === 'tasks'
    ? { input: 'task-workspace-input', form: 'task-workspace-composer', backdrop: 'tasks-composer-backdrop' }
    : surface === 'workflows'
      ? { input: 'workflow-input-textarea', form: 'workflow-input-composer', backdrop: 'workflows-composer-backdrop' }
      : { input: 'workflow-ai-edit-textarea', form: 'workflow-ai-edit-composer', backdrop: 'workflow-editor-composer-backdrop' };
  const background = surface === 'editor'
    ? page.locator('.workflow-management .management-grid')
    : page.locator(`.workspace-home-shell[data-surface="${surface}"] .workspace-scroll-layer`);
  const input = page.getByTestId(ids.input);
  const form = page.getByTestId(ids.form);
  const cancel = page.getByTestId(`${ids.input}-cancel`);
  const draft = `Unsent ${surface} layout draft\nKeep this second line`;

  await expect(input).toBeVisible({ timeout: 30000 });
  await expectBalancedPanelGutters(page, surface);
  await expect(cancel).toHaveCSS('visibility', 'hidden');
  await expect.poll(() => cancel.evaluate((element: HTMLElement) => element.getBoundingClientRect().height)).toBe(0);
  await input.fill(draft);
  await expect(input).toBeFocused();
  await expect(page.getByTestId(ids.backdrop)).toHaveCount(0);
  await expect(background).toHaveAttribute('inert', '');
  await expect(background).toHaveCSS('opacity', '1');
  await expect(background).toHaveCSS('visibility', 'visible');
  if (surface === 'editor') {
    await expect(page.getByTestId('workflow-graph-renderer')).toBeVisible();
  } else {
    await expect(page.getByTestId(`${surface}-daily-inspiration-area`)).toBeVisible();
    if (surface === 'tasks') await expect(page.getByTestId('tasks-board-workspace')).toBeVisible();
  }
  await expect(cancel).toBeVisible();

  const [formBox, cancelBox] = await Promise.all([form.boundingBox(), cancel.boundingBox()]);
  if (!formBox || !cancelBox) throw new Error(`${surface}: focused composer geometry unavailable`);
  expect(Math.abs(cancelBox.x - formBox.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(cancelBox.width - formBox.width)).toBeLessThanOrEqual(1);
  expect(cancelBox.y).toBeGreaterThanOrEqual(formBox.y + formBox.height);
  expect(cancelBox.y + cancelBox.height).toBeLessThanOrEqual(height + 1);
  expect(Number.parseFloat(await cancel.evaluate((element: HTMLElement) => getComputedStyle(element).borderTopWidth))).toBeGreaterThan(0);
  expect(Number.parseFloat(await cancel.evaluate((element: HTMLElement) => getComputedStyle(element).borderTopLeftRadius))).toBeGreaterThanOrEqual(20);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: test.info().outputPath(`${surface}-focused-390x${height}.png`), fullPage: true });

  await page.locator(surface === 'editor' ? '.workflow-management' : `.workspace-home-shell[data-surface="${surface}"]`).click({ position: { x: 8, y: 8 } });
  await expect(page.getByTestId(ids.backdrop)).toHaveCount(0);
  await expect(background).not.toHaveAttribute('inert', '');
  await expect(background).toHaveCSS('opacity', '1');
  await expect(background).toHaveCSS('visibility', 'visible');
  if (surface === 'editor') {
    await expect(page.getByTestId('workflow-graph-renderer')).toBeVisible();
  } else {
    await expect(page.getByTestId(`${surface}-daily-inspiration-area`)).toBeVisible();
    if (surface === 'tasks') await expect(page.getByTestId('tasks-board-workspace')).toBeVisible();
  }
  await expect(input).toHaveValue(draft);
  await expect(input).not.toBeFocused();
  await expect(cancel).toHaveCSS('visibility', 'hidden');
  await expect.poll(() => cancel.evaluate((element: HTMLElement) => element.getBoundingClientRect().height)).toBe(0);
  await expectBalancedPanelGutters(page, surface);
  await page.screenshot({ path: test.info().outputPath(`${surface}-restored-390x${height}.png`), fullPage: true });
}

test.describe('Actual workspace composer layout', () => {
  for (const { height, theme, color } of [
    { height: 800, theme: 'light', color: 'rgb(230, 234, 255)' },
    { height: 400, theme: 'dark', color: 'rgb(45, 47, 53)' },
  ]) {
    // contract-test: direct surface=gui.web assertions=message-input.focus.guest-welcome-suppression,message-input.focus.workspace-suppression,message-input.layout.responsive-parity,message-input.suggestions.contextual
    test(`guest new chat restores its welcome and preserves a draft at 1280x${height}`, async ({ page }: { page: Page }) => {
      await page.setViewportSize({ width: 1280, height });
      await page.addInitScript((theme) => localStorage.setItem('theme_mode', theme), theme);
      await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
      const field = page.getByTestId('message-field');
      const editor = page.getByTestId('message-editor').locator('.ProseMirror');
      const welcome = page.getByTestId('daily-inspiration-area');
      const chat = page.getByTestId('active-chat-container');
      const suggestions = page.getByTestId('chat-welcome-suggestions');
      const firstSuggestion = page.getByTestId('new-chat-suggestion-card').first();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(welcome).toBeVisible({ timeout: 30000 });
      await expect(field).toHaveCSS('background-color', color);
      const welcomeHeight = await welcome.evaluate((element) => element.getBoundingClientRect().height);
      await field.click();
      await expect(field).toHaveAttribute('data-focused', 'true');
      await expect(field).toHaveCSS('background-color', color);
      await expect(welcome).toBeHidden();
      await expect(welcome).toHaveAttribute('inert', '');
      await expect(page.getByTestId('welcome-content')).toBeHidden();
      await expect(suggestions).toBeVisible();
      await expect(suggestions).not.toHaveAttribute('inert', '');
      await expect(suggestions.getByTestId('suggestions-wrapper')).toHaveCSS('opacity', '1');
      await expect(firstSuggestion).toBeVisible();
      await expect(firstSuggestion).toBeEnabled();
      await expect.poll(() => welcome.evaluate((element) => element.getBoundingClientRect().height)).toBe(welcomeHeight);
      await expect(field).toBeInViewport({ ratio: 1 });
      const cancel = page.getByTestId('input-dismiss-button');
      await expect(cancel).toBeInViewport({ ratio: 1 });
      await cancel.click();
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(welcome).toBeVisible();
      await expect(welcome).not.toHaveAttribute('inert', '');
      await expect(suggestions).toBeHidden();
      await field.click();
      await expect(welcome).toBeHidden();
      // Use a real outside pointer event, including when the empty chat-side has no height.
      await page.mouse.click(5, 5);
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(welcome).toBeVisible();
      await expect(editor).not.toBeFocused();

      // Guest drafts stay in session storage without selecting an authenticated
      // saved-chat shell. Both dismissal paths restore this welcome surface.
      await field.click();
      const suggestionText = await firstSuggestion.locator('.card-text').innerText();
      await firstSuggestion.click();
      await expect(editor).toContainText(suggestionText);
      await expect(editor).toBeFocused();
      await expect(chat).toHaveAttribute('data-current-chat-id', '');
      await expect(page.getByTestId('message-user')).toHaveCount(0);
      await editor.fill('');
      await editor.pressSequentially('Keep this new-chat draft');
      await editor.press('Shift+Enter');
      await editor.pressSequentially('Keep its second line');
      await expect(editor).toContainText('Keep its second line');
      await cancel.click();
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(chat).toHaveAttribute('data-current-chat-id', '');
      await expect(welcome).toBeVisible();
      await expect(welcome).not.toHaveAttribute('inert', '');
      await expect(editor).toContainText('Keep this new-chat draft');
      await expect(editor).toContainText('Keep its second line');
      await field.click();
      await expect(welcome).toBeHidden();
      await expect(field).toHaveCSS('background-color', color);
      await page.mouse.click(5, 5);
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(editor).not.toBeFocused();
      await expect(chat).toHaveAttribute('data-current-chat-id', '');
      await expect(welcome).toBeVisible();
      await expect(welcome).not.toHaveAttribute('inert', '');
      await expect(editor).toContainText('Keep this new-chat draft');
      await expect(editor).toContainText('Keep its second line');
    });
  }

  // contract-test: direct surface=gui.web assertions=message-input.actions.visibility,public-example-chats.transcript.safe-rendering,workspace-shell.start.chat-visual-parity,message-input.suggestions.contextual
  test('empty chat hides welcome on focus while a public example keeps its transcript fully visible', async ({ page }: { page: Page }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await page.addInitScript(() => localStorage.setItem('theme_mode', 'dark'));
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});

    for (const { width, height } of [{ width: 390, height: 844 }, { width: 390, height: 400 }, { width: 1280, height: 800 }]) {
      await page.setViewportSize({ width, height });
      await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
      const chat = page.getByTestId('active-chat-container');
      const background = page.getByTestId('chat-side');
      const field = page.getByTestId('message-field');
      await expect(field).toBeVisible({ timeout: 30000 });
      await startNewChat(page);
      await expect(chat).toHaveAttribute('data-current-chat-id', '', { timeout: 30000 });
      await expectBalancedPanelGutters(page, 'chat');
      await field.click();
      await expect(field).toHaveAttribute('data-focused', 'true');
      await expect(background).toHaveAttribute('inert', '');
      await expect(background).toHaveCSS('opacity', '1');
      await expect(background).toHaveCSS('visibility', 'visible');
      await expect(page.getByTestId('daily-inspiration-banner')).toBeHidden();
      await expect(page.getByTestId('welcome-content')).toBeHidden();
      await expect(field).toHaveCSS('background-color', 'rgb(45, 47, 53)');
      await expect(page.getByTestId('chat-welcome-suggestions')).toBeVisible();
      await expect(page.getByTestId('chat-welcome-suggestions')).not.toHaveAttribute('inert', '');
      await expect(page.getByTestId('chat-welcome-suggestions').getByTestId('suggestions-wrapper')).toHaveCSS('opacity', '1');
      await expect(page.getByTestId('new-chat-suggestion-card').first()).toBeVisible();
      await page.screenshot({ path: test.info().outputPath(`chat-welcome-focused-${width}x${height}.png`), fullPage: true });
      // Outside touch dismisses through the document capture listener, even
      // when Safari does not synthesize a subsequent click.
      await page.getByTestId('chat-side').dispatchEvent('pointerdown', { pointerType: 'touch', button: 0 });
      await expect(field).toHaveAttribute('data-focused', 'false');
      await expect(background).not.toHaveAttribute('inert', '');
      await expect(page.getByTestId('daily-inspiration-banner')).toBeVisible();
      await expect(background).toHaveCSS('opacity', '1');
      await expect(background).toHaveCSS('visibility', 'visible');
      await expectBalancedPanelGutters(page, 'chat');

      await page.goto(getE2EDebugUrl('/#chat-id=example-gigantic-airplanes'), { waitUntil: 'domcontentloaded' });
      const transcript = page.getByTestId('user-message-content').filter({ hasText: 'Help me find a name for my new product.' });
      await expect(chat).toHaveAttribute('data-current-chat-id', 'example-gigantic-airplanes');
      // ReadOnlyMessage mounts its editor lazily. At the shorter viewport the
      // header can occupy the scroll area, so bring the known message into view.
      await page.locator('[data-testid="message-user"][data-message-id="dfd8a5dc-b685-4854-8dbf-4b00c71d93cc"]').scrollIntoViewIfNeeded();
      await expect(transcript).toBeVisible({ timeout: 30000 });
      await expectBalancedPanelGutters(page, 'chat');
      await field.click();
      await expect(field).toHaveAttribute('data-focused', 'true');
      await expect(background).toHaveAttribute('inert', '');
      await expect(background).toHaveCSS('opacity', '1');
      await expect(background).toHaveCSS('visibility', 'visible');
      await expect(transcript).toBeVisible();
      await page.screenshot({ path: test.info().outputPath(`chat-example-focused-${width}x${height}.png`), fullPage: true });
      await page.getByTestId('chat-side').dispatchEvent('pointerdown', { pointerType: 'touch', button: 0 });
      await expect(background).not.toHaveAttribute('inert', '');
      await expect(background).toHaveCSS('opacity', '1');
      await expect(background).toHaveCSS('visibility', 'visible');
      await expect(transcript).toBeVisible();
      await expectBalancedPanelGutters(page, 'chat');
      await page.screenshot({ path: test.info().outputPath(`chat-example-restored-${width}x${height}.png`), fullPage: true });
    }
  });

  // contract-test: direct surface=gui.web assertions=workspace-shell.start.chat-visual-parity,workflows-ui.responsive-accessible-reachable
  test('Tasks and Workflows focus hides workspace content, then restores it without losing drafts', async ({ page }: { page: Page }) => {
    test.setTimeout(180000);
    test.skip(!getTestAccount().email, 'Test account credentials required.');
    await skipIfFeaturesDisabled(test, page, ['platform:tasks', 'platform:workflows']);
    await page.addInitScript(() => localStorage.setItem('theme_mode', 'dark'));
    await page.goto(getE2EDebugUrl('/'), { waitUntil: 'domcontentloaded' });
    await loginToTestAccount(page, () => {}, async () => {});

    let workflowId = '';
    try {
      for (const height of [844, 400]) {
        await page.setViewportSize({ width: 390, height });
        await page.goto(getE2EDebugUrl('/tasks'), { waitUntil: 'domcontentloaded' });
        await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
        await expect(page.getByTestId('tasks-page')).toBeVisible({ timeout: 30000 });
        await checkFocusedLayout(page, 'tasks', height);

        await page.goto(getE2EDebugUrl('/workflows'), { waitUntil: 'domcontentloaded' });
        await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
        await expect(page.getByTestId('workflows-page')).toBeVisible({ timeout: 30000 });
        await checkFocusedLayout(page, 'workflows', height);

        if (!workflowId) {
          const response = await page.request.post(`${apiUrl()}/v1/workflows`, { data: {
            title: `Composer layout ${Date.now()}`,
            graph: { version: 2, trigger_node_id: 'manual', nodes: [{ id: 'manual', type: 'manual_trigger', title: 'Manual start', config: {} }], edges: [] },
            enabled: false,
          } });
          expect(response.ok(), await response.text()).toBe(true);
          workflowId = (await response.json()).workflow.id;
        }
        await page.goto(getE2EDebugUrl(`/#workflow-id=${encodeURIComponent(workflowId)}&workflow-tab=details`), { waitUntil: 'domcontentloaded' });
        await expect(page.getByTestId('workflow-graph-renderer')).toBeVisible({ timeout: 30000 });
        await checkFocusedLayout(page, 'editor', height);
      }
    } finally {
      if (workflowId) await page.request.delete(`${apiUrl()}/v1/workflows/${encodeURIComponent(workflowId)}`).catch(() => null);
    }
  });
});
