// playwright-account: not_required reason=isolated_component_preview
import { readFile } from 'node:fs/promises';
import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

// Editable Diagram Design Plan: composition, safe frames and editing controls.
const preview = (component: 'Preview' | 'Fullscreen', width: number, variant?: string) =>
  `/dev/preview/embeds/diagrams/DiagramHtmlEmbed${component}?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0',
    ...(variant ? { variant } : {}),
  })}`;

async function screenshot(page: Page, name: string) {
  const path = test.info().outputPath(name);
  await page.screenshot({ path, animations: 'disabled' });
  await test.info().attach(name, { path, contentType: 'image/png' });
}

for (const width of [390, 1280]) {
  for (const variant of ['light', undefined]) {
    // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
    test(`preserves the full upstream ${variant ?? 'dark'} composition at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(preview('Preview', width, variant));
      await waitForComponentPreview(page);
      const rendered = page.getByTestId('diagram-html-preview');
      await expect(rendered).toBeVisible();
      await expect(rendered).toHaveAttribute('data-layout-ready', 'true');
      await expect(page.getByTestId('embed-app-icon-mask')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
      const iframe = rendered.getByTestId('diagram-html-frame');
      await expect(iframe).toBeVisible();
      await expect(iframe).toHaveAttribute('sandbox', '');
      expect(await iframe.getAttribute('sandbox')).not.toContain('allow-same-origin');
      const frame = page.frameLocator('[data-testid="diagram-html-frame"]');
      await expect(frame.locator('svg[data-om-diagram]')).toBeVisible();
      await expect(frame.locator('svg text').first()).toBeVisible();
      expect(await frame.locator('svg text').count()).toBeGreaterThan(25);
      expect(await frame.locator('svg path').count()).toBeGreaterThan(15);
      await expect(frame.locator('svg defs marker').first()).toBeAttached();
      await frame.locator('body').evaluate(async () => { await document.fonts.ready; });
      const pageBackground = await frame.locator('body').evaluate(body => getComputedStyle(body).backgroundColor);
      await expect(rendered).toHaveCSS('background-color', pageBackground);
      const geometry = await rendered.evaluate(element => {
        const rect = element.getBoundingClientRect();
        return { left: rect.left, right: rect.right, width: rect.width, scroll: element.scrollWidth, client: element.clientWidth };
      });
      expect(geometry.left).toBeGreaterThanOrEqual(-1);
      expect(geometry.right).toBeLessThanOrEqual(width + 1);
      expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 2);
      // Standalone previews use the ordinary 300px embed card on both viewports.
      // The diagram fills that card; the chat's large container expands it separately.
      expect(geometry.width).toBeGreaterThan(250);
      const artboard = (await iframe.boundingBox())!;
      const viewport = (await rendered.boundingBox())!;
      expect(artboard.width / artboard.height).toBeCloseTo(1240 / 900, 3);
      expect(artboard.width).toBeLessThanOrEqual(viewport.width + 1);
      expect(artboard.height).toBeLessThanOrEqual(viewport.height + 1);
      const pageBounds = await frame.locator('body').evaluate(element => ({
        scroll: element.scrollHeight, viewport: document.documentElement.clientHeight,
      }));
      expect(pageBounds.scroll).toBeLessThanOrEqual(pageBounds.viewport + 1);
      await expect(rendered).not.toContainText('<svg');
      await expect(page.getByTestId('diagram-html-error')).toHaveCount(0);
      await screenshot(page, `diagram-preview-${variant ?? 'dark'}-${width}.png`);
    });
  }
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
test('fullscreen retains the source, provides matching edit/close controls, and supports text and layout undo', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(preview('Fullscreen', 1440, 'editable'));
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const canvas = page.getByTestId('diagram-html-canvas');
  await expect(page.getByTestId('diagram-html-fullscreen')).toBeVisible();
  await expect(canvas).toHaveAttribute('data-layout-ready', 'true');
  const frame = page.frameLocator('[data-testid="diagram-html-frame"]');
  await expect(frame.locator('svg[data-om-diagram]')).toBeVisible();
  const pageBackground = await frame.locator('body').evaluate(body => getComputedStyle(body).backgroundColor);
  await expect(canvas).toHaveCSS('background-color', pageBackground);
  await expect(page.getByTestId('diagram-html-fullscreen')).toHaveCSS('background-color', pageBackground);
  await expect(page.getByTestId('embed-fullscreen-overlay')).toHaveCSS('background-color', pageBackground);
  expect((await canvas.boundingBox())!.x + (await canvas.boundingBox())!.width).toBeLessThanOrEqual(1440);
  const edit = page.getByTestId('embed-edit-button');
  const close = page.getByTestId('embed-minimize');
  await expect(edit).toBeVisible();
  await expect(close).toBeVisible();
  await expect(edit.locator('.clickable-icon')).not.toHaveCSS('mask-image', 'none');
  const editBox = (await edit.boundingBox())!;
  const closeBox = (await close.boundingBox())!;
  expect(Math.abs(editBox.width - closeBox.width)).toBeLessThanOrEqual(2);
  expect(Math.abs(editBox.height - closeBox.height)).toBeLessThanOrEqual(2);
  expect(editBox.x).toBeLessThan(closeBox.x);
  expect(Math.abs(editBox.y - closeBox.y)).toBeLessThanOrEqual(2);
  await screenshot(page, 'diagram-fullscreen-original.png');

  const scaleBefore = await canvas.evaluate(element => getComputedStyle(element).getPropertyValue('--diagram-scale'));
  await page.getByTestId('diagram-html-zoom-in').click();
  await expect.poll(() => canvas.evaluate(element => getComputedStyle(element).getPropertyValue('--diagram-scale'))).not.toBe(scaleBefore);
  const canvasBox = (await canvas.boundingBox())!;
  await page.mouse.move(canvasBox.x + 50, canvasBox.y + 50);
  await page.mouse.down();
  await page.mouse.move(canvasBox.x + 90, canvasBox.y + 80, { steps: 4 });
  await page.mouse.up();
  expect(await canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-pan-x')))).not.toBe(0);
  await page.getByTestId('diagram-html-zoom-fit').click();
  expect(await canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-pan-x')))).toBe(0);

  const downloadPromise = page.waitForEvent('download');
  await page.getByTestId('diagram-html-export').click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.html$/);
  const exported = await readFile((await download.path())!, 'utf8');
  expect(exported).toContain('<svg');
  expect(exported).toContain('<defs>');
  expect(exported).toContain('data-om-component="nifi"');
  expect(exported).not.toMatch(/<script|data-om-runtime|diagram-html-text-editor/i);

  const label = frame.locator('text[data-om-text="nifi-text-2"]');
  const originalText = (await label.textContent())!;
  const node = frame.locator('g[data-om-component="nifi"]');
  const edge = frame.locator('g[data-om-edge="nifi-trino"] path[data-om-path]');
  const originalTransform = await node.getAttribute('transform');
  const originalPath = await edge.getAttribute('d');
  await edit.click();
  await expect(canvas).toHaveAttribute('data-editing', 'true');
  await expect(page.getByTestId('diagram-html-frame')).toHaveAttribute('sandbox', 'allow-scripts');
  await expect(canvas).toHaveAttribute('data-editor-ready', 'true');
  await label.click();
  const input = frame.getByTestId('diagram-html-text-editor');
  await expect(input).toBeVisible();
  await input.fill('Edited ingestion');
  await input.press('Enter');
  await expect(label).toHaveText('Edited ingestion');
  await page.getByTestId('diagram-html-undo').click();
  await expect(label).toHaveText(originalText);

  const edgeGeometry = () => edge.evaluate(path => {
    const curve = path as SVGPathElement;
    const connection = curve.closest('g[data-om-edge]') as SVGGElement;
    const root = curve.ownerSVGElement!;
    const from = root.querySelector<SVGGElement>(`g[data-om-component="${connection.dataset.omFrom}"]`)!.getBoundingClientRect();
    const to = root.querySelector<SVGGElement>(`g[data-om-component="${connection.dataset.omTo}"]`)!.getBoundingClientRect();
    const matrix = curve.getScreenCTM()!;
    const start = curve.getPointAtLength(0).matrixTransform(matrix);
    const end = curve.getPointAtLength(curve.getTotalLength()).matrixTransform(matrix);
    return {
      start: { x: start.x, y: start.y },
      end: { x: end.x, y: end.y },
      fromPort: { x: from.right, y: from.top + from.height / 2 },
      toPort: { x: to.left, y: to.top + to.height / 2 },
    };
  });
  const originalAttachment = await edgeGeometry();

  const nodeBox = (await node.boundingBox())!;
  const start = { x: nodeBox.x + 15, y: nodeBox.y + nodeBox.height - 8 };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + 45, start.y + 25, { steps: 8 });
  await page.mouse.up();
  await expect(node).not.toHaveAttribute('transform', originalTransform ?? '');
  await expect(edge).not.toHaveAttribute('d', originalPath ?? '');
  const attachment = await edgeGeometry();
  expect(attachment.start.x - attachment.fromPort.x).toBeCloseTo(originalAttachment.start.x - originalAttachment.fromPort.x, 1);
  expect(attachment.start.y - attachment.fromPort.y).toBeCloseTo(originalAttachment.start.y - originalAttachment.fromPort.y, 1);
  expect(attachment.end.x - attachment.toPort.x).toBeCloseTo(originalAttachment.end.x - originalAttachment.toPort.x, 1);
  expect(attachment.end.y - attachment.toPort.y).toBeCloseTo(originalAttachment.end.y - originalAttachment.toPort.y, 1);
  expect(attachment.start.x - originalAttachment.start.x).toBeCloseTo(attachment.fromPort.x - originalAttachment.fromPort.x, 1);
  expect(attachment.start.y - originalAttachment.start.y).toBeCloseTo(attachment.fromPort.y - originalAttachment.fromPort.y, 1);
  expect(attachment.end.x).toBeCloseTo(originalAttachment.end.x, 1);
  expect(attachment.end.y).toBeCloseTo(originalAttachment.end.y, 1);
  await screenshot(page, 'diagram-fullscreen-moving-component.png');
  await page.getByTestId('diagram-html-undo').click();
  await expect.poll(() => node.getAttribute('transform')).toBe(originalTransform);
  await expect.poll(() => edge.getAttribute('d')).toBe(originalPath);

  await label.click();
  await input.fill('Discarded text');
  await input.press('Enter');
  await page.getByTestId('diagram-html-cancel').click();
  await expect(canvas).toHaveAttribute('data-editing', 'false');
  await expect(page.getByTestId('diagram-html-frame')).toHaveAttribute('sandbox', '');
  await expect(label).toHaveText(originalText);
});

// contract-test: supporting surface=gui.web assertions=chats.layout.responsive-history
test('phone fullscreen keeps viewing and editing controls usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(preview('Fullscreen', 390, 'editable'));
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const canvas = page.getByTestId('diagram-html-canvas');
  await expect(canvas).toBeVisible();
  expect((await canvas.boundingBox())!.x + (await canvas.boundingBox())!.width).toBeLessThanOrEqual(390);
  await expect(page.frameLocator('[data-testid="diagram-html-frame"]').locator('svg[data-om-diagram]')).toBeVisible();
  await expect(page.getByTestId('embed-edit-button')).toBeVisible();
  await expect(page.getByTestId('embed-minimize')).toBeVisible();
  await screenshot(page, 'diagram-fullscreen-phone-fit.png');
  await page.getByTestId('diagram-html-zoom-in').click();
  await page.getByTestId('diagram-html-zoom-in').click();
  await screenshot(page, 'diagram-fullscreen-phone.png');
  const zoomedScale = await canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-scale')));
  await page.getByTestId('diagram-html-zoom-out').click();
  await expect.poll(() => canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-scale')))).toBeLessThan(zoomedScale);
  const zoomedCanvas = (await canvas.boundingBox())!;
  const panStart = { x: zoomedCanvas.x + zoomedCanvas.width / 2, y: zoomedCanvas.y + zoomedCanvas.height / 2 };
  await page.mouse.move(panStart.x, panStart.y);
  await page.mouse.down();
  await page.mouse.move(panStart.x + 45, panStart.y + 30, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-pan-x')))).toBeGreaterThan(40);
  await expect.poll(() => canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-pan-y')))).toBeGreaterThan(25);
  await screenshot(page, 'diagram-fullscreen-phone-zoomed-pan.png');
  await page.getByTestId('diagram-html-zoom-fit').click();
  await expect.poll(() => canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-pan-x')))).toBe(0);
  await expect.poll(() => canvas.evaluate(element => Number.parseFloat(getComputedStyle(element).getPropertyValue('--diagram-pan-y')))).toBe(0);
  await page.getByTestId('embed-edit-button').click();
  await expect(canvas).toHaveAttribute('data-editing', 'true');
  await expect(page.getByTestId('diagram-html-frame')).toHaveAttribute('sandbox', 'allow-scripts');
  await expect(canvas).toHaveAttribute('data-editor-ready', 'true');
  for (const action of ['diagram-html-undo', 'diagram-html-cancel', 'diagram-html-save']) {
    const button = page.getByTestId(action);
    await expect(button).toBeVisible();
    const box = (await button.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
  await screenshot(page, 'diagram-fullscreen-phone-edit-controls.png');
  await page.getByTestId('diagram-html-cancel').click();
  await expect(canvas).toHaveAttribute('data-editing', 'false');
  await expect(page.getByTestId('diagram-html-frame')).toHaveAttribute('sandbox', '');
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('editor moves the primary diagram while preserving a leading decorative SVG through undo', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(preview('Fullscreen', 1440, 'decorativeSvg'));
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const frame = page.frameLocator('[data-testid="diagram-html-frame"]');
  const decoration = frame.locator('svg[data-om-decorative]');
  const primary = frame.locator('svg[data-om-diagram]');
  await expect(decoration).toBeAttached();
  await expect(primary).toBeVisible();
  const decorationBefore = await decoration.evaluate(element => element.outerHTML);
  const node = primary.locator('g[data-om-component="nifi"]');
  const edge = primary.locator('g[data-om-edge="nifi-trino"] path[data-om-path]');
  const originalTransform = await node.getAttribute('transform');
  const originalPath = await edge.getAttribute('d');

  await page.getByTestId('embed-edit-button').click();
  await expect(page.getByTestId('diagram-html-canvas')).toHaveAttribute('data-editor-ready', 'true');
  const nodeBox = (await node.boundingBox())!;
  await page.mouse.move(nodeBox.x + 15, nodeBox.y + nodeBox.height - 8);
  await page.mouse.down();
  await page.mouse.move(nodeBox.x + 60, nodeBox.y + nodeBox.height + 17, { steps: 8 });
  await page.mouse.up();
  await expect(node).not.toHaveAttribute('transform', originalTransform ?? '');
  await expect(edge).not.toHaveAttribute('d', originalPath ?? '');
  await expect(decoration).toHaveJSProperty('outerHTML', decorationBefore);
  await screenshot(page, 'diagram-primary-svg-with-leading-decoration-moved.png');

  await page.getByTestId('diagram-html-undo').click();
  await expect.poll(() => node.getAttribute('transform')).toBe(originalTransform);
  await expect.poll(() => edge.getAttribute('d')).toBe(originalPath);
  await expect(decoration).toHaveJSProperty('outerHTML', decorationBefore);
  await expect(primary).toHaveCount(1);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('same-chat selections preserve an editable draft while a different chat closes fullscreen', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(preview('Fullscreen', 1280, 'chatLifecycle'));
  await waitForComponentPreview(page);
  const overlay = page.getByTestId('embed-fullscreen-overlay');
  await expect(overlay).toBeVisible();
  await page.getByTestId('embed-edit-button').click();
  const canvas = page.getByTestId('diagram-html-canvas');
  await expect(canvas).toHaveAttribute('data-editor-ready', 'true');
  const frame = page.frameLocator('[data-testid="diagram-html-frame"]');
  const label = frame.locator('text[data-om-text="nifi-text-2"]');
  await label.click();
  const input = frame.getByTestId('diagram-html-text-editor');
  await input.fill('Unsaved diagram draft');
  await input.press('Enter');
  await expect(label).toHaveText('Unsaved diagram draft');

  await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', {
    detail: { chatId: 'preview-diagrams-html-chat' },
  })));
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', {
    detail: { chat: { chat_id: 'preview-diagrams-html-chat' } },
  })));
  await expect(overlay).toBeVisible();
  await expect(canvas).toHaveAttribute('data-editing', 'true');
  await expect(label).toHaveText('Unsaved diagram draft');

  await page.evaluate(() => window.dispatchEvent(new CustomEvent('globalChatSelected', {
    detail: { chatId: 'another-chat' },
  })));
  await expect(overlay).toHaveCount(0);
});

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
test('unsafe source produces a visible error without executing scripts or loading external assets', async ({ page }) => {
  const unexpectedRequests: string[] = [];
  page.on('request', request => {
    if (/example\.invalid|attacker|fonts\.googleapis/.test(request.url())) unexpectedRequests.push(request.url());
  });
  await page.goto(preview('Fullscreen', 1280, 'unsafe'));
  await waitForComponentPreview(page);
  await expect(page.getByTestId('diagram-html-error')).toBeVisible();
  await expect(page.getByTestId('diagram-html-frame')).toHaveCount(0);
  expect(unexpectedRequests).toEqual([]);
  expect(await page.evaluate(() => (window as Window & { diagramInjection?: unknown }).diagramInjection)).toBeUndefined();
});
