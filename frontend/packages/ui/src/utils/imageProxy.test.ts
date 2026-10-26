import { describe, expect, it, vi } from 'vitest';

vi.mock('../config/api', () => ({ getPreviewUrl: () => 'https://preview.example.org' }));

import { proxyImage } from './imageProxy';

describe('image proxy local media bypass', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed
  it.each(['blob:https://app.example.org/private-image', 'data:image/png;base64,cGl4ZWxz', '/local/image.webp'])(
    'keeps %s local without proxying or adding resize parameters', (url) => {
      expect(proxyImage(url, 520)).toBe(url);
    },
  );

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('continues proxying public HTTPS images and preserves existing proxy URLs', () => {
    const url = 'https://images.example.org/photo.jpg';
    const proxied = proxyImage(url, 520);
    expect(proxied).toBe(`https://preview.example.org/api/v1/image?url=${encodeURIComponent(url)}&max_width=520`);
    expect(proxyImage(proxied, 1024)).toBe(proxied);
    expect(proxyImage(null)).toBe('');
  });
});
