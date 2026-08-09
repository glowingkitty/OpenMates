/**
 * Chat settings downloadable-files regression tests.
 *
 * These tests pin the local-first Files tab helper contract: scan chat message
 * text for embed references, resolve them through the existing embed store, and
 * expose only entries with an existing downloadable/exportable type.
 */

import { describe, expect, it, vi } from 'vitest';
import type { Message } from '../../../types/chat';

const uploadedFiles = vi.hoisted(() => ({
  getUploadedFilesByContentRefs: vi.fn(),
}));

vi.mock('../../../services/embedStore', () => ({
  embedStore: uploadedFiles,
}));

import { extractChatEmbedRefs, loadChatFileRows } from '../chatSettingsFiles';

function message(content: string, truncatedContent = ''): Message {
  return {
    message_id: crypto.randomUUID(),
    role: 'assistant',
    content,
    truncated_content: truncatedContent,
    created_at: Date.now(),
  } as Message;
}

describe('chat settings downloadable files', () => {
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it('extracts unique embed refs from full and truncated message content', () => {
    const refs = extractChatEmbedRefs([
      message('Open embed:code:one and embed:image:two'),
      message('Repeated embed:code:one', 'Truncated contains embed:pdf:three'),
      message('```json\n{"type":"audio-recording","embed_id":"voice-note-1"}\n```'),
    ]);

    expect(refs).toEqual(['embed:code:one', 'embed:image:two', 'embed:pdf:three', 'embed:voice-note-1']);
  });

  // contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity
  it('lists audio recording embeds as downloadable files', async () => {
    uploadedFiles.getUploadedFilesByContentRefs.mockResolvedValueOnce([
      {
        embedId: 'voice-note-1',
        contentRef: 'embed:voice-note-1',
        title: 'Audio recording',
        subtitle: '00:08',
        type: 'audio-recording',
        nodeType: 'recording',
        iconName: 'audio',
        createdAt: 1,
        updatedAt: 1,
      },
    ]);

    const rows = await loadChatFileRows([message('```json\n{"type":"audio-recording","embed_id":"voice-note-1"}\n```')]);

    expect(uploadedFiles.getUploadedFilesByContentRefs).toHaveBeenCalledWith(['embed:voice-note-1']);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ contentRef: 'embed:voice-note-1', iconName: 'audio', metadata: '00:08' });
  });

  // contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity
  it('keeps only downloadable file rows and preserves useful metadata', async () => {
    uploadedFiles.getUploadedFilesByContentRefs.mockResolvedValueOnce([
      {
        embedId: 'code-1',
        contentRef: 'embed:code:one',
        title: 'Whisper transcript parser',
        subtitle: '42 lines | TypeScript',
        type: 'code',
        nodeType: 'code',
        iconName: 'code',
        createdAt: 1,
        updatedAt: 1,
      },
      {
        embedId: 'search-1',
        contentRef: 'embed:web:search',
        title: 'Search results',
        subtitle: '5 results',
        type: 'web',
        nodeType: 'web',
        iconName: 'web',
        createdAt: 2,
        updatedAt: 2,
      },
      {
        embedId: 'sheet-1',
        contentRef: 'embed:sheets:budget',
        title: 'Budget sheet',
        subtitle: '',
        type: 'spreadsheet',
        nodeType: 'sheets',
        iconName: 'sheets',
        createdAt: 3,
        updatedAt: 3,
      },
    ]);

    const rows = await loadChatFileRows([message('Files embed:code:one embed:web:search embed:sheets:budget')]);

    expect(uploadedFiles.getUploadedFilesByContentRefs).toHaveBeenCalledWith([
      'embed:code:one',
      'embed:web:search',
      'embed:sheets:budget',
    ]);
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.contentRef)).toEqual(['embed:code:one', 'embed:sheets:budget']);
    expect(rows[0].metadata).toBe('42 lines | TypeScript');
    expect(rows[1].metadata).toBe('spreadsheet');
  });

  // contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity
  it('does not list generic embed UUID fallbacks as downloadable files', async () => {
    uploadedFiles.getUploadedFilesByContentRefs.mockResolvedValueOnce([
      {
        embedId: '679deba7-2815-4d8e-9c3d-8ade97ea5dce',
        contentRef: 'embed:679deba7-2815-4d8e-9c3d-8ade97ea5dce',
        title: '679deba7-2815-4d8e-9c3d-8ade97ea5dce',
        subtitle: 'Uploaded file',
        type: 'web-website',
        nodeType: 'docs-doc',
        iconName: 'document',
        createdAt: 1,
        updatedAt: 1,
      },
    ]);

    const rows = await loadChatFileRows([
      message('[iPhone source](embed:679deba7-2815-4d8e-9c3d-8ade97ea5dce)'),
    ]);

    expect(rows).toEqual([]);
  });
});
