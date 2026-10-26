// playwright-account: not_required reason=isolated_component_preview
import { createCipheriv } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from '../helpers/cookie-audit';
import { waitForComponentPreview } from '../helpers/component-preview';

const key = Buffer.from('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f', 'hex');
const nonce = Buffer.from('000102030405060708090a0b', 'hex');
const source = readFileSync(resolve(__dirname, '../fixtures/sample.png'));
const cipher = createCipheriv('aes-256-gcm', key, nonce);
const encrypted = Buffer.concat([cipher.update(source), cipher.final(), cipher.getAuthTag()]);

for (const width of [390, 1280]) {
  for (const { variant, name } of [
    { variant: undefined, name: 'nonce-prefixed upload' },
    { variant: 'legacyEncrypted', name: 'legacy encryption' },
    { variant: 'variantNonce', name: 'per-file nonce' },
  ]) {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  test(`renders the viewed image with ${name} at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    let downloads = 0;
    await page.route('**/v1/embeds/presigned-url**', route => {
      const filename = new URL(route.request().url()).searchParams.get('s3_key')!.split('/').pop();
      return route.fulfill({ json: { url: `${new URL(route.request().url()).origin}/__image-view/${filename}` } });
    });
    await page.route('**/__image-view/*', route => {
      downloads += 1;
      return route.fulfill({ contentType: 'application/octet-stream', body:
        route.request().url().endsWith('/v2.png') ? Buffer.concat([nonce, encrypted]) : encrypted });
    });
        const params = new URLSearchParams({ chrome: '0', theme: width === 390 ? 'dark' : 'light',
          background: '#dbeafe', width: String(Math.min(width, 680)),
          props: JSON.stringify({ isMobile: width === 390 }), ...(variant ? { variant } : {}) });
        await page.goto(`/dev/preview/embeds/images/ImageViewEmbedPreview?${params}`);
        await waitForComponentPreview(page);
        const card = page.getByTestId('embed-preview');
        const image = card.getByRole('img', { name: 'golden-gate-sunset.jpg' });
        await expect(image).toBeVisible();
        await expect(image).toHaveAttribute('src', /^blob:/);
        await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true);
        await expect(image).toHaveCSS('object-fit', 'contain');
        await expect(card.locator('.skeleton-content')).toHaveCount(0);
        await expect(card.getByTestId('result-card-title')).toHaveCount(0);
        await expect(card.getByTestId('embed-basic-infos-bar')).toHaveCount(0);
        const bounds = (await card.boundingBox())!;
        expect(bounds.x).toBeGreaterThanOrEqual(0);
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    expect(downloads).toBe(1);
  });
  }
}
