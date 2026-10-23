import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';
import { clickSettledScrollTarget } from '../helpers/chat-scroll';
import { createCipheriv } from 'node:crypto';
import { readFile } from 'node:fs/promises';
// playwright-account: not_required reason=isolated_component_preview

const id = '3c93f160-b0c4-4000-8000-000000000001';
const key = Buffer.from(Array.from({ length: 32 }, (_, index) => index));
const nonce = Buffer.from(Array.from({ length: 12 }, (_, index) => index));
const previewPath = '/dev/preview/embeds/images/ImageEmbedMessagePreview';

for (const width of [390, 1000]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction,chats.layout.responsive-history
  test(`assistant image copy and download work for direct and reference nodes at ${width}px`, async ({ page, context }, testInfo) => {
    test.setTimeout(180_000);
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.setViewportSize({ width, height: 900 });
    const response = await page.request.get('/images/examples/group1.jpg');
    expect(response.ok()).toBe(true);
    const bytes = await response.body();
    await page.route('**/api/v1/image?*', route => route.fulfill({ contentType: 'image/jpeg', body: bytes }));
    for (const presentation of ['direct', 'large', 'grouped']) {
      const params = new URLSearchParams({ chrome: '0', width: String(width), theme: 'dark', background: '#dbeafe',
        props: JSON.stringify({ presentation, width }) });
      await page.goto(`${previewPath}?${params}`);
      await waitForComponentPreview(page);
      const card = page.getByTestId('embed-preview').filter({ has: page.getByTestId('image-result-preview-image') }).nth(presentation === 'grouped' ? 1 : 0);
      await expect(card).toBeVisible();
      const image = card.getByTestId('image-result-preview-image');
      await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
      await expect(card.getByTestId('result-card-title')).toHaveCount(0);
      await page.evaluate(() => navigator.clipboard.writeText('before image copy'));
      // Open the real assistant menu through its explicit More control.
      await clickSettledScrollTarget(card.getByTestId('result-preview-more'), testInfo);
      const copy = page.getByRole('button', { name: 'Copy', exact: true });
      await expect(copy).toBeVisible();
      await copy.focus();
      await copy.press('Enter');
      await expect.poll(() => page.evaluate(async () => (await navigator.clipboard.read()).some(item => item.types.includes('image/png')))).toBe(true);
      const clipboard = await page.evaluate(async () => {
        const item = (await navigator.clipboard.read())[0];
        const png = await item.getType('image/png');
        const bitmap = await createImageBitmap(png);
        const html = await (await item.getType('text/html')).text();
        const meta = new DOMParser().parseFromString(html, 'text/html').querySelector('meta[name="x-openmates-embed"]');
        const reference = meta ? JSON.parse(decodeURIComponent(escape(atob(meta.getAttribute('content')!)))) : null;
        const result = { width: bitmap.width, height: bitmap.height, html, reference };
        bitmap.close();
        return result;
      });
      const natural = await image.evaluate((element: HTMLImageElement) => ({ width: element.naturalWidth, height: element.naturalHeight }));
      expect(clipboard.width).toBe(natural.width);
      expect(clipboard.height).toBe(natural.height);
      expect(clipboard.reference.contentRef).toBe(`embed:${presentation === 'grouped' ? id.replace(/1$/, '2') : id}`);
      expect(clipboard.reference.type).toBe('images-image-result');
      expect(clipboard.html).toContain('data:image/png;base64,');
      expect(clipboard.html).not.toContain('aes_key');

      await clickSettledScrollTarget(card.getByTestId('result-preview-more'), testInfo);
      const pending = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download', exact: true }).click();
      const download = await pending;
      expect(download.suggestedFilename()).toBe(presentation === 'grouped' ? 'openmates_second_landscape.jpg' : 'openmates_golden_gate_bridge.jpg');
      expect(await readFile((await download.path())!)).toEqual(bytes);
      await expect(card).toBeVisible();
      await expect(page.getByTestId('embed-fullscreen-overlay')).toHaveCount(0);
    }
  });
}

for (const kind of ['generated', 'uploaded']) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`assistant ${kind} image actions decrypt the original file`, async ({ page, context }, testInfo) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    const response = await page.request.get('/images/examples/group1.jpg');
    const bytes = await response.body();
    const cipher = createCipheriv('aes-256-gcm', key, nonce);
    const encrypted = Buffer.concat([cipher.update(bytes), cipher.final(), cipher.getAuthTag()]);
    const original = { s3_key: `e2e/image-actions/${kind}.bin`, format: 'jpg', width: 640, height: 480, size_bytes: bytes.length };
    await page.route('**/v1/embeds/presigned-url?*', route => route.fulfill({ json: { url: 'https://storage.example.org/original-image' } }));
    await page.route('https://storage.example.org/original-image', route => route.fulfill({ contentType: 'application/octet-stream', body: encrypted }));
    const record = { files: { preview: original, full: original, original }, aes_key: key.toString('base64'), aes_nonce: nonce.toString('base64'),
      s3_base_url: 'https://storage.example.org', filename: `${kind}-original.jpg` };
    await page.goto(`${previewPath}?chrome=0&width=900&props=${encodeURIComponent(JSON.stringify({ kind, presentation: 'large', record }))}`);
    await waitForComponentPreview(page);
    const card = page.getByTestId('embed-preview').first();
    await expect(card).toBeVisible();
    await expect.poll(() => card.getByRole('img').first().evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    await clickSettledScrollTarget(card.getByTestId('result-preview-more'), testInfo);
    const pending = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download', exact: true }).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe(`${kind}-original.jpg`);
    expect(await readFile((await download.path())!)).toEqual(bytes);
    await page.evaluate(() => navigator.clipboard.writeText('before encrypted image copy'));
    await clickSettledScrollTarget(card.getByTestId('result-preview-more'), testInfo);
    await page.getByRole('button', { name: 'Copy', exact: true }).click();
    await expect.poll(() => page.evaluate(async () => (await navigator.clipboard.read()).some(item => item.types.includes('image/png')))).toBe(true);
    const html = await page.evaluate(async () => (await (await navigator.clipboard.read())[0].getType('text/html')).text());
    expect(html).not.toContain(key.toString('base64'));
    expect(html).not.toContain(nonce.toString('base64'));
    expect(html).not.toContain('aes_key');
    expect(html).not.toContain('s3_base_url');
  });
}
