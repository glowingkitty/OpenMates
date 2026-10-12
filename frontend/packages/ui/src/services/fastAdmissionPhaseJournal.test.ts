import { describe, expect, it } from 'vitest';
import { retainOrReuseContextPhaseFrame } from './fastAdmissionPhaseJournal';

const identity = { chat_id: 'chat', turn_id: 'turn', message_id: 'message', request_id: 'request' };
const routing = { ...identity, phase: 'routing', context: { project_focus_candidates: [{ id: 'original' }] } };

describe('retained admission context', () => {
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('seals before the first delivery and replays the original after a crash', async () => {
    let journal: string | null = null;
    let commits = 0;
    const storage = {
      read: async () => journal,
      commit: async (sealed: string) => { commits++; journal ??= sealed; return journal; },
      seal: async (frame: Record<string, unknown>) => JSON.stringify(frame),
      open: async (sealed: string) => sealed,
    };
    const first = await retainOrReuseContextPhaseFrame({ identity, phase: 'routing', proposed: routing, ...storage });
    const replay = await retainOrReuseContextPhaseFrame({
      identity, phase: 'routing', proposed: { ...routing, context: { project_focus_candidates: [{ id: 'changed' }] } },
      ...storage,
    });
    expect(commits).toBe(1);
    expect(replay).toEqual(first);
    expect(replay).toEqual(routing);
  });

  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('refuses a stored phase from another turn', async () => {
    await expect(retainOrReuseContextPhaseFrame({
      identity, phase: 'routing', read: async () => JSON.stringify({ ...routing, turn_id: 'other' }),
      commit: async (value) => value, seal: async (frame) => JSON.stringify(frame), open: async (value) => value,
    })).rejects.toThrow('different turn identity');
  });
});
