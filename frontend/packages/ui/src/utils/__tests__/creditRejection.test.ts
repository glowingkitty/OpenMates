import { describe, expect, it } from 'vitest';
import { hasCreditRejectionEvidence, isCreditRejection } from '../creditRejection';

describe('credit rejection classification', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.lifecycle.recovery-and-billing
  it('never treats lifecycle events or ordinary user prompts as a credit rejection', () => {
    for (const status of ['synced', 'delivered', 'waiting_for_user']) {
      expect(isCreditRejection({ role: 'system', status, content: JSON.stringify({ type: 'voice_call', action: 'ended' }) })).toBe(false);
      expect(isCreditRejection({ role: 'assistant', status, content: 'Which city?' })).toBe(false);
      expect(isCreditRejection({ role: 'assistant', status, content: 'Not enough credits to buy that item.' })).toBe(false);
    }
    expect(isCreditRejection({ role: 'user', status: 'waiting_for_user', content: 'Explain insufficient credits' })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.call-events,video-call.lifecycle.recovery-and-billing
  it('retains explicit and persisted rejection evidence and its exact linked user row', () => {
    const rejection = { chat_id: 'chat', role: 'system', user_message_id: 'user', content: 'Not enough credits', status: 'synced' };
    expect(hasCreditRejectionEvidence({ role: 'system', rejection_reason: 'insufficient_credits' })).toBe(true);
    expect(isCreditRejection(rejection)).toBe(true);
    const user = { chat_id: 'chat', role: 'user', message_id: 'user', status: 'waiting_for_user' };
    expect(isCreditRejection(user, [rejection])).toBe(true);
    expect(isCreditRejection({ ...user, message_id: 'other' }, [rejection])).toBe(false);
    expect(isCreditRejection({ ...user, chat_id: 'other' }, [rejection])).toBe(false);
  });
});
