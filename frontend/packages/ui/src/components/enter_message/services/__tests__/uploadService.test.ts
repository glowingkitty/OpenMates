import { beforeEach, describe, expect, it, vi } from 'vitest';

const sanitizeUploadBytes = vi.hoisted(() => vi.fn());
vi.mock('@repo/upload-privacy', () => ({
  sanitizeUploadBytes,
}));
vi.mock('../../../../config/api.js', () => ({ getUploadUrl: () => 'https://upload.example.test' }));

import { uploadFileToServer } from '../uploadService';

const success = {
  embed_id: 'embed-1', filename: 'private-photo.png', content_type: 'image/png', content_hash: 'hash',
  files: {}, s3_base_url: '', aes_key: '', aes_nonce: '', vault_wrapped_aes_key: '',
  malware_scan: 'clean', ai_detection: null, deduplicated: false,
};

class FakeXHR {
  static instances: FakeXHR[] = [];
  upload = { addEventListener: vi.fn() };
  handlers = new Map<string, () => void>();
  status = 200;
  responseText = JSON.stringify(success);
  timeout = 0;
  withCredentials = false;
  sentBody: FormData | null = null;
  open = vi.fn();
  abort = vi.fn();
  constructor() { FakeXHR.instances.push(this); }
  addEventListener(name: string, callback: () => void) { this.handlers.set(name, callback); }
  send(body: FormData) {
    this.sentBody = body;
    queueMicrotask(() => this.handlers.get('load')?.());
  }
}

describe('web upload privacy boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeXHR.instances = [];
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
  });

  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('sends sanitized bytes while preserving the filename through multipart upload', async () => {
    const original = new File(['original metadata'], 'private-photo.png', { type: 'image/png' });
    sanitizeUploadBytes.mockResolvedValue({
      bytes: new TextEncoder().encode('sanitized pixels'), mimeType: 'image/png',
      filename: 'private-photo.png', status: 'sanitized',
    });

    const response = await uploadFileToServer(original);
    expect(response.filename).toBe('private-photo.png');

    const sent = FakeXHR.instances[0].sentBody?.get('file') as File;
    expect(sent.name).toBe('private-photo.png');
    expect(sent.type).toBe('image/png');
    expect(await sent.text()).toBe('sanitized pixels');
    const [bytes, mimeType, filename] = sanitizeUploadBytes.mock.calls[0];
    expect(Array.from(bytes as Uint8Array)).toEqual(Array.from(new TextEncoder().encode('original metadata')));
    expect([mimeType, filename]).toEqual(['image/png', 'private-photo.png']);
  });

  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('continues with original bytes and filename after sanitizer failure', async () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    sanitizeUploadBytes.mockRejectedValue(new Error('private-photo.png: hidden metadata'));

    await uploadFileToServer(new File(['original bytes'], 'private-photo.png', { type: 'image/png' }));

    const sent = FakeXHR.instances[0].sentBody?.get('file') as File;
    expect(sent.name).toBe('private-photo.png');
    expect(await sent.text()).toBe('original bytes');
    expect(warning).toHaveBeenCalledWith('[UploadPrivacy] Metadata cleanup failed; continuing upload.');
    expect(JSON.stringify(warning.mock.calls)).not.toContain('private-photo');
    warning.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('does not prepare or send a request when already aborted', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(uploadFileToServer(new File(['data'], 'photo.png'), controller.signal))
      .rejects.toMatchObject({ name: 'AbortError' });
    expect(sanitizeUploadBytes).not.toHaveBeenCalled();
    expect(FakeXHR.instances).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('does not create XHR if aborted while preparation is pending', async () => {
    let finish!: (value: unknown) => void;
    sanitizeUploadBytes.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const controller = new AbortController();
    const pending = uploadFileToServer(new File(['data'], 'photo.png', { type: 'image/png' }), controller.signal);
    await vi.waitFor(() => expect(sanitizeUploadBytes).toHaveBeenCalled());
    controller.abort();
    finish({ bytes: new TextEncoder().encode('clean'), mimeType: 'image/png', filename: 'photo.png', status: 'sanitized' });
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(FakeXHR.instances).toHaveLength(0);
  });
});
