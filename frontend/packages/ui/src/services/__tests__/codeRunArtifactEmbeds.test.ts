/**
 * Code Run child embed persistence tests.
 *
 * Verifies generated artifact children inherit the parent row's encrypted
 * persistence indexes so message cleanup and chat sync retain the relationship.
 * Contract: feature.app-skill.code-run@1.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockHandleSendEmbedData = vi.hoisted(() => vi.fn());
const mockSendStoreEmbed = vi.hoisted(() => vi.fn());
const mockGetRawEntry = vi.hoisted(() => vi.fn());
const mockUpdateChildEmbedIds = vi.hoisted(() => vi.fn());

vi.mock('../chatSyncService', () => ({ chatSyncService: {} }));
vi.mock('../chatSyncServiceHandlersAI', () => ({
  handleSendEmbedDataImpl: mockHandleSendEmbedData,
}));
vi.mock('../chatSyncServiceSenders', () => ({
  sendStoreEmbedImpl: mockSendStoreEmbed,
}));
vi.mock('../embedStore', () => ({
  embedStore: {
    getRawEntry: mockGetRawEntry,
    updateChildEmbedIds: mockUpdateChildEmbedIds,
  },
}));

import { materializeCodeRunArtifactChildren } from '../codeRunArtifactEmbeds';

describe('materializeCodeRunArtifactChildren', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetRawEntry.mockResolvedValue({
      hashed_chat_id: 'parent-chat-hash',
      hashed_message_id: 'parent-message-hash',
      hashed_user_id: 'parent-user-hash',
    });
    mockUpdateChildEmbedIds.mockResolvedValue({ embed_id: 'parent-1' });
  });

  // contract-test: direct surface=gui.web assertions=code-run.artifacts.chat-bound-versioned
  it('inherits parent persistence indexes for every child row', async () => {
    await materializeCodeRunArtifactChildren({
      artifacts: [{
        path: 'outputs/result.txt',
        normalized_path: 'outputs/result.txt',
        mime_type: 'text/plain',
        size_bytes: 2,
        status: 'captured',
        asset_id: 'parent-1',
        variant: 'result-txt',
      }, {
        path: 'outputs/chart.png',
        normalized_path: 'outputs/chart.png',
        mime_type: 'image/png',
        size_bytes: 4,
        status: 'captured',
        asset_id: 'parent-1',
        variant: 'chart-png',
      }],
      parentEmbedId: 'parent-1',
      chatId: 'chat-1',
      sourceExecutionId: 'execution-1',
    });

    expect(mockHandleSendEmbedData).toHaveBeenCalledTimes(2);
    for (const [, payload, indexes] of mockHandleSendEmbedData.mock.calls) {
      expect(payload).toEqual(expect.objectContaining({
        parent_embed_id: 'parent-1',
        message_id: 'parent-1',
      }));
      expect(payload).not.toHaveProperty('user_id');
      expect(indexes).toEqual({
        hashed_chat_id: 'parent-chat-hash',
        hashed_message_id: 'parent-message-hash',
        hashed_user_id: 'parent-user-hash',
      });
    }
    expect(mockUpdateChildEmbedIds).toHaveBeenCalledWith(
      'parent-1',
      [expect.any(String), expect.any(String)],
    );
  });

  // contract-test: supporting surface=gui.web assertions=code-run.artifacts.chat-bound-versioned
  it('refuses to create orphan-prone children when parent indexes are unavailable', async () => {
    mockGetRawEntry.mockResolvedValue({ hashed_chat_id: 'parent-chat-hash' });

    await expect(materializeCodeRunArtifactChildren({
      artifacts: [],
      parentEmbedId: 'parent-1',
      chatId: 'chat-1',
      sourceExecutionId: 'execution-1',
    })).rejects.toThrow('Parent embed parent-1 is missing persistence indexes');
    expect(mockHandleSendEmbedData).not.toHaveBeenCalled();
  });
});
