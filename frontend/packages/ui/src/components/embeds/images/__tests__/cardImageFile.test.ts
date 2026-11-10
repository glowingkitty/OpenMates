import { describe, expect, it } from 'vitest';
import { cardImageFile } from '../cardImageFile';

const preview = (width: number, height: number) => ({ s3_key: 'p.webp', width, height, format: 'webp' });

describe('cardImageFile', () => {
  // contract-test: direct surface=gui.web assertions=images-generate.preview.whole-picture
  it('uses the preview when it holds the whole picture', () => {
    const files = { preview: preview(800, 800), full: { s3_key: 'f.webp', width: 1024, height: 1024 } };
    expect(cardImageFile(files)?.s3_key).toBe('p.webp');
  });

  // contract-test: direct surface=gui.web assertions=images-generate.preview.whole-picture
  it('uses the full file when an older preview was cropped to 600x400', () => {
    const files = { preview: preview(600, 400), full: { s3_key: 'f.webp', width: 1024, height: 1024 } };
    expect(cardImageFile(files)?.s3_key).toBe('f.webp');
  });

  // contract-test: direct surface=gui.web assertions=images-generate.preview.whole-picture
  it('keeps a 600x400 preview of a picture that really is 3:2', () => {
    const files = { preview: preview(600, 400), full: { s3_key: 'f.webp', width: 1536, height: 1024 } };
    expect(cardImageFile(files)?.s3_key).toBe('p.webp');
  });

  // contract-test: direct surface=gui.web assertions=images-generate.preview.whole-picture
  it('uses the vector original for an older cropped vector preview', () => {
    const files = { preview: preview(600, 400), original: { s3_key: 'o.svg', format: 'svg' } };
    expect(cardImageFile(files)?.s3_key).toBe('o.svg');
  });

  // contract-test: direct surface=gui.web assertions=images-generate.preview.whole-picture
  it('returns nothing without a preview', () => {
    expect(cardImageFile(undefined)).toBeUndefined();
    expect(cardImageFile({})).toBeUndefined();
  });
});
