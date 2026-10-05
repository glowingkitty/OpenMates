import { describe, expect, it } from 'vitest';
import { parseAgentContextEvent } from '../agentContextEvents';

describe('persisted agent context notices', () => {
  // contract-test: supporting surface=gui.web assertions=rules.transparency.applied-set
  it('requires count to match whole applied guides with exact revisions', () => {
    const receipt = { type: 'rules_loaded', count: 1, set_key: 'a'.repeat(64), rules: [
      { id: 'app:code:python', title: 'Python coding rules', source: 'app', revision: 'b'.repeat(64), body: '- One practice\n- Another practice' },
    ] };
    expect(parseAgentContextEvent(JSON.stringify(receipt))).toEqual(receipt);
    expect(parseAgentContextEvent({ ...receipt, count: 2 })).toBeNull();
    expect(parseAgentContextEvent({ ...receipt, rules: [receipt.rules[0], receipt.rules[0]], count: 2 })).toBeNull();
    expect(parseAgentContextEvent({ ...receipt, rules: [{ ...receipt.rules[0], revision: 'stale' }] })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.direction.reviewed-correction
  it('retains the exact delivered correction and refuses notices missing delivery identity', () => {
    const notice = { type: 'chat_direction_correction', delivery_id: 'sent-1', notice: 'Correction instruction was sent.', instruction: 'Exact\nprivate instruction.' };
    expect(parseAgentContextEvent(JSON.stringify(notice))).toEqual(notice);
    expect(parseAgentContextEvent({ ...notice, delivery_id: '' })).toBeNull();
    expect(parseAgentContextEvent({ ...notice, instruction: '' })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=focus-modes.project-authoring-click
  it('keeps click proposals as data and hides inspection-only authoring actions', () => {
    const recommendation = { type: 'project_authoring_recommendation', recommendation_id: 'r1', chat_id: 'c1', project_id: 'p1', kind: 'focus', action: 'create' };
    expect(parseAgentContextEvent(recommendation)).toEqual(recommendation);
    expect(parseAgentContextEvent({ ...recommendation, action: 'inspect' })).toBeNull();
  });
});
