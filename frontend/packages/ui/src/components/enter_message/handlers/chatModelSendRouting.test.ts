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
