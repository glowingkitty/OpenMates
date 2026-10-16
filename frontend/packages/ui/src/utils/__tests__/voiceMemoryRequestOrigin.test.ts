import { describe, expect, it } from 'vitest';
import { buildMemoryRequestMessage, parseMemoryRequest } from '../appMemoryRequests';

describe('voice memory permission origin', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.memories-and-focus,video-call.privacy
  it('retains voice transport origin in encrypted-history input without storing memory content', () => {
    const message = buildMemoryRequestMessage({ requestId: 'voice-request', userMessageId: 'user-one',
      requestedKeys: ['code-preferred_tech'], createdAt: 100, responseTransport: 'voice' });
    expect(parseMemoryRequest(message.content, message.message_id)).toMatchObject({
      response_transport: 'voice', request_id: 'voice-request', user_message_id: 'user-one',
    });
    expect(JSON.parse(message.content)).not.toHaveProperty('content');
    expect(JSON.parse(message.content)).not.toHaveProperty('settings_memories');
  });
});
