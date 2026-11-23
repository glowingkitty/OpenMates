import { describe, expect, it } from 'vitest';
import { applyChatModelSendRouting } from './chatModelSendRouting';

describe('saved chat model routing after immediate composer admission', () => {
  // contract-test: supporting surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope,message-input.send.ownership
  it('uses the restored exact preference for the submitted text', () => {
    expect(applyChatModelSendRouting('Explain this', 'google/gemini-2.5-pro'))
      .toBe('@ai-model:gemini-2.5-pro:google Explain this');
  });

  // contract-test: supporting surface=gui.web assertions=ai-model-routing.chat-selection.encrypted-user-chat-scope
  it('preserves explicit mentions and new-chat Auto', () => {
    expect(applyChatModelSendRouting('@best-model:code Explain this', 'google/gemini-2.5-pro'))
      .toBe('@best-model:code Explain this');
    expect(applyChatModelSendRouting('Explain this', 'auto')).toBe('Explain this');
  });
});

describe('model mention before an uploaded file (TASK-1610)', () => {
  const fence = '```json\n{"type": "image", "embed_id": "ea6cc310-1c03-4250-a642-a4051d99d6d1"}\n```';

  // contract-test: direct surface=gui.web assertions=chats.rendering.embed-references-never-raw
  it('keeps the embed fence at the start of its own line', () => {
    const sent = applyChatModelSendRouting(`${fence}\n\nTurn this into a patch`, 'google/gemini-3.8-flash');
    expect(sent).toBe(`@ai-model:gemini-3.8-flash:google\n\n${fence}\n\nTurn this into a patch`);
    expect(sent.split('\n')).toContain('```json');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.embed-references-never-raw
  it('separates other leading blocks and keeps plain text on one line', () => {
    expect(applyChatModelSendRouting('# Plan', 'google/gemini-3.8-flash')).toBe('@ai-model:gemini-3.8-flash:google\n\n# Plan');
    expect(applyChatModelSendRouting('- one', 'google/gemini-3.8-flash')).toBe('@ai-model:gemini-3.8-flash:google\n\n- one');
    expect(applyChatModelSendRouting('#hashtag idea', 'google/gemini-3.8-flash')).toBe('@ai-model:gemini-3.8-flash:google #hashtag idea');
  });
});
