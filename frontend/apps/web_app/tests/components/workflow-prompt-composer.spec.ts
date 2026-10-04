// playwright-account: not_required reason=isolated_component_preview
/* eslint-disable @typescript-eslint/no-require-imports -- Existing Playwright helpers expose CommonJS exports. */
export {};

import type { Page } from '@playwright/test';
import { waitForComponentPreview } from '../helpers/component-preview';

const { expect, test } = require('../helpers/cookie-audit');

test.use({
  launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] },
  permissions: ['microphone'],
});

const preview = (width: number, variant?: string, theme = 'light') =>
  `/dev/preview/workspace/WorkspacePromptComposer?${new URLSearchParams({
    theme, background: theme === 'dark' ? '#171717' : '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

const focusPreview = (variant: string) =>
  `/dev/preview/workspace/WorkspaceComposerFocusFixture?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: '900', chrome: '0', variant,
  })}`;

test.describe('Workflow prompt composer', () => {
  for (const [width, theme] of [[320, 'light'], [390, 'dark'], [1024, 'light']] as const) {
    // contract-test: direct surface=gui.web assertions=workflows-ui.responsive-accessible-reachable
    test(`edit placeholder stays on one line at ${width}px in ${theme} mode and entered instructions expand`, async ({ page }: { page: Page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(preview(width, 'workflowEdit', theme), { waitUntil: 'domcontentloaded' });
      await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
      const composer = page.getByTestId('workflows-input-composer');
      const input = page.getByTestId('workflows-input-textarea');
      const icon = composer.locator('.workspace-prompt-ai-icon');
      const mic = page.getByTestId('workflows-input-mic');
      await expect(composer).toBeVisible();
      await expect(input).toHaveAttribute('placeholder', 'Describe workflow change.');
      await page.evaluate(() => document.fonts.ready);
      const placeholderFit = await input.evaluate((element: HTMLTextAreaElement) => {
        const style = getComputedStyle(element, '::placeholder');
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d')!;
        context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
        const label = element.placeholder;
        const spacing = Number.parseFloat(style.letterSpacing) || 0;
        return { textWidth: context.measureText(label).width + Math.max(0, label.length - 1) * spacing, inputWidth: element.clientWidth };
      });
      expect(placeholderFit.textWidth).toBeLessThanOrEqual(placeholderFit.inputWidth);

      const emptyHeight = await input.evaluate((element: HTMLTextAreaElement) => element.scrollHeight);
      expect(emptyHeight).toBeLessThanOrEqual(30);
      const [iconBox, inputBox, micBox] = await Promise.all([icon.boundingBox(), input.boundingBox(), mic.boundingBox()]);
      if (!iconBox || !inputBox || !micBox) throw new Error('Composer controls must be measurable.');
      expect(iconBox.x + iconBox.width).toBeLessThanOrEqual(inputBox.x);
      expect(inputBox.x + inputBox.width).toBeLessThanOrEqual(micBox.x);
      await composer.screenshot({ path: test.info().outputPath(`workflow-change-empty-${width}-${theme}.png`) });
      await input.fill('Add a morning summary\nInclude earlier results');
      await expect(input).toHaveValue('Add a morning summary\nInclude earlier results');
      await expect.poll(() => input.evaluate((element: HTMLTextAreaElement) => element.getBoundingClientRect().height)).toBeGreaterThan(emptyHeight);
      await expect(page.getByTestId('workflows-input-submit')).toBeVisible();
      await composer.screenshot({ path: test.info().outputPath(`workflow-change-filled-${width}-${theme}.png`) });
    });
  }

  for (const [surface, variant] of [['workflows', 'workflowEdit'], ['tasks', 'tasks']] as const) {
    for (const [width, theme] of [[390, 'dark'], [1024, 'light']] as const) {
      // contract-test: supporting surface=gui.web assertions=workflows-ui.responsive-accessible-reachable,workspace-shell.start.chat-visual-parity
      test(`${surface} keeps multiline drafts when collapsed and expands from four scrollable lines at ${width}px`, async ({ page }: { page: Page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(preview(width, variant, theme), { waitUntil: 'domcontentloaded' });
        await expect(page.getByTestId('component-preview-canvas')).toHaveAttribute('data-preview-ready', 'true', { timeout: 30000 });
        const composer = page.getByTestId(`${surface}-input-composer`);
        const input = page.getByTestId(`${surface}-input-textarea`);
        const toggle = page.getByTestId(`${surface}-input-textarea-expand`);
        const collapsedPreview = page.getByTestId(`${surface}-input-textarea-preview`);
        const restingHeight = (await composer.boundingBox())!.height;
        await input.click();
        await expect.poll(async () => (await composer.boundingBox())!.height).toBeGreaterThan(restingHeight);
        await expect(toggle).toBeVisible();
        await expect(toggle.locator('.icon_fullscreen')).toBeVisible();
        const draft = 'A long first line that keeps the instructions available after collapsing this field\nSecond line\nThird line\nFourth line\nFifth line\nSixth line';
        await input.fill(draft);
        const geometry = await input.evaluate((element: HTMLTextAreaElement) => ({
          height: element.clientHeight,
          lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
          scrollHeight: element.scrollHeight,
          overflow: getComputedStyle(element).overflowY,
        }));
        expect(geometry.height).toBeLessThanOrEqual(geometry.lineHeight * 4 + 1);
        expect(geometry.height).toBeGreaterThan(geometry.lineHeight * 2);
        expect(geometry.scrollHeight).toBeGreaterThan(geometry.height);
        expect(geometry.overflow).toBe('auto');
        const [activeInput, activeComposer, activeSubmit] = await Promise.all([input.boundingBox(), composer.boundingBox(), page.getByTestId(`${surface}-input-submit`).boundingBox()]);
        if (!activeInput || !activeComposer || !activeSubmit) throw new Error('Active composer controls must be measurable.');
        // The expand control reserves 28px from the text row; keep at least 70% of the remaining field usable.
        expect(activeInput.width).toBeGreaterThan((activeComposer.width - 28) * .7);
        expect(activeInput.x + activeInput.width).toBeLessThanOrEqual(activeComposer.x + activeComposer.width);
        expect(activeInput.y + activeInput.height).toBeLessThan(activeSubmit.y);
        await input.evaluate((element: HTMLTextAreaElement) => { element.scrollTop = element.scrollHeight; });
        expect(await input.evaluate((element: HTMLTextAreaElement) => element.scrollTop)).toBeGreaterThan(0);
        await input.press('Escape');
        await expect(input).not.toBeFocused();
        await expect(input).toHaveValue(draft);
        await expect(collapsedPreview).toHaveText(`${draft.split('\n')[0]}…`);
        await expect(collapsedPreview).toHaveCSS('text-overflow', 'ellipsis');
        await expect(collapsedPreview).toHaveCSS('white-space', 'nowrap');
        await expect(toggle).toHaveCount(0);
        await expect.poll(async () => (await composer.boundingBox())!.height).toBe(restingHeight);
        await composer.screenshot({ path: test.info().outputPath(`${surface}-collapsed-${width}-${theme}.png`) });
        await input.click();
        await expect(input).toHaveValue(draft);
        await expect(collapsedPreview).toHaveCount(0);
        await toggle.click();
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await expect(toggle.locator('.icon_minimize')).toBeVisible();
        await expect(input).toBeFocused();
        await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(geometry.height * 2);
        const [toggleBox, submitBox] = await Promise.all([toggle.boundingBox(), page.getByTestId(`${surface}-input-submit`).boundingBox()]);
        if (!toggleBox || !submitBox) throw new Error('Expanded composer controls must be measurable.');
        expect(toggleBox.y + toggleBox.height).toBeLessThan(submitBox.y);
        await composer.screenshot({ path: test.info().outputPath(`${surface}-expanded-${width}-${theme}.png`) });
        await toggle.click();
        await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        await input.press('ControlOrMeta+End');
        await input.press('Shift+Enter');
        await input.press('x');
        await expect(input).toHaveValue(`${draft}\nx`);
        // Keyboard navigation stays within the active composer until focus leaves it.
        await input.press('Tab');
        await expect(toggle).toBeFocused();
        await toggle.press('Enter');
        await expect(input).toBeFocused();
        await expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await page.locator('body').click({ position: { x: 2, y: 2 } });
        await expect(collapsedPreview).toBeVisible();
        await expect(input).toHaveValue(`${draft}\nx`);
        await expect.poll(async () => (await composer.boundingBox())!.height).toBe(restingHeight);
        await input.click();
        await page.getByTestId(`${surface}-input-submit`).focus();
        await expect(collapsedPreview).toHaveCount(0);
        await expect(toggle).toBeVisible();
        await expect.poll(async () => (await composer.boundingBox())!.height).toBeGreaterThan(restingHeight);
        await expect(input).toHaveValue(`${draft}\nx`);
      });
    }
  }

  // contract-test: supporting surface=gui.web assertions=workflows-ui.files.composer-drop-import,workflows-ui.responsive-accessible-reachable
  test('file import replaces the AI icon, matches the microphone and fits phone and laptop inputs', async ({ page }: { page: Page }) => {
    for (const width of [390, 1280]) {
      for (const theme of ['light', 'dark']) {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(preview(width, undefined, theme), { waitUntil: 'networkidle' });
        const composer = page.getByTestId('workflows-input-composer');
        const input = page.getByTestId('workflows-input-textarea');
        const file = composer.getByRole('button', { name: 'Import .workflow.yml', exact: true });
        const mic = page.getByTestId('workflows-input-mic');
        await expect(input).toHaveAttribute('placeholder', 'Describe new workflow.');
        await expect(file).toBeVisible();
        await expect(mic).toBeVisible();
        await expect(composer.locator('.workspace-prompt-ai-icon')).toHaveCount(0);
        const icon = file.locator('.icon_files');
        const gradient = await icon.evaluate((element) => getComputedStyle(element).backgroundImage);
        expect(gradient).toContain('linear-gradient');
        await expect(mic).toHaveCSS('background-image', gradient);
        // Vite may inline the SVG into a data URL; the icon must still have a mask.
        expect(await icon.evaluate((element) => getComputedStyle(element).maskImage)).not.toBe('none');
        const [fileBox, inputBox, micBox] = await Promise.all([file.boundingBox(), input.boundingBox(), mic.boundingBox()]);
        if (!fileBox || !inputBox || !micBox) throw new Error('Composer controls must be measurable.');
        expect(fileBox.width).toBeGreaterThanOrEqual(36);
        expect(fileBox.width).toBeLessThanOrEqual(44);
        expect(fileBox.x).toBeGreaterThanOrEqual(0);
        expect(fileBox.x + fileBox.width).toBeLessThanOrEqual(inputBox.x + 1);
        expect(inputBox.x + inputBox.width).toBeLessThanOrEqual(micBox.x + 1);
        expect(micBox.x + micBox.width).toBeLessThanOrEqual(width);
        await file.focus();
        await expect(page.getByTestId('workflows-input-textarea-expand')).toHaveCount(0);
        expect((await input.boundingBox())!.height).toBeLessThanOrEqual(30);
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await expect(file).toBeFocused();
        await expect(file).toHaveCSS('outline-style', 'solid');
        await file.hover();
        await file.click();
        await input.fill('Every morning, send me the weather');
        await expect(file).toBeVisible();
        await expect(page.getByTestId('workflows-input-submit')).toBeVisible();
        const [filledFileBox, filledInputBox] = await Promise.all([file.boundingBox(), input.boundingBox()]);
        if (!filledFileBox || !filledInputBox) throw new Error('Filled composer controls must be measurable.');
        expect(filledFileBox.y).toBeGreaterThan(filledInputBox.y + filledInputBox.height);
      }
    }
    await page.goto(preview(390, 'disabled'), { waitUntil: 'networkidle' });
    await expect(page.getByTestId('workflow-import-button')).toBeDisabled();
    await page.goto(preview(390, 'projects'), { waitUntil: 'networkidle' });
    await expect(page.locator('.workspace-prompt-ai-icon')).toBeVisible();
    await expect(page.getByTestId('workflow-import-button')).toHaveCount(0);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.responsive-accessible-reachable,workspace-shell.nav.released-surfaces-visible
  test('Safari edge backgrounds follow theme changes without covering header controls', async ({ page }: { page: Page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.addInitScript(() => localStorage.setItem('theme_mode', 'dark'));
    for (const [width, theme] of [[390, 'dark'], [390, 'light'], [1280, 'light'], [1280, 'dark']] as const) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(`/dev/preview/Header?${new URLSearchParams({
        theme, background: theme === 'dark' ? '#171717' : '#dbeafe',
        width: String(width), variant: 'signedIn', chrome: '0',
      })}`, { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const rgb = theme === 'dark' ? 'rgb(23, 23, 23)' : 'rgb(255, 255, 255)';
      const hex = theme === 'dark' ? '#171717' : '#ffffff';
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.locator('html')).toHaveCSS('background-color', rgb);
      await expect(page.locator('body')).toHaveCSS('background-color', rgb);
      await expect(page.locator('html')).toHaveCSS('color-scheme', theme);
      await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', hex);
      for (const edge of ['top', 'bottom']) {
        const sampler = page.locator(`.safari-browser-tint-sampler.${edge}`);
        await expect(sampler).toHaveCSS('background-color', rgb);
        await expect(sampler).toHaveCSS('position', 'fixed');
        await expect(sampler).toHaveCSS('pointer-events', 'none');
        const box = await sampler.boundingBox();
        if (!box) throw new Error('Safari edge background must be measurable.');
        expect(box.height).toBeGreaterThan(10);
        expect(box.width).toBeGreaterThanOrEqual(width);
        if (edge === 'top') {
          // The full box still qualifies for Safari detection; only 1px is visible.
          expect(box.y).toBeLessThan(0);
          expect(box.y + box.height).toBe(1);
        } else {
          expect(box.y + box.height).toBe(844);
        }
      }
      const controls = width === 390
        ? page.getByTestId('workspace-mobile-select')
        : page.locator('.webapp-center-tabs .icon-tab');
      await expect(controls).toHaveCount(width === 390 ? 1 : 5);
      for (const control of await controls.all()) {
        await expect(control).toBeVisible();
        const box = await control.boundingBox();
        if (!box) throw new Error('Header controls must be measurable.');
        expect(box.y, 'The tint strip must stay above the entire header control').toBeGreaterThanOrEqual(1);
        await control.focus();
        await expect(control).toBeFocused();
      }
      await page.locator('header').screenshot({ path: test.info().outputPath(`safari-header-${width}-${theme}.png`) });
    }
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('.safari-browser-tint-sampler.top')).toHaveCSS('background-color', 'rgb(23, 23, 23)');
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
  for (const [variant, surface, backdropId] of [
    ['default', 'tasks', 'tasks-composer-backdrop'],
    ['workflows', 'workflows', 'workflows-composer-backdrop'],
    ['editor', 'workflows', 'fixture-editor-backdrop'],
  ] as const) {
    test(`${variant} focus dims controls and preserves the multiline draft on outside click`, async ({ page }: { page: Page }) => {
      await page.goto(focusPreview(variant), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const input = page.getByTestId(`${surface}-input-textarea`);
      await input.focus();
      const background = variant === 'editor' ? page.getByTestId('fixture-editor-graph') : page.locator('.workspace-scroll-layer');
      await expect(page.getByTestId(backdropId)).toBeVisible();
      await expect(background).toHaveAttribute('inert', '');
      await input.fill('First\nSecond\nThird\nFourth\nFifth');
      await expect.poll(() => input.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(70);
      const regularHeight = await input.evaluate((element) => element.getBoundingClientRect().height);
      await page.getByTestId(`${surface}-input-textarea-expand`).click();
      await expect.poll(() => input.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(regularHeight + 30);
      await expect(page.getByTestId(`${surface}-input-mic`)).toBeVisible();
      await page.getByTestId(backdropId).click({ position: { x: 8, y: 8 } });
      await expect(page.getByTestId(backdropId)).toHaveCount(0);
      await expect(background).not.toHaveAttribute('inert', '');
      await expect(input).toHaveValue('First\nSecond\nThird\nFourth\nFifth');
      await expect(input).not.toBeFocused();
      await page.getByTestId('fixture-card').click();
      await expect(page.getByTestId('fixture-card-clicks')).toHaveText('1');
    });
  }

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
  test('Cancel keeps the draft and microphone works with text', async ({ page }: { page: Page }) => {
    await page.goto(focusPreview('workflows'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const input = page.getByTestId('workflows-input-textarea');
    await input.fill('Keep\nthis draft');
    await page.getByTestId('workflows-input-mic').click();
    await expect(page.getByTestId('fixture-mic-clicks')).toHaveText('1');
    await expect.poll(() => page.evaluate(() => {
      const field = document.querySelector('[data-testid="workflows-input-composer"]');
      const cancel = document.querySelector('[data-testid="workflows-input-textarea-cancel"]');
      if (!field || !cancel) throw new Error('Cancel and message field must be measurable.');
      return cancel.getBoundingClientRect().top - field.getBoundingClientRect().bottom;
    })).toBeGreaterThanOrEqual(0);
    await page.getByTestId('workflows-input-textarea-cancel').click();
    await expect(page.getByTestId('workflows-composer-backdrop')).toHaveCount(0);
    await expect(input).toHaveValue('Keep\nthis draft');
  });

  // contract-test: supporting surface=gui.web assertions=workspace-shell.start.chat-visual-parity
  test('programmatic inspiration prefill focuses and expands the task editor', async ({ page }: { page: Page }) => {
    await page.goto(focusPreview('default'), { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    await page.getByTestId('fixture-prefill').click();
    const input = page.getByTestId('tasks-input-textarea');
    await expect(input).toHaveValue('An inspired task');
    await expect(input).toBeFocused();
    await expect(page.getByTestId('tasks-input-textarea-expand')).toBeVisible();
    await expect(page.getByTestId('tasks-composer-backdrop')).toBeVisible();
  });

  // contract-test: supporting surface=gui.web assertions=workspace-shell.start.chat-visual-parity
  test('compact project task editor dims and disables its board and search', async ({ page }: { page: Page }) => {
    await page.goto(`/dev/preview/tasks/TasksPage?${new URLSearchParams({ theme: 'light', width: '900', chrome: '0', variant: 'project' })}`, { waitUntil: 'domcontentloaded' });
    await waitForComponentPreview(page);
    const input = page.getByTestId('project-task-workspace-input');
    await input.fill('Keep\na project draft');
    const background = page.getByTestId('project-task-background');
    await expect(background).toHaveAttribute('inert', '');
    await expect(background).toHaveClass(/dimmed/);
    await expect(page.getByTestId('project-task-composer-backdrop')).toBeVisible();
    await page.getByTestId('project-task-composer-backdrop').click({ position: { x: 8, y: 8 } });
    await expect(background).not.toHaveAttribute('inert', '');
    await expect(input).toHaveValue('Keep\na project draft');
    await expect(input).not.toBeFocused();
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
  for (const variant of ['declined', 'rejected', 'default'] as const) {
    test(`${variant} submit only collapses after success`, async ({ page }: { page: Page }) => {
      await page.goto(focusPreview(variant), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const input = page.getByTestId('tasks-input-textarea');
      await input.fill('Create a task');
      await page.getByTestId('tasks-input-submit').click();
      await expect(page.getByTestId('fixture-sends')).toHaveText('1');
      if (variant === 'default') {
        await expect(page.getByTestId('tasks-composer-backdrop')).toHaveCount(0);
        await expect(input).toHaveValue('');
      } else {
        await expect(page.getByTestId('tasks-composer-backdrop')).toBeVisible();
        await expect(input).toHaveValue('Create a task');
        await expect(input).toBeFocused();
      }
    });
  }

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring
  for (const [variant, accepted] of [['pendingSuccess', true], ['pendingFailure', false]] as const) {
    test(`${variant} retains a focused read-only draft until the send settles`, async ({ page }: { page: Page }) => {
      await page.goto(focusPreview(variant), { waitUntil: 'domcontentloaded' });
      await waitForComponentPreview(page);
      const input = page.getByTestId('tasks-input-textarea');
      const draft = 'Create a task\nwith details';
      await input.fill(draft);
      await page.getByTestId('tasks-input-submit').click();
      await expect(page.getByTestId('fixture-settle')).toBeVisible();
      await expect(input).toHaveAttribute('readonly', '');
      await expect(input).toBeFocused();
      await expect(page.getByTestId('tasks-composer-backdrop')).toBeVisible();
      await expect(page.getByTestId('tasks-input-textarea-expand')).toBeVisible();
      await expect(page.getByTestId('tasks-input-submit')).toBeDisabled();
      await expect(page.getByTestId('tasks-input-mic')).toBeDisabled();
      await expect(input).toHaveValue(draft);
      await page.getByTestId('fixture-settle').click();
      if (accepted) {
        await expect(page.getByTestId('tasks-composer-backdrop')).toHaveCount(0);
        await expect(input).toHaveValue('');
      } else {
        await expect(input).not.toHaveAttribute('readonly', '');
        await expect(input).toHaveValue(draft);
        await expect(input).toBeFocused();
        await expect(page.getByTestId('tasks-composer-backdrop')).toBeVisible();
      }
    });
  }

  // contract-test: direct surface=gui.web assertions=workflows-ui.mvp.authoring,workflows-ui.responsive-accessible-reachable
  test('fits the shared recording overlay inside the phone composer', async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(preview(390, 'recording'), { waitUntil: 'networkidle' });
    const composer = page.getByTestId('workflows-input-composer');
    const recorder = page.getByTestId('record-overlay');
    await expect(composer).toBeVisible();
    await expect(recorder).toBeVisible();
    await expect(page.getByTestId('record-finish-button')).toBeVisible();
    await expect(page.getByTestId('record-cancel-button')).toBeVisible();
    const composerBox = await composer.boundingBox();
    const recorderBox = await recorder.boundingBox();
    if (!composerBox || !recorderBox) throw new Error('Recording layout must be measurable.');
    expect(composerBox.height).toBeGreaterThanOrEqual(220);
    expect(recorderBox.y).toBeGreaterThanOrEqual(composerBox.y - 1);
    expect(recorderBox.y + recorderBox.height).toBeLessThanOrEqual(composerBox.y + composerBox.height + 1);
    expect(recorderBox.x).toBeGreaterThanOrEqual(0);
    expect(recorderBox.x + recorderBox.width).toBeLessThanOrEqual(391);
  });
});
