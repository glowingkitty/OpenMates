import { describe, expect, it } from 'vitest';
import { pickSlideImageVariants } from '../slideImage';

const webp = { s3_key: 'u/1_preview.webp', format: 'webp' };

describe('pickSlideImageVariants', () => {
  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  it('uses a sanitized uploaded vector as the animated variant and keeps the preview still', () => {
    const vector = { s3_key: 'u/1_vector.bin', format: 'svg', sanitized: true };
    const { still, animated } = pickSlideImageVariants({ files: { preview: webp, vector } });
    expect(animated).toBe(vector);
    expect(still).toBe(webp);
  });

  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  it('never animates an unsanitized vector', () => {
    const vector = { s3_key: 'u/1_vector.bin', format: 'svg' };
    expect(pickSlideImageVariants({ files: { preview: webp, vector } }).animated).toBeNull();
    expect(pickSlideImageVariants({ files: { preview: webp, vector: { ...vector, sanitized: false } } }).animated).toBeNull();
  });

  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  it('animates a sanitized generated SVG original', () => {
    const original = { s3_key: 'u/1_original.svg', format: 'svg', sanitized: true };
    const { still, animated } = pickSlideImageVariants({ files: { preview: webp, original } });
    expect(animated).toBe(original);
    expect(still).toBe(webp);
  });

  // contract-test: direct surface=gui.web assertions=slides.media.svg-declarative-animation
  it('returns only the still for a raster image', () => {
    const original = { s3_key: 'u/1_original.webp', format: 'webp' };
    expect(pickSlideImageVariants({ files: { preview: webp, original } })).toEqual({ still: webp, animated: null });
    expect(pickSlideImageVariants({ files: { original } })).toEqual({ still: original, animated: null });
  });
});
