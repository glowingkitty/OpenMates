/**
 * Code Run parent embed linkage tests.
 *
 * Verifies adding generated artifact children retains parent routing metadata
 * and encrypted persistence indexes used by sync and message cleanup.
 * Contract: feature.app-skill.code-run@1.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EmbedStore } from '../embedStore';

describe('Code Run parent embed linkage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=code-run.artifacts.chat-bound-versioned,code-run.artifacts.parent-child-navigation
  it('preserves parent metadata and persistence indexes while adding child IDs', async () => {
    const store = new EmbedStore();
    await store.putEncrypted(
      'embed:code-parent',
      {
        embed_id: 'code-parent',
        encrypted_type: '<encrypted-type>',
        encrypted_content: '<encrypted-content>',
        status: 'finished',
        hashed_chat_id: 'hashed-chat',
        hashed_message_id: 'hashed-message',
        hashed_user_id: 'hashed-user',
        createdAt: 1000,
        updatedAt: 1000,
      },
      'code-code',
      undefined,
      { app_id: 'code', skill_id: 'run-code' },
      { skipMetadataExtraction: true },
    );

    const payload = await store.updateChildEmbedIds('code-parent', ['child-b', 'child-a']);

    await expect(store.getRawEntry('embed:code-parent')).resolves.toMatchObject({
      app_id: 'code',
      skill_id: 'run-code',
      embed_ids: ['child-b', 'child-a'],
      hashed_chat_id: 'hashed-chat',
      hashed_message_id: 'hashed-message',
      hashed_user_id: 'hashed-user',
    });
    expect(payload).toMatchObject({
      embed_id: 'code-parent',
      embed_ids: ['child-b', 'child-a'],
      hashed_chat_id: 'hashed-chat',
      hashed_message_id: 'hashed-message',
      hashed_user_id: 'hashed-user',
    });
  });
});
