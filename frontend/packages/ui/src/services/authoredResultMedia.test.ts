import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthoredResultMedia } from '../types/authoredResult';

const io = vi.hoisted(() => ({ fetch: vi.fn(), decrypt: vi.fn() }));
vi.mock('./presignedUrlService', () => ({ fetchWithPresignedUrl: io.fetch }));
vi.mock('./encryption/mediaEncryption', () => ({ decryptMediaPayload: io.decrypt }));

import { createAuthoredResultMediaOwner } from './authoredResultMedia';
import { clearCachedImages, fetchAndDecryptImage, getCachedImageUrl } from '../components/embeds/images/imageEmbedCrypto';
import { invalidateWorkspaceCaches } from './workspaceCacheLifecycle';

const bytes = () => new Uint8Array([1, 2, 3]).buffer;
const media = (name: string, extras: Partial<AuthoredResultMedia> = {}): AuthoredResultMedia => ({
  source_embed_id: `source-${name}`, s3_base_url: 'https://private-storage.example.org', aes_key: 'encrypted-content-key',
  aes_nonce: 'legacy-nonce', files: {
    preview: { s3_key: `${name}-preview.webp`, aes_nonce: 'preview-nonce', encryption: 'aes-gcm-v2' },
    original: { s3_key: `${name}-original.png`, encryption: 'aes-gcm-v2' },
  }, ...extras,
});

function deferred() {
  let resolve!: (data: ArrayBuffer) => void;
  const promise = new Promise<ArrayBuffer>(finish => { resolve = finish; });
  return { promise, resolve };
}

describe('selected authored-result media lifetime', () => {
  beforeEach(() => {
    clearCachedImages();
    vi.restoreAllMocks();
    vi.useFakeTimers();
    io.fetch.mockReset().mockResolvedValue(bytes());
    io.decrypt.mockReset().mockResolvedValue(bytes());
    let sequence = 0;
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:authored-${++sequence}`);
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  });
  afterEach(() => {
    clearCachedImages();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('owns only the selected preview variants, passes existing encryption metadata and preserves input order', async () => {
    const first = deferred();
    const second = deferred();
    io.fetch.mockImplementation((key: string) => key.startsWith('first') ? first.promise : second.promise);
    const descriptors = [media('first', { caption: 'First', attribution: 'Photographer' }), media('second')];
    const owner = createAuthoredResultMediaOwner();
    const pending = owner.resolve(descriptors);
    second.resolve(bytes());
    // Await the shared in-flight cache operation to settle the second image first.
    await fetchAndDecryptImage('', 'second-preview.webp', 'encrypted-content-key', '', descriptors[1].files.preview);
    first.resolve(bytes());
    expect(await pending).toEqual([
      { url: 'blob:authored-2', caption: 'First', attribution: 'Photographer' }, { url: 'blob:authored-1' },
    ]);
    expect(io.fetch.mock.calls.map(([key]) => key)).toEqual(['first-preview.webp', 'second-preview.webp']);
    expect(io.decrypt).toHaveBeenCalledWith(expect.objectContaining({
      aesKeyBase64: 'encrypted-content-key', legacyNonceBase64: 'legacy-nonce', variant: descriptors[0].files.preview,
    }));
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    owner.dispose();
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('releases the prior variant on update and selects fullscreen original or an available fallback', async () => {
    const owner = createAuthoredResultMediaOwner();
    await owner.resolve([media('one')]);
    const fullscreen = await owner.resolve([media('one')], 'fullscreen');
    expect(fullscreen).toEqual([{ url: 'blob:authored-2' }]);
    expect(io.fetch.mock.calls.map(([key]) => key)).toEqual(['one-preview.webp', 'one-original.png']);
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:authored-1');
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:authored-2');
    const fallback = media('fallback', { files: { full: { s3_key: 'full.webp' } }, aes_nonce: undefined });
    expect(await owner.resolve([fallback], 'fullscreen')).toEqual([{ url: 'blob:authored-3' }]);
    expect(io.decrypt).toHaveBeenLastCalledWith(expect.objectContaining({
      legacyNonceBase64: '', variant: fallback.files.full,
    }));
    owner.dispose();
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(3);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('keeps valid media in order when a selected image fails and ignores descriptors without encrypted files', async () => {
    io.fetch.mockImplementation(async (key: string) => {
      if (key.startsWith('broken')) throw new Error('Selected resource is unavailable');
      return bytes();
    });
    const owner = createAuthoredResultMediaOwner();
    expect(await owner.resolve([
      media('first'), media('broken'), media('missing', { files: {} }),
      { url: 'https://public.example.org/not-an-encrypted-descriptor' } as unknown as AuthoredResultMedia,
      media('last', { attribution: 'Archive' }),
    ])).toEqual([{ url: 'blob:authored-1' }, { url: 'blob:authored-2', attribution: 'Archive' }]);
    expect(io.fetch.mock.calls.map(([key]) => key)).toEqual(['first-preview.webp', 'broken-preview.webp', 'last-preview.webp']);
    owner.dispose();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('reuses existing cache ownership across views and duplicate descriptors without over-retaining', async () => {
    const preview = createAuthoredResultMediaOwner();
    const fullscreen = createAuthoredResultMediaOwner();
    await preview.resolve([media('shared'), media('shared')]);
    await fullscreen.resolve([media('shared')]);
    expect(io.fetch).toHaveBeenCalledOnce();
    preview.dispose();
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    fullscreen.dispose();
    fullscreen.dispose();
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:authored-1');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('discards stale results after an update and never retains the late URL', async () => {
    const slow = deferred();
    io.fetch.mockImplementation((key: string) => key.startsWith('slow') ? slow.promise : Promise.resolve(bytes()));
    const owner = createAuthoredResultMediaOwner();
    const stale = owner.resolve([media('slow')]);
    expect(await owner.resolve([media('current')])).toEqual([{ url: 'blob:authored-1' }]);
    slow.resolve(bytes());
    expect(await stale).toEqual([]);
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:authored-2');
    expect(getCachedImageUrl('current-preview.webp')).toBe('blob:authored-1');
    owner.dispose();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('does not retain or publish media completed after disposal and cannot be reused', async () => {
    const slow = deferred();
    io.fetch.mockReturnValue(slow.promise);
    const owner = createAuthoredResultMediaOwner();
    const pending = owner.resolve([media('late')]);
    owner.dispose();
    slow.resolve(bytes());
    expect(await pending).toEqual([]);
    expect(await owner.resolve([media('another')])).toEqual([]);
    expect(io.fetch).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(31_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:authored-1');
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('reuses the existing account-clear fence for pending decryptions and cached URLs', async () => {
    const cachedOwner = createAuthoredResultMediaOwner();
    await cachedOwner.resolve([media('cached')]);
    const pendingOwner = createAuthoredResultMediaOwner();
    const slow = deferred();
    io.fetch.mockReturnValue(slow.promise);
    const pending = pendingOwner.resolve([media('pending')]);
    invalidateWorkspaceCaches();
    slow.resolve(bytes());
    expect(await pending).toEqual([]);
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith('blob:authored-1');
    expect(await cachedOwner.resolve([media('cached')])).toEqual([]);
    cachedOwner.dispose();
    pendingOwner.dispose();
  });
});
