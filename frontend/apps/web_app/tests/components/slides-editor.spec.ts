// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
//
// Manual slides editor against the real Rust core: the deck replica, every
// operation and undo/redo run in the shared Worker's wasm (deckDocument unit).
// Run in component mode with the web Rust core on:
//   ci_coordinator.py submit --mode component --web-rust-core --spec components/slides-editor.spec.ts
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Page, TestInfo } from '@playwright/test';
import { test, expect } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const EDITOR_PREVIEW = '/dev/preview/embeds/slides/SlidesEditor';
const FULLSCREEN_PREVIEW = '/dev/preview/embeds/slides/SlidesDeckEmbedFullscreen';
const CANVAS_WIDTH = 1920;

const url = (path: string, variant = '', extra: Record<string, string> = {}) =>
  `${path}?${new URLSearchParams({ variant, chrome: '0', ...extra })}`;
/** Local runs may also write the screenshots as files (CI keeps the attachments). */
const SHOTS_DIR = process.env.SLIDES_EDITOR_SHOTS_DIR ?? '';

const editor = (page: Page) => page.getByTestId('slides-editor');
const hit = (page: Page, id: string) => page.locator(`[data-testid="slides-editor-element"][data-element-id="${id}"]`);
const rendered = (page: Page, id: string) =>
  page.getByTestId('slides-editor-canvas').getByTestId('slide-canvas').locator(`[data-element-id="${id}"]`);
const strip = (page: Page) => page.getByTestId('slides-editor-strip-item');

async function waitForEditor(page: Page) {
  // The first open pays the wasm load of the shared Worker.
  await expect(editor(page), 'the Rust core should open the deck').toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
}

async function openEditor(page: Page, variant = '', size = { width: 1280, height: 900 }, extra: Record<string, string> = {}) {
  await page.setViewportSize(size);
  await page.goto(url(EDITOR_PREVIEW, variant, extra));
  await waitForComponentPreview(page);
  await waitForEditor(page);
}

async function geometry(page: Page, id: string) {
  const box = hit(page, id);
  const read = async (name: string) => Number(await box.getAttribute(`data-${name}`));
  return { x: await read('x'), y: await read('y'), w: await read('w'), h: await read('h') };
}

/** Canvas units per screen pixel of the editable slide (1 means no zoom). */
async function unitsPerPixel(page: Page) {
  const stage = await page.getByTestId('slides-editor-canvas').boundingBox();
  expect(stage).not.toBeNull();
  return CANVAS_WIDTH / stage!.width;
}

async function center(page: Page, locator: ReturnType<Page['locator']>) {
  const box = await locator.boundingBox();
  expect(box).not.toBeNull();
  return { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 };
}

async function drag(page: Page, from: { x: number; y: number }, dx: number, dy: number) {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + dx / 2, from.y + dy / 2, { steps: 4 });
  await page.mouse.move(from.x + dx, from.y + dy, { steps: 4 });
  await page.mouse.up();
}

async function stripOrder(page: Page) {
  return strip(page).evaluateAll((items) => items.map((item) => item.getAttribute('data-slide-id')));
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot();
  await testInfo.attach(name, { body, contentType: 'image/png' });
  if (SHOTS_DIR) {
    mkdirSync(SHOTS_DIR, { recursive: true });
    writeFileSync(join(SHOTS_DIR, `${name}.png`), body);
  }
}

/** Hovers a control and waits for the shared tooltip (1 s delay) to name it. */
async function expectTooltip(page: Page, testId: string, label: string | RegExp) {
  const control = page.getByTestId(testId);
  await expect(control).toHaveAttribute('aria-label', label);
  await page.mouse.move(0, 0);
  await control.hover();
  await expect(page.getByRole('tooltip')).toHaveText(label, { timeout: 5_000 });
}

/** Opens the open slide's action row (duplicate, move, delete) from the strip. */
async function openSlideActions(page: Page) {
  const menu = page.getByTestId('slides-editor-slide-actions-menu');
  if (!(await menu.isVisible())) await page.getByTestId('slides-editor-slide-actions').click();
  await expect(menu).toBeVisible();
}

/** Every round icon button of the editor: a circle, not the global 112px button. */
async function iconButtonShapes(page: Page) {
  return editor(page)
    .locator('.embed-icon-button')
    .evaluateAll((buttons) =>
      buttons.map((button) => {
        const style = getComputedStyle(button);
        const rect = button.getBoundingClientRect();
        return {
          id: button.getAttribute('data-testid') ?? '',
          name: button.getAttribute('aria-label') ?? '',
          width: rect.width,
          height: rect.height,
          radius: parseFloat(style.borderTopLeftRadius)
        };
      })
    );
}

test.describe('Slides editor (Rust core)', () => {
  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('Edit opens the editor; Done without changes closes it, a failed save keeps the edits with a retry', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(url(FULLSCREEN_PREVIEW, 'editable'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('slide-strip-item')).toHaveCount(3);

    // Nothing changed: Done writes no version and closes at once.
    await page.getByTestId('slides-edit').click();
    await waitForEditor(page);
    await expect(editor(page)).toHaveAttribute('data-dirty', 'false');
    await page.getByTestId('slides-editor-done').click();
    await expect(editor(page)).toHaveCount(0);

    await page.getByTestId('slides-edit').click();
    await waitForEditor(page);
    await expect(page.getByTestId('slides-deck-fullscreen').getByTestId('slides-editor')).toBeVisible();
    await hit(page, 'e1').dblclick();
    const input = page.getByTestId('slides-editor-text-input');
    await expect(input).toBeFocused();
    await page.keyboard.press('ControlOrMeta+a');
    await page.keyboard.type('Annual review');
    await page.keyboard.press('Escape');
    await expect(rendered(page, 'e1')).toHaveText('Annual review');
    await page.getByTestId('slides-editor-add-slide').click();
    await expect(strip(page)).toHaveCount(4);
    await expect(editor(page)).toHaveAttribute('data-dirty', 'true');

    // The preview embed is not in the local embed store: saving must fail visibly,
    // keep the editor open with the edits, and allow a retry (no silent fallback).
    await page.getByTestId('slides-editor-done').click();
    await expect(editor(page)).toHaveAttribute('data-save-state', 'failed');
    await expect(page.getByTestId('slides-editor-save-failed')).toBeVisible();
    await expect(strip(page)).toHaveCount(4);
    await expect(editor(page)).toHaveAttribute('data-dirty', 'true');
    await expect(page.getByTestId('slides-editor-done')).toBeEnabled();
    // The failure sits inline beside Done in the editor bar.
    const toolbar = await page.getByTestId('slides-editor-toolbar').boundingBox();
    const failed = await page.getByTestId('slides-editor-save-failed').boundingBox();
    expect(failed!.y).toBeGreaterThanOrEqual(toolbar!.y - 1);
    expect(failed!.y + failed!.height).toBeLessThanOrEqual(toolbar!.y + toolbar!.height + 1);
    await shot(page, testInfo, 'desktop-save-failed');
    await page.getByTestId('slides-editor-save-retry').click();
    await expect(editor(page)).toHaveAttribute('data-save-state', 'failed');
    await expect(editor(page)).toBeVisible();
    await expect(strip(page)).toHaveCount(4);
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('click selects with a frame and eight handles, empty click deselects, Delete removes', async ({ page }, testInfo) => {
    await openEditor(page);
    await expect(page.getByTestId('slides-editor-selection')).toHaveCount(0);
    await hit(page, 'e5').click();
    const frame = page.getByTestId('slides-editor-selection');
    await expect(frame).toHaveAttribute('data-element-id', 'e5');
    await expect(frame.getByTestId('slides-editor-handle')).toHaveCount(8);
    const frameBox = await frame.boundingBox();
    const hitBox = await hit(page, 'e5').boundingBox();
    expect(Math.abs(frameBox!.x - hitBox!.x)).toBeLessThan(2);
    expect(Math.abs(frameBox!.width - hitBox!.width)).toBeLessThan(2);
    await testInfo.attach('editor-desktop-selected', { body: await page.screenshot(), contentType: 'image/png' });

    // Bottom-right corner of slide 2 has no element.
    const stage = await page.getByTestId('slides-editor-canvas').boundingBox();
    await page.mouse.click(stage!.x + stage!.width - 12, stage!.y + stage!.height - 12);
    await expect(frame).toHaveCount(0);

    await hit(page, 'e5').click();
    await expect(frame).toHaveAttribute('data-element-id', 'e5');
    await page.keyboard.press('Delete');
    await expect(hit(page, 'e5')).toHaveCount(0);
    await expect(rendered(page, 'e5')).toHaveCount(0);
    await expect(frame).toHaveCount(0);
    await page.keyboard.press('ControlOrMeta+z');
    await expect(hit(page, 'e5')).toHaveCount(1);
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('drag moves and a handle resizes at a non-1 zoom; undo restores and redo reapplies', async ({ page }) => {
    await openEditor(page);
    const ratio = await unitsPerPixel(page);
    expect(Math.abs(ratio - 1)).toBeGreaterThan(0.2);
    const start = await geometry(page, 'e5');
    expect(start).toEqual({ x: 1300, y: 320, w: 480, h: 480 });

    await drag(page, await center(page, hit(page, 'e5')), -100, 60);
    await expect.poll(() => geometry(page, 'e5').then((box) => box.x)).not.toBe(start.x);
    const moved = await geometry(page, 'e5');
    expect(Math.abs(moved.x - (start.x - 100 * ratio))).toBeLessThanOrEqual(3);
    expect(Math.abs(moved.y - (start.y + 60 * ratio))).toBeLessThanOrEqual(3);
    expect({ w: moved.w, h: moved.h }).toEqual({ w: start.w, h: start.h });
    // The drawn element follows the core's geometry.
    const drawn = await rendered(page, 'e5').boundingBox();
    const box = await hit(page, 'e5').boundingBox();
    expect(Math.abs(drawn!.x - box!.x)).toBeLessThan(2);

    const handle = page.locator('[data-testid="slides-editor-handle"][data-handle="se"]');
    await drag(page, await center(page, handle), 40, 30);
    await expect.poll(() => geometry(page, 'e5').then((box) => box.w)).not.toBe(start.w);
    const resized = await geometry(page, 'e5');
    expect({ x: resized.x, y: resized.y }).toEqual({ x: moved.x, y: moved.y });
    expect(Math.abs(resized.w - (start.w + 40 * ratio))).toBeLessThanOrEqual(3);
    expect(Math.abs(resized.h - (start.h + 30 * ratio))).toBeLessThanOrEqual(3);

    await page.getByTestId('slides-editor-undo').click();
    await expect.poll(() => geometry(page, 'e5')).toEqual(moved);
    await page.getByTestId('slides-editor-undo').click();
    await expect.poll(() => geometry(page, 'e5')).toEqual(start);
    await expect(page.getByTestId('slides-editor-undo')).toBeDisabled();
    await page.getByTestId('slides-editor-redo').click();
    await expect.poll(() => geometry(page, 'e5')).toEqual(moved);
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('Ctrl+Z and Shift+Ctrl+Z undo and redo', async ({ page }) => {
    await openEditor(page);
    const start = await geometry(page, 'e5');
    await hit(page, 'e5').click();
    await page.keyboard.press('ArrowDown');
    await expect.poll(() => geometry(page, 'e5').then((box) => box.y)).toBe(start.y + 10);
    await page.keyboard.press('ControlOrMeta+z');
    await expect.poll(() => geometry(page, 'e5').then((box) => box.y)).toBe(start.y);
    await page.keyboard.press('ControlOrMeta+Shift+z');
    await expect.poll(() => geometry(page, 'e5').then((box) => box.y)).toBe(start.y + 10);
    await expect(editor(page)).toHaveAttribute('data-dirty', 'true');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('double-click edits text and the new text is committed', async ({ page }, testInfo) => {
    await openEditor(page);
    await hit(page, 'e3').dblclick();
    const input = page.getByTestId('slides-editor-text-input');
    await expect(input).toBeFocused();
    await expect(input).toHaveText('Highlights');
    await page.keyboard.press('ControlOrMeta+a');
    await page.keyboard.type('Key results');
    await expect(page.getByTestId('slides-editor-toolbar')).toBeVisible();
    await expect(page.getByTestId('slides-editor-context-bar')).toBeVisible();
    await expect(page.getByTestId('slides-editor-text-tools')).toBeVisible();
    await testInfo.attach('editor-text-editing', { body: await page.screenshot(), contentType: 'image/png' });
    // Clicking the empty canvas ends typing (blur commits).
    const stage = await page.getByTestId('slides-editor-canvas').boundingBox();
    await page.mouse.click(stage!.x + stage!.width - 12, stage!.y + stage!.height - 12);
    await expect(input).toHaveCount(0);
    await expect(rendered(page, 'e3')).toHaveText('Key results');
    await page.keyboard.press('ControlOrMeta+z');
    await expect(rendered(page, 'e3')).toHaveText('Highlights');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('toolbar font size, colour, bold and alignment change the computed style', async ({ page }) => {
    await openEditor(page, 'textSelected');
    await expect(page.getByTestId('slides-editor-selection')).toHaveAttribute('data-element-id', 'e3');
    const text = rendered(page, 'e3').getByTestId('slide-text');
    const style = () =>
      text.evaluate((element) => {
        const computed = getComputedStyle(element);
        return { size: computed.fontSize, weight: computed.fontWeight, color: computed.color, align: computed.textAlign };
      });
    const before = await style();
    expect(before.size).toBe('68px');
    expect(Number(before.weight)).toBeGreaterThanOrEqual(600);

    await page.getByTestId('slides-editor-size-up').click();
    await expect.poll(() => style().then((s) => s.size)).toBe('72px');
    await expect(page.getByTestId('slides-editor-font-size')).toHaveValue('72');
    await page.getByTestId('slides-editor-font-size').fill('90');
    await page.getByTestId('slides-editor-font-size').press('Enter');
    await expect.poll(() => style().then((s) => s.size)).toBe('90px');

    await page.getByTestId('slides-editor-bold').click();
    await expect.poll(() => style().then((s) => Number(s.weight))).toBeLessThan(600);
    await expect(page.getByTestId('slides-editor-bold')).toHaveAttribute('aria-pressed', 'false');

    // Colour: one swatch button opens the popover with the template swatches.
    const colorButton = page.getByTestId('slides-editor-color');
    const popover = page.getByTestId('slides-editor-color-popover');
    await expect(popover).toHaveCount(0);
    await colorButton.click();
    await expect(colorButton).toHaveAttribute('aria-expanded', 'true');
    await expect(popover).toBeVisible();
    await expect(popover.getByTestId('slides-editor-swatch')).toHaveCount(6);
    await expect(popover.getByTestId('slides-editor-custom-color')).toBeAttached();
    const accent = popover.locator('[data-testid="slides-editor-swatch"][data-color="accent"]');
    const accentColor = await accent.evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(accentColor).not.toBe(before.color);
    await accent.click();
    await expect.poll(() => style().then((s) => s.color)).toBe(accentColor);
    await expect(accent).toHaveAttribute('aria-pressed', 'true');
    // The button shows the current colour; Escape closes the popover and returns focus.
    await expect
      .poll(() => colorButton.locator('.slides-editor-color-dot').evaluate((element) => getComputedStyle(element).backgroundColor))
      .toBe(accentColor);
    await page.keyboard.press('Escape');
    await expect(popover).toHaveCount(0);
    await expect(colorButton).toBeFocused();
    await expect(page.getByTestId('slides-editor-selection')).toHaveAttribute('data-element-id', 'e3');
    // A press outside closes it too.
    await colorButton.click();
    await expect(popover).toBeVisible();
    await page.getByTestId('slides-editor-undo').hover();
    await page.mouse.down();
    await page.mouse.up();
    await expect(popover).toHaveCount(0);
    await page.getByTestId('slides-editor-redo').click();
    await expect.poll(() => style().then((s) => s.color)).toBe(accentColor);

    // Alignment: one button cycles left, centre, right; no native select.
    await expect(page.getByTestId('slides-editor-toolbar').locator('select')).toHaveCount(0);
    const align = page.getByTestId('slides-editor-align');
    expect(before.align).toMatch(/^(left|start)$/);
    await align.click();
    await expect.poll(() => style().then((s) => s.align)).toBe('center');
    await expect(align).toHaveAttribute('aria-label', /: Center$/i);
    await align.click();
    await expect.poll(() => style().then((s) => s.align)).toBe('right');
    await align.click();
    await expect.poll(() => style().then((s) => s.align)).toMatch(/^(left|start)$/);
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('forward and backward change the paint order of the selected element', async ({ page }) => {
    await openEditor(page);
    const paintOrder = () =>
      page
        .getByTestId('slides-editor-canvas')
        .getByTestId('slide-canvas')
        .locator('[data-element-id]')
        .evaluateAll((items) => items.map((item) => item.getAttribute('data-element-id')));
    await expect.poll(paintOrder).toEqual(['e3', 'e4', 'e5']);
    await hit(page, 'e5').click();
    await expect(page.getByTestId('slides-editor-bring-forward')).toBeDisabled();
    await page.getByTestId('slides-editor-send-backward').click();
    await expect.poll(paintOrder).toEqual(['e3', 'e5', 'e4']);
    await page.getByTestId('slides-editor-send-backward').click();
    await expect.poll(paintOrder).toEqual(['e5', 'e3', 'e4']);
    await expect(page.getByTestId('slides-editor-send-backward')).toBeDisabled();
    // The hit boxes follow the same order, so the element in front takes the click.
    const hits = await page.getByTestId('slides-editor-element').evaluateAll((items) => items.map((item) => item.getAttribute('data-element-id')));
    expect(hits).toEqual(['e5', 'e3', 'e4']);
    await page.getByTestId('slides-editor-bring-forward').click();
    await expect.poll(paintOrder).toEqual(['e3', 'e5', 'e4']);
    await page.keyboard.press('ControlOrMeta+z');
    await expect.poll(paintOrder).toEqual(['e5', 'e3', 'e4']);
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('Add text adds a text element', async ({ page }) => {
    await openEditor(page);
    const count = await page.getByTestId('slides-editor-element').count();
    await page.getByTestId('slides-editor-add-text').click();
    await expect(page.getByTestId('slides-editor-element')).toHaveCount(count + 1);
    const input = page.getByTestId('slides-editor-text-input');
    await expect(input).toBeFocused();
    const id = await input.getAttribute('data-element-id');
    expect(id).toBeTruthy();
    await page.keyboard.press('ControlOrMeta+a');
    await page.keyboard.type('Fresh note');
    await page.keyboard.press('Escape');
    await expect(rendered(page, id!)).toHaveText('Fresh note');
    await expect(hit(page, id!)).toHaveAttribute('data-kind', 'text');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('slides can be added, duplicated, moved and deleted', async ({ page }, testInfo) => {
    await openEditor(page);
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', 's3']);
    await expect(editor(page)).toHaveAttribute('data-slide-id', 's2');

    await page.getByTestId('slides-editor-add-slide').click();
    await expect(strip(page)).toHaveCount(4);
    const added = await editor(page).getAttribute('data-slide-id');
    expect(['s1', 's2', 's3']).not.toContain(added);
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', added, 's3']);
    await expect(page.locator('[data-testid="slides-editor-strip-item"][aria-current="true"]')).toHaveAttribute('data-slide-id', added!);

    await strip(page).nth(1).click();
    await expect(editor(page)).toHaveAttribute('data-slide-id', 's2');
    await expect(page.getByTestId('slides-editor-duplicate-slide')).toHaveCount(0);
    await openSlideActions(page);
    await page.getByTestId('slides-editor-duplicate-slide').click();
    await expect(strip(page)).toHaveCount(5);
    const copy = await editor(page).getAttribute('data-slide-id');
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', copy, added, 's3']);
    // The copy carries the original's elements under new ids.
    await expect(page.getByTestId('slides-editor-element')).toHaveCount(3);
    await openSlideActions(page);
    await shot(page, testInfo, 'desktop-slide-actions');

    await page.getByTestId('slides-editor-move-slide-left').click();
    await expect.poll(() => stripOrder(page)).toEqual(['s1', copy, 's2', added, 's3']);
    await page.getByTestId('slides-editor-move-slide-right').click();
    await page.getByTestId('slides-editor-move-slide-right').click();
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', added, copy, 's3']);

    await page.getByTestId('slides-editor-delete-slide').click();
    await expect(strip(page)).toHaveCount(4);
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', added, 's3']);
    await expect(editor(page)).toHaveAttribute('data-slide-id', 's3');
    // Escape closes the action row and returns focus to its button.
    await page.getByTestId('slides-editor-delete-slide').focus();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('slides-editor-slide-actions-menu')).toHaveCount(0);
    await expect(page.getByTestId('slides-editor-slide-actions')).toBeFocused();
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('speaker notes are collapsed behind the notes button and survive switching slides', async ({ page }, testInfo) => {
    await openEditor(page);
    const notes = page.getByTestId('slides-editor-notes');
    const toggle = page.getByTestId('slides-editor-notes-toggle');
    const badge = page.getByTestId('slides-editor-notes-badge');
    await expect(notes).toHaveCount(0);
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    // Slide 2 has notes: the button carries the badge; slide 3 has none.
    await expect(badge).toBeVisible();
    await strip(page).nth(2).click();
    await expect(badge).toHaveCount(0);
    await strip(page).nth(1).click();
    await expect(badge).toBeVisible();
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(notes).toBeVisible();
    // The notes open under the slide.
    const canvasBox = await page.getByTestId('slides-editor-canvas').boundingBox();
    const notesBox = await notes.boundingBox();
    expect(notesBox!.y).toBeGreaterThan(canvasBox!.y + canvasBox!.height);
    await expect(notes).toHaveValue('Stress the eighteen percent.');
    await shot(page, testInfo, 'desktop-notes-open');
    await notes.fill('Pause after the chart.');
    await strip(page).nth(2).click();
    await expect(editor(page)).toHaveAttribute('data-slide-id', 's3');
    await expect(notes).toHaveValue('');
    await strip(page).nth(0).click();
    await expect(notes).toHaveValue('Welcome everyone.');
    await strip(page).nth(1).click();
    await expect(notes).toHaveValue('Pause after the chart.');
    await expect(editor(page)).toHaveAttribute('data-dirty', 'true');
    // New notes on an empty slide bring the badge; closing keeps the notes.
    await strip(page).nth(2).click();
    await expect(badge).toHaveCount(0);
    await notes.fill('Thank the team.');
    await toggle.click();
    await expect(notes).toHaveCount(0);
    await expect(badge).toBeVisible();
    await toggle.click();
    await expect(notes).toHaveValue('Thank the team.');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('round icon buttons with tooltips; the contextual bar exists only for a selection', async ({ page }, testInfo) => {
    await openEditor(page);
    const context = page.getByTestId('slides-editor-context-bar');
    await expect(context, 'nothing selected: no contextual bar').toHaveCount(0);
    await expect(page.getByTestId('slides-editor-delete-element')).toHaveCount(0);
    await expect(page.getByTestId('slides-editor-bold')).toHaveCount(0);
    // Always on: undo, redo, add, notes, Done; slide actions stay behind one button.
    for (const id of ['slides-editor-undo', 'slides-editor-redo', 'slides-editor-add-text', 'slides-editor-notes-toggle', 'slides-editor-done', 'slides-editor-add-slide', 'slides-editor-slide-actions']) {
      await expect(page.getByTestId(id), id).toBeVisible();
    }
    await expect(page.getByTestId('slides-editor-duplicate-slide')).toHaveCount(0);
    await shot(page, testInfo, 'desktop-idle');

    // Desktop: one slim bar above the slide, the strip below it.
    const toolbar = await page.getByTestId('slides-editor-toolbar').boundingBox();
    const canvas = await page.getByTestId('slides-editor-canvas').boundingBox();
    const stripBox = await strip(page).first().boundingBox();
    const done = await page.getByTestId('slides-editor-done').boundingBox();
    expect(toolbar!.height).toBeLessThanOrEqual(done!.height + 2);
    expect(canvas!.y).toBeGreaterThanOrEqual(toolbar!.y + toolbar!.height);
    expect(stripBox!.y).toBeGreaterThanOrEqual(canvas!.y + canvas!.height);
    // The whole editor fits the window: the slide takes the height that is left.
    expect(stripBox!.y + stripBox!.height).toBeLessThanOrEqual(900);

    await hit(page, 'e3').click();
    await expect(context).toBeVisible();
    for (const id of ['slides-editor-delete-element', 'slides-editor-bring-forward', 'slides-editor-send-backward', 'slides-editor-size-down', 'slides-editor-font-size', 'slides-editor-size-up', 'slides-editor-bold', 'slides-editor-align', 'slides-editor-color']) {
      await expect(context.getByTestId(id), id).toBeVisible();
    }
    // Still one row on desktop with the contextual group.
    const withContext = await page.getByTestId('slides-editor-toolbar').boundingBox();
    expect(withContext!.height).toBeLessThanOrEqual(done!.height + 2);

    // Every icon button: an accessible name, a circle of the top-bar size, not the global 112px button.
    const shapes = await iconButtonShapes(page);
    expect(shapes.length).toBeGreaterThanOrEqual(14);
    for (const shape of shapes) {
      expect(shape.name, `${shape.id} has an accessible name`).not.toBe('');
      expect(Math.abs(shape.width - shape.height), `${shape.id} is round`).toBeLessThanOrEqual(0.5);
      expect(shape.radius, `${shape.id} radius`).toBeGreaterThanOrEqual(shape.height / 2 - 0.5);
      expect(shape.width, `${shape.id} is not a global 112px button`).toBeLessThan(60);
      expect(shape.width, `${shape.id} is tappable`).toBeGreaterThanOrEqual(36);
    }
    await shot(page, testInfo, 'desktop-text-selected');

    await expectTooltip(page, 'slides-editor-undo', 'Undo');
    await expectTooltip(page, 'slides-editor-add-text', 'Add text');
    await expectTooltip(page, 'slides-editor-delete-element', 'Delete');
    await expectTooltip(page, 'slides-editor-bold', 'Bold');
    await shot(page, testInfo, 'desktop-tooltip');
    // Tooltip inside the viewport (not clipped at the top edge).
    const tip = await page.getByRole('tooltip').boundingBox();
    expect(tip!.y).toBeGreaterThanOrEqual(0);
    await openSlideActions(page);
    await expectTooltip(page, 'slides-editor-duplicate-slide', 'Duplicate slide');
    await page.keyboard.press('Escape');

    await page.getByTestId('slides-editor-color').click();
    const popover = page.getByTestId('slides-editor-color-popover');
    await expect(popover).toBeVisible();
    const popoverBox = await popover.boundingBox();
    expect(popoverBox!.x).toBeGreaterThanOrEqual(0);
    expect(popoverBox!.x + popoverBox!.width).toBeLessThanOrEqual(1280);
    await shot(page, testInfo, 'desktop-colour-popover');
    await page.keyboard.press('Escape');
    await expect(popover).toHaveCount(0);

    // Escape with nothing open deselects: the contextual bar leaves again.
    await page.keyboard.press('Escape');
    await expect(context).toHaveCount(0);
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('selection handles at the slide edge stay visible outside the frame', async ({ page }, testInfo) => {
    await openEditor(page);
    const stage = await page.getByTestId('slides-editor-canvas').boundingBox();
    // Move the ellipse into the top-left corner so its handles leave the slide.
    await hit(page, 'e5').click();
    await expect(page.getByTestId('slides-editor-selection')).toHaveAttribute('data-element-id', 'e5');
    // One nudge at a time: each waits for the core's new geometry.
    for (const [key, axis] of [['Shift+ArrowLeft', 'x'], ['Shift+ArrowUp', 'y']] as const) {
      for (let step = 0; step < 40 && (await geometry(page, 'e5'))[axis] > 0; step += 1) {
        const before = (await geometry(page, 'e5'))[axis];
        await page.keyboard.press(key);
        await expect.poll(() => geometry(page, 'e5').then((box) => box[axis])).not.toBe(before);
      }
    }
    await expect.poll(() => geometry(page, 'e5').then((box) => [box.x, box.y])).toEqual([0, 0]);
    const corner = page.locator('[data-testid="slides-editor-handle"][data-handle="nw"]');
    const box = await corner.boundingBox();
    expect(box!.x).toBeLessThan(stage!.x);
    // Not clipped: the handle's centre point hits the handle itself.
    const hitTest = await corner.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2) === element;
    });
    expect(hitTest).toBe(true);
    await shot(page, testInfo, 'desktop-handles-edge');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('dark theme: the bar and the contextual tools stay readable', async ({ page }, testInfo) => {
    await openEditor(page, 'textSelected', { width: 1280, height: 900 }, { theme: 'dark' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByTestId('slides-editor-context-bar')).toBeVisible();
    const colours = await page.getByTestId('slides-editor-undo').evaluate((button) => ({
      background: getComputedStyle(button).backgroundColor,
      page: getComputedStyle(document.body).backgroundColor
    }));
    expect(colours.background).not.toBe('rgb(249, 249, 249)');
    await shot(page, testInfo, 'dark-theme-text-selected');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('phone width has no horizontal overflow, at most two control rows and every control is reachable', async ({ page }, testInfo) => {
    const width = 390;
    await openEditor(page, '', { width, height: 844 });
    await shot(page, testInfo, 'phone-idle');
    await hit(page, 'e3').click();
    await expect(page.getByTestId('slides-editor-text-tools')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);

    // Above the slide: the always-on row plus the contextual row, never more.
    const toolbar = await page.getByTestId('slides-editor-toolbar').boundingBox();
    const done = await page.getByTestId('slides-editor-done').boundingBox();
    const canvas = await page.getByTestId('slides-editor-canvas').boundingBox();
    expect(toolbar!.height, 'controls above the slide fit in two rows').toBeLessThanOrEqual(2 * done!.height + 24);
    expect(canvas!.y).toBeGreaterThanOrEqual(toolbar!.y + toolbar!.height);
    const rowTops = await page
      .getByTestId('slides-editor-toolbar')
      .locator('.embed-icon-button')
      .evaluateAll((buttons) => [...new Set(buttons.map((button) => Math.round(button.getBoundingClientRect().top)))]);
    expect(rowTops.length, `button rows ${rowTops.join(', ')}`).toBeLessThanOrEqual(2);
    await shot(page, testInfo, 'phone-text-selected');

    await openSlideActions(page);
    const controls = page.locator(
      '[data-testid="slides-editor-toolbar"] :is(button, input), [data-testid="slides-editor-done"], [data-testid^="slides-editor-"][data-testid$="-slide"], [data-testid^="slides-editor-move-slide"], [data-testid="slides-editor-slide-actions"]'
    );
    const count = await controls.count();
    expect(count).toBeGreaterThan(15);
    for (let index = 0; index < count; index += 1) {
      const control = controls.nth(index);
      await control.scrollIntoViewIfNeeded();
      const box = await control.boundingBox();
      const name = await control.evaluate((element) => element.getAttribute('data-testid') ?? element.outerHTML.slice(0, 60));
      expect(box, `${name} should be laid out`).not.toBeNull();
      expect(box!.x, `${name} should start inside the screen`).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, `${name} should end inside the screen`).toBeLessThanOrEqual(width + 0.5);
      expect(box!.width, `${name} should be wide enough to tap`).toBeGreaterThanOrEqual(24);
    }
    const after = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(after).toBeLessThanOrEqual(0);
  });
});
