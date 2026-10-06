import { describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';

vi.mock('../../../../config/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../../config/api')>()),
  getApiUrl: () => 'https://api.example.test',
}));
vi.mock('../../../../services/embedStore', () => ({ embedStore: { put: vi.fn() } }));
vi.mock('../../utils', () => ({
  getLanguageFromFilename: vi.fn(), extractEpubCover: vi.fn(), getEpubMetadata: vi.fn(),
  resizeImage: vi.fn(), resizeForUpload: vi.fn(),
}));
vi.mock('../uploadService', () => ({ uploadFileToServer: vi.fn() }));
vi.mock('../../services/codeEmbedService', () => ({
  createCodeEmbed: vi.fn(), createDocEmbed: vi.fn(), createMailEmbed: vi.fn(),
  createMindMapEmbed: vi.fn(), detectLanguageFromContent: vi.fn(),
  redactEmbedContent: vi.fn(), createSheetEmbed: vi.fn(),
}));
vi.mock('../../services/mindMapUploadDetection', () => ({ classifyMindMapUploadSource: vi.fn() }));
vi.mock('../../utils/fileContentParsers', () => ({
  delimitedTextToMarkdownTable: vi.fn(), docxArrayBufferToHtml: vi.fn(),
  parseEmlText: vi.fn(), xlsxArrayBufferToMarkdownTable: vi.fn(),
}));
vi.mock('../../../../services/audioRealtimeTranscription', () => ({ REALTIME_TRANSCRIPTION_MODEL: 'realtime-test' }));
vi.mock('../../../../stores/settingsDeepLinkStore', () => ({ settingsDeepLink: { set: vi.fn() } }));
vi.mock('../../../../stores/panelStateStore', () => ({ panelState: { openSettings: vi.fn() } }));

import { retryTranscription } from '../../embedHandlers';

describe('recording transcription retry privacy', () => {
  // contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
  it('preserves the filename and provided folder path through transcription retry', async () => {
    let attrs: Record<string, unknown> = {
      id: 'recording-1', type: 'recording', status: 'error',
      filename: 'projects/voice/private-voice-memo.webm', mimeType: 'audio/webm',
      uploadEmbedId: 'uploaded-1', s3Files: { original: { s3_key: 'private/audio', size_bytes: 7 } },
      s3BaseUrl: 'https://files.example.test', aesKey: 'aes-key', aesNonce: 'nonce',
      vaultWrappedAesKey: 'wrapped-key', uploadError: 'Prior error',
    };
    const doc = {
      descendants(callback: (node: { type: { name: string }; attrs: Record<string, unknown> }, pos: number) => boolean) {
        callback({ type: { name: 'embed' }, attrs }, 1);
      },
    };
    const transaction = {
      setNodeMarkup(_pos: number, _type: unknown, updated: Record<string, unknown>) {
        attrs = updated;
        return this;
      },
    };
    const editor = {
      state: { doc },
      view: { state: { doc, tr: transaction }, dispatch: vi.fn() },
    } as unknown as Editor;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({
      success: true,
      data: { results: [{ id: 'recording-1', results: [{ transcript: 'hello', model: 'voxtral' }] }] },
    }));

    await retryTranscription(editor, 'recording-1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.example.test/v1/apps/audio/skills/transcribe');
    const body = JSON.parse(String(init?.body));
    expect(body.requests[0].filename).toBe('projects/voice/private-voice-memo.webm');
    expect(attrs).toMatchObject({
      filename: 'projects/voice/private-voice-memo.webm', status: 'finished', transcript: 'hello',
      model: 'voxtral', uploadError: null,
    });
    fetchMock.mockRestore();
  });
});
