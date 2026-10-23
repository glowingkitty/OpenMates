import { beforeEach, describe, expect, it, vi } from 'vitest';
import { resolveImageEmbedFile } from './imageEmbedActions';
import { resolveEmbed } from '../../../services/embedResolver';
import { fetchAndDecryptImage } from './imageEmbedCrypto';
import { getWorkspaceCacheEpoch } from '../../../services/workspaceCacheLifecycle';
import { proxyImage } from '../../../utils/imageProxy';

vi.mock('../../../services/embedResolver', () => ({ resolveEmbed: vi.fn(), decodeToonContent: vi.fn(JSON.parse) }));
vi.mock('./imageEmbedCrypto', () => ({ fetchAndDecryptImage: vi.fn() }));
vi.mock('../../../message_parsing/serializers', () => ({ writeEmbedToClipboard: vi.fn() }));
vi.mock('../../../services/workspaceCacheLifecycle', () => ({ getWorkspaceCacheEpoch: vi.fn(() => 0) }));

describe('assistant image-file resolution', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(getWorkspaceCacheEpoch).mockReturnValue(0); });
  const seed = (data: Record<string, unknown>) => vi.mocked(resolveEmbed).mockResolvedValue({
    content: JSON.stringify(data),
  } as Awaited<ReturnType<typeof resolveEmbed>>);

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('fetches the full external image through the privacy proxy without thumbnail resizing', async () => {
    seed({ image_url: 'https://images.example.org/full.jpg', thumbnail_url: 'https://images.example.org/thumb.jpg', title: 'A bridge' });
    const blob = new Blob(['file bytes'], { type: 'image/jpeg' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, blob: async () => blob } as Response);
    const file = await resolveImageEmbedFile('child-id');
    expect(fetchMock).toHaveBeenCalledWith(proxyImage('https://images.example.org/full.jpg'));
    expect(file).toEqual({ blob, filename: 'openmates_a_bridge.jpg' });
    fetchMock.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('decrypts the original variant and preserves an uploaded filename and MIME type', async () => {
    const original = { s3_key: 'private/original.bin', format: 'jpg', aes_nonce: 'variant-nonce' };
    seed({ files: { original, preview: { s3_key: 'private/thumb.bin' } }, aes_key: 'private-key',
      s3_base_url: 'https://storage.example.org', filename: 'holiday.jpg' });
    vi.mocked(fetchAndDecryptImage).mockResolvedValue(new Blob(['original'], { type: 'image/webp' }));
    const file = await resolveImageEmbedFile('uploaded-id');
    expect(fetchAndDecryptImage).toHaveBeenCalledWith('https://storage.example.org', 'private/original.bin', 'private-key', '', original);
    expect(file.filename).toBe('holiday.jpg');
    expect(file.blob.type).toBe('image/jpeg');
    expect(file.blob.size).toBe(8);
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('fails closed when the original has no encryption metadata', async () => {
    seed({ files: { original: { s3_key: 'private/original.bin' } }, aes_key: 'private-key', image_url: 'https://images.example.org/fallback.jpg' });
    await expect(resolveImageEmbedFile('broken-id')).rejects.toThrow('encryption metadata');
    expect(fetchAndDecryptImage).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('rejects a non-image response instead of downloading an error document', async () => {
    seed({ image_url: 'https://images.example.org/missing.jpg' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true, blob: async () => new Blob(['error'], { type: 'text/html' }),
    } as Response);
    await expect(resolveImageEmbedFile('missing-id')).rejects.toThrow('not an image');
    fetchMock.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
  it('discards an in-flight file after account or workspace invalidation', async () => {
    seed({ image_url: 'https://images.example.org/full.jpg' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      vi.mocked(getWorkspaceCacheEpoch).mockReturnValue(1);
      return { ok: true, blob: async () => new Blob(['file'], { type: 'image/jpeg' }) } as Response;
    });
    await expect(resolveImageEmbedFile('old-context-id')).rejects.toThrow('Image context changed');
    fetchMock.mockRestore();
  });
});
