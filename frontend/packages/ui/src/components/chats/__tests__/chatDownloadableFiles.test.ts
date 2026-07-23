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
  it('extracts unique embed refs from full and truncated message content', () => {
    const refs = extractChatEmbedRefs([
      message('Open embed:code:one and embed:image:two'),
      message('Repeated embed:code:one', 'Truncated contains embed:pdf:three'),
    ]);

    expect(refs).toEqual(['embed:code:one', 'embed:image:two', 'embed:pdf:three']);
  });

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
});
