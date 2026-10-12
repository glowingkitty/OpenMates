// playwright-account: not_required reason=isolated_component_preview
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Page } from '@playwright/test';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentMotion, waitForComponentPreview } from '../helpers/component-preview';

interface GeneratedDiagram {
  id: string;
  prompt: string;
  html_file: string;
  sha256: string;
  guidance_type: string;
  guidance_revision: string;
  render_width: number;
  render_height: number;
  background: string;
  diagram_kind: string;
  required_labels: string[];
  generation_status?: string;
  generation_error_code?: string;
}
const artifactsDirectory = resolve(process.cwd(), '../../packages/ui/src/components/embeds/diagrams');
const examples = JSON.parse(readFileSync(resolve(artifactsDirectory, 'diagramHtmlGeneratedProvenance.json'), 'utf8')) as GeneratedDiagram[];

function preview(component: 'Preview' | 'Fullscreen', width: number, variant: string) {
  return `/dev/preview/embeds/diagrams/DiagramHtmlEmbed${component}?${new URLSearchParams({
    theme: 'light', background: '#dbeafe', width: String(width), chrome: '0', variant,
  })}`;
}
async function screenshot(page: Page, name: string) {
  const path = test.info().outputPath(name);
  await page.screenshot({ path, animations: 'disabled' });
  await test.info().attach(name, { path, contentType: 'image/png' });
}

for (const example of examples) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  test(`preserves the real natural-language ${example.id} result on desktop and phone`, async ({ page }) => {
    test.setTimeout(60_000);
    const sourceBytes = readFileSync(resolve(artifactsDirectory, example.html_file));
    expect(createHash('sha256').update(sourceBytes).digest('hex')).toBe(example.sha256);
    expect(example.prompt.length).toBeGreaterThan(30);
    expect(example.required_labels.length).toBeGreaterThanOrEqual(3);
    expect(example.guidance_revision).toMatch(/^[a-f0-9]{64}$/);
    const externalRequests: Array<Promise<string | null>> = [];
    page.on('request', request => {
      const url = new URL(request.url());
      if (!url.protocol.startsWith('http') || ['localhost', '127.0.0.1'].includes(url.hostname)) return;
      try {
        const requestFrame = request.frame();
        externalRequests.push(requestFrame.frameElement()
          .then(async element => ['diagram-html-frame', 'diagram-html-measure-frame'].includes(await element.getAttribute('data-testid') ?? '') ? request.url() : null)
          .catch(() => requestFrame.url() === 'about:srcdoc' ? request.url() : null));
      } catch {
        // Browser-level requests without an initiating frame cannot come from the diagram iframe.
      }
    });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      for (const component of ['Preview', 'Fullscreen'] as const) {
        await page.goto(preview(component, width, example.id));
        await waitForComponentPreview(page);
        if (component === 'Fullscreen') await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
        const surround = page.getByTestId(component === 'Preview' ? 'diagram-html-preview' : 'diagram-html-canvas');
        await expect(surround).toHaveAttribute('data-layout-ready', 'true');
        const iframe = page.getByTestId('diagram-html-frame');
        await expect(iframe).toBeVisible();
        await expect(iframe).toHaveAttribute('sandbox', '');
        await expect(page.getByTestId('diagram-html-measure-frame')).toHaveAttribute('sandbox', 'allow-scripts');
        const frame = page.frameLocator('[data-testid="diagram-html-frame"]');
        await expect(frame.locator('svg[data-om-diagram]')).toBeVisible();
        await frame.locator('body').evaluate(async () => { await document.fonts.ready; });
        const fidelity = await frame.locator('body').evaluate((body, original) => {
          const expected = new DOMParser().parseFromString(original, 'text/html');
          return {
            expectedSvg: expected.querySelector('svg[data-om-diagram]')?.outerHTML,
            actualSvg: document.querySelector('svg[data-om-diagram]')?.outerHTML,
            text: body.textContent ?? '',
            background: getComputedStyle(body).backgroundColor,
            scrollHeight: body.scrollHeight,
            viewportHeight: document.documentElement.clientHeight,
          };
        }, sourceBytes.toString('utf8'));
        expect(fidelity.actualSvg).toBe(fidelity.expectedSvg);
        for (const label of example.required_labels) expect(fidelity.text).toContain(label);
        expect(fidelity.viewportHeight).toBeGreaterThanOrEqual(example.render_height);
        expect(fidelity.viewportHeight).toBeLessThanOrEqual(4096);
        expect(fidelity.scrollHeight).toBeLessThanOrEqual(fidelity.viewportHeight + 1);
        await expect(surround).toHaveCSS('background-color', fidelity.background);
        if (component === 'Fullscreen') {
          await expect(page.getByTestId('embed-fullscreen-overlay')).toHaveCSS('background-color', fidelity.background);
        }
        const artboard = (await iframe.boundingBox())!;
        expect(artboard.width / artboard.height).toBeCloseTo(example.render_width / fidelity.viewportHeight, 3);
        const container = (await surround.boundingBox())!;
        expect(container.x).toBeGreaterThanOrEqual(-1);
        expect(container.x + container.width).toBeLessThanOrEqual(width + 1);
        await expect(page.getByTestId('diagram-html-error')).toHaveCount(0);
        await screenshot(page, `diagram-real-${example.id}-${component.toLowerCase()}-${width}.png`);
      }
    }
    expect((await Promise.all(externalRequests)).filter((url): url is string => url !== null)).toEqual([]);
    await test.info().attach('real-generation-provenance', {
      body: JSON.stringify({ prompt: example.prompt, sha256: example.sha256, guidance_type: example.guidance_type, guidance_revision: example.guidance_revision,
        generation_status: example.generation_status, generation_error_code: example.generation_error_code }),
      contentType: 'application/json',
    });
  });
}

// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
test('keeps passwordless sequence message chronology and column shapes attached while dragging', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(preview('Fullscreen', 1440, 'generatedPasswordless'));
  await waitForComponentPreview(page);
  await waitForComponentMotion(page.getByTestId('embed-fullscreen-overlay'));
  const frame = page.frameLocator('[data-testid="diagram-html-frame"]');
  await page.getByTestId('embed-edit-button').click();
  await expect(page.getByTestId('diagram-html-canvas')).toHaveAttribute('data-editor-ready', 'true');
  const actor = frame.locator('g[data-om-component="actor-app"]');
  const primary = frame.locator('svg[data-om-diagram="sequence"]');
  const originalSvg = await primary.evaluate(element => element.outerHTML);
  const lifeline = primary.locator(':scope > line[x1="360"][x2="360"][y1="108"]');
  const activations = primary.locator(':scope > rect[x="356"][width="8"]');
  await expect(lifeline).toHaveCount(1);
  await expect(activations).toHaveCount(2);
  const originalColumnX = (await lifeline.boundingBox())!.x;
  const paths = primary.locator('g[data-om-edge] path[data-om-path]');
  const endpoints = () => paths.evaluateAll(elements => elements.map(element => {
    const path = element as SVGPathElement;
    const start = path.getPointAtLength(0);
    const end = path.getPointAtLength(path.getTotalLength());
    return { id: path.closest('g')!.getAttribute('data-om-edge'), sx: start.x, sy: start.y, ex: end.x, ey: end.y };
  }));
  const before = await endpoints();
  expect(before).toHaveLength(10);
  expect(new Set(before.map(item => item.sy)).size).toBe(10);
  const frameScale = await page.getByTestId('diagram-html-frame').evaluate(element =>
    element.getBoundingClientRect().width / element.clientWidth);
  const horizontalPixels = await actor.evaluate(element => (element as SVGGElement).getScreenCTM()!.a * 40) * frameScale;
  const box = (await actor.boundingBox())!;
  const start = { x: box.x + 8, y: box.y + box.height - 4 };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + horizontalPixels, start.y + 20, { steps: 8 });
  await page.mouse.up();
  await expect(actor).toHaveAttribute('transform', /translate\(/);
  const after = await endpoints();
  for (let i = 0; i < before.length; i++) {
    expect(after[i].sy).toBeCloseTo(before[i].sy, 2);
    expect(after[i].ey).toBeCloseTo(before[i].ey, 2);
  }
  for (const id of ['msg-2', 'msg-6']) {
    const original = before.find(item => item.id === id)!;
    const moved = after.find(item => item.id === id)!;
    expect(moved.sx - original.sx).toBeCloseTo(40, 1);
    expect(moved.ex).toBeCloseTo(original.ex, 2);
  }
  expect((await lifeline.boundingBox())!.x - originalColumnX).toBeCloseTo(horizontalPixels, 1);
  for (const activation of await activations.all()) {
    await expect(activation).toHaveAttribute('transform', /translate\(/);
  }
  await screenshot(page, 'diagram-real-sequence-edit-drag.png');
  await page.getByTestId('diagram-html-undo').click();
  await expect.poll(() => primary.evaluate(element => element.outerHTML)).toBe(originalSvg);
  await page.getByTestId('diagram-html-cancel').click();
  await expect(page.getByTestId('diagram-html-frame')).toHaveAttribute('sandbox', '');
});
