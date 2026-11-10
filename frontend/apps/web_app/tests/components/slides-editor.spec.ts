// playwright-account: not_required reason=isolated_component_preview
// proof-video: not_required reason=visual_smoke_not_needed
//
// Manual slides editor against the real Rust core: the deck replica, every
// operation and undo/redo run in the shared Worker's wasm (deckDocument unit).
// Run in component mode with the web Rust core on:
//   ci_coordinator.py submit --mode component --web-rust-core --spec components/slides-editor.spec.ts
import { test, expect, type Page } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const EDITOR_PREVIEW = '/dev/preview/embeds/slides/SlidesEditor';
const FULLSCREEN_PREVIEW = '/dev/preview/embeds/slides/SlidesDeckEmbedFullscreen';
const CANVAS_WIDTH = 1920;

const url = (path: string, variant = '') => `${path}?${new URLSearchParams({ variant, chrome: '0' })}`;

const editor = (page: Page) => page.getByTestId('slides-editor');
const hit = (page: Page, id: string) => page.locator(`[data-testid="slides-editor-element"][data-element-id="${id}"]`);
const rendered = (page: Page, id: string) =>
  page.getByTestId('slides-editor-canvas').getByTestId('slide-canvas').locator(`[data-element-id="${id}"]`);
const strip = (page: Page) => page.getByTestId('slides-editor-strip-item');

async function waitForEditor(page: Page) {
  // The first open pays the wasm load of the shared Worker.
  await expect(editor(page), 'the Rust core should open the deck').toHaveAttribute('data-status', 'ready', { timeout: 60_000 });
}

async function openEditor(page: Page, variant = '', size = { width: 1280, height: 900 }) {
  await page.setViewportSize(size);
  await page.goto(url(EDITOR_PREVIEW, variant));
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

test.describe('Slides editor (Rust core)', () => {
  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('Edit opens the editor and Done shows the edited deck', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(url(FULLSCREEN_PREVIEW, 'editable'));
    await waitForComponentPreview(page);
    await expect(page.getByTestId('slide-strip-item')).toHaveCount(3);
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

    await page.getByTestId('slides-editor-done').click();
    await expect(editor(page)).toHaveCount(0);
    await expect(page.getByTestId('slide-strip-item')).toHaveCount(4);
    await expect(page.getByTestId('slide-position')).toHaveText(/\/ 4$/);
    await page.getByTestId('slide-strip-item').first().click();
    await expect(page.getByTestId('slides-deck-fullscreen').getByTestId('slide-canvas').first()).toContainText('Annual review');
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

    const accent = page.locator('[data-testid="slides-editor-swatch"][data-color="accent"]');
    const accentColor = await accent.evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(accentColor).not.toBe(before.color);
    await accent.click();
    await expect.poll(() => style().then((s) => s.color)).toBe(accentColor);
    await expect(accent).toHaveAttribute('aria-pressed', 'true');

    await page.getByTestId('slides-editor-align').selectOption('center');
    await expect.poll(() => style().then((s) => s.align)).toBe('center');
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
    await page.getByTestId('slides-editor-duplicate-slide').click();
    await expect(strip(page)).toHaveCount(5);
    const copy = await editor(page).getAttribute('data-slide-id');
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', copy, added, 's3']);
    // The copy carries the original's elements under new ids.
    await expect(page.getByTestId('slides-editor-element')).toHaveCount(3);
    await testInfo.attach('editor-slide-strip', { body: await page.screenshot(), contentType: 'image/png' });

    await page.getByTestId('slides-editor-move-slide-left').click();
    await expect.poll(() => stripOrder(page)).toEqual(['s1', copy, 's2', added, 's3']);
    await page.getByTestId('slides-editor-move-slide-right').click();
    await page.getByTestId('slides-editor-move-slide-right').click();
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', added, copy, 's3']);

    await page.getByTestId('slides-editor-delete-slide').click();
    await expect(strip(page)).toHaveCount(4);
    await expect.poll(() => stripOrder(page)).toEqual(['s1', 's2', added, 's3']);
    await expect(editor(page)).toHaveAttribute('data-slide-id', 's3');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('speaker notes survive switching slides', async ({ page }) => {
    await openEditor(page);
    const notes = page.getByTestId('slides-editor-notes');
    await expect(notes).toHaveValue('Stress the eighteen percent.');
    await notes.fill('Pause after the chart.');
    await strip(page).nth(2).click();
    await expect(editor(page)).toHaveAttribute('data-slide-id', 's3');
    await expect(notes).toHaveValue('');
    await strip(page).nth(0).click();
    await expect(notes).toHaveValue('Welcome everyone.');
    await strip(page).nth(1).click();
    await expect(notes).toHaveValue('Pause after the chart.');
    await expect(editor(page)).toHaveAttribute('data-dirty', 'true');
  });

  // contract-test: direct surface=gui.web assertions=slides.editor.direct-manipulation
  test('phone width has no horizontal overflow and every control is reachable', async ({ page }, testInfo) => {
    const width = 390;
    await openEditor(page, 'textSelected', { width, height: 844 });
    await expect(page.getByTestId('slides-editor-text-tools')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    const controls = page.locator(
      '[data-testid="slides-editor-toolbar"] :is(button, input, select), [data-testid="slides-editor-done"], [data-testid^="slides-editor-"][data-testid$="-slide"], [data-testid^="slides-editor-move-slide"]'
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
    await page.evaluate(() => window.scrollTo(0, 0));
    await testInfo.attach('editor-phone', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
});
