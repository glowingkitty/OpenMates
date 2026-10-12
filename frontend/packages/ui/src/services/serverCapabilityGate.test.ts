import { describe, expect, it } from 'vitest';
import { ServerCapabilityGate } from './serverCapabilityGate';

describe('ServerCapabilityGate', () => {
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
  it('uses legacy send until both admission and context capabilities arrive', () => {
    const gate = new ServerCapabilityGate();
    expect(gate.supportsImmediateChatAdmission()).toBe(false);
    gate.accept({ capabilities: ['chat_turn_admit_v1'] });
    expect(gate.supportsImmediateChatAdmission()).toBe(false);
    gate.accept({ capabilities: ['chat_turn_admit_v1', 'chat_turn_context_v1'] });
    expect(gate.supportsImmediateChatAdmission()).toBe(true);
    expect(gate.supportsSelectionDetailsV2()).toBe(false);
    gate.accept({ capabilities: ['chat_turn_admit_v1', 'chat_turn_context_v1', 'chat_turn_context_selection_details_v2'] });
    expect(gate.supportsSelectionDetailsV2()).toBe(true);
    gate.reset();
    expect(gate.supportsImmediateChatAdmission()).toBe(false);
    expect(gate.supportsSelectionDetailsV2()).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
  it('rejects malformed capability announcements', () => {
    const gate = new ServerCapabilityGate();
    gate.accept({ capabilities: ['chat_turn_admit_v1', 'chat_turn_context_v1'] });
    gate.accept({ capabilities: ['chat_turn_admit_v1', 3] });
    expect(gate.supportsImmediateChatAdmission()).toBe(false);
  });
});
