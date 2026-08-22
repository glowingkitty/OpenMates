/**
 * Chat settings file helper coverage anchor.
 *
 * The broader downloadable-file regression suite lives in
 * chatDownloadableFiles.test.ts. This filename keeps the deterministic session
 * coverage checker linked to chatSettingsFiles.ts.
 */

import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/embedStore', () => ({
  embedStore: {
    getUploadedFilesByContentRefs: vi.fn(),
    get: vi.fn(),
  },
}));

import { extractChatEmbedRefs } from '../chatSettingsFiles';

describe('chatSettingsFiles helper coverage', () => {
  // contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity
  it('extracts dotted inline embed refs for files tab resolution', () => {
    const refs = extractChatEmbedRefs([
      {
        message_id: 'message-1',
        role: 'assistant',
        content: 'Open [the file](embed:code.example-file.v1)',
        created_at: Date.now(),
      } as never,
    ]);

    expect(refs).toEqual(['embed:code.example-file.v1']);
  });
});
