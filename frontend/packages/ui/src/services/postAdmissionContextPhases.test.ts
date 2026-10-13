import { describe, expect, it, vi } from 'vitest';
import { isSelectionDetailsV2Routing, publishSelectionDetailsPhases, publishContextPreparationFailure, retainFreshRoutingPhase } from './postAdmissionContextPhases';

describe('post-admission selection details v2', () => {
  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance
  it('publishes routing without waiting for a slow Task catalog', async () => {
    let finishTasks!: (value: string) => void;
    const tasks = new Promise<string>((resolve) => { finishTasks = resolve; });
    const sent: string[] = [];
    const publish = publishSelectionDetailsPhases({
      routing: async () => 'projects-ready',
      details: () => tasks,
      send: async (phase, frame) => { sent.push(`${phase}:${frame}`); },
      isCurrent: () => true,
    });
    await vi.waitFor(() => expect(sent).toEqual(['routing:projects-ready']));
    finishTasks('tasks-ready');
    await publish;
    expect(sent).toEqual(['routing:projects-ready', 'details:tasks-ready']);
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance
  it('never publishes an empty routing phase when Project discovery fails', async () => {
    const send = vi.fn();
    await expect(publishSelectionDetailsPhases({
      routing: async () => { throw new Error('Project discovery failed'); },
      details: async () => 'tasks-ready', send, isCurrent: () => true,
    })).rejects.toThrow('Project discovery failed');
    expect(send).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('does not send details after workspace ownership changes', async () => {
    let current = true;
    const sent: string[] = [];
    await publishSelectionDetailsPhases({
      routing: async () => 'projects-ready',
      details: async () => 'tasks-ready',
      send: async (phase) => { sent.push(phase); current = false; },
      isCurrent: () => current,
    });
    expect(sent).toEqual(['routing']);
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,chats.send.immediate-admission
  it('discards a sealed phase when Project metadata mutates during retention', async () => {
    let releaseSeal!: (frame: string) => void;
    const sealing = new Promise<string>((resolve) => { releaseSeal = resolve; });
    let mutationVersion = 1;
    let retained: string | null = null;
    const sent = vi.fn();
    const publish = publishSelectionDetailsPhases({
      routing: () => retainFreshRoutingPhase({
        mutationVersion, getMutationVersion: () => mutationVersion, isCurrent: () => true,
        retain: async () => { retained = await sealing; return retained; },
        discard: async () => { retained = null; },
      }),
      details: async () => 'details', send: sent, isCurrent: () => true,
    });
    mutationVersion = 2;
    releaseSeal('sealed-stale-candidates');
    await expect(publish).rejects.toThrow('routing scope changed');
    expect(retained).toBeNull();
    expect(sent).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent,message-input.send.ownership
  it('leaves a sealed journal for a successor when the old attempt loses ownership', async () => {
    let releaseSeal!: (value: string) => void;
    const sealing = new Promise<string>((resolve) => { releaseSeal = resolve; });
    let releaseOld!: () => void;
    const oldPaused = new Promise<void>((resolve) => { releaseOld = resolve; });
    let journal: string | null = null;
    let oldOwnsTurn = true;
    const discard = vi.fn(async () => { journal = null; });
    const oldSend = vi.fn();
    const oldAttempt = publishSelectionDetailsPhases({
      routing: () => retainFreshRoutingPhase({
        mutationVersion: 1, getMutationVersion: () => 2, isCurrent: () => oldOwnsTurn,
        retain: async () => { journal = await sealing; await oldPaused; return journal; },
        discard,
      }),
      details: async () => 'details', send: oldSend, isCurrent: () => oldOwnsTurn,
    });
    releaseSeal('exact-sealed-routing');
    await vi.waitFor(() => expect(journal).toBe('exact-sealed-routing'));
    oldOwnsTurn = false;
    const successorFrame = journal;
    const successorSent = [successorFrame];
    releaseOld();
    await oldAttempt;
    expect(successorSent).toEqual(['exact-sealed-routing']);
    expect(journal).toBe(successorFrame);
    expect(discard).not.toHaveBeenCalled();
    expect(oldSend).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance
  it('replays retained legacy routing with its original field placement', () => {
    expect(isSelectionDetailsV2Routing({ context: { project_focus_candidates: [] } })).toBe(true);
    expect(isSelectionDetailsV2Routing({ context: {
      project_focus_candidates: [], related_task_candidates: [], project_focus_catalog: [],
    } })).toBe(false);
  });
});

describe('admitted context failure', () => {
  const identity = { chat_id: 'chat', turn_id: 'turn', message_id: 'message', request_id: 'request' };

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance,message-input.send.ownership
  it('sends only exact turn identity and a generic failure category', async () => {
    const send = vi.fn(async () => undefined);
    await publishContextPreparationFailure({ identity, isCurrent: () => true, supportsFailure: () => true, send });
    expect(send).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledWith({ ...identity, reason: 'context_preparation_failed' });
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it.each(['owner', 'capability'])('does not send after %s becomes unavailable', async (missing) => {
    const send = vi.fn();
    await publishContextPreparationFailure({ identity, isCurrent: () => missing !== 'owner',
      supportsFailure: () => missing !== 'capability', send });
    expect(send).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
  it('does not replace a failure with an empty successful context phase', async () => {
    const send = vi.fn(async () => { throw new Error('disconnected'); });
    await expect(publishContextPreparationFailure({ identity, isCurrent: () => true,
      supportsFailure: () => true, send })).rejects.toThrow('disconnected');
    expect(send.mock.calls[0][0]).not.toHaveProperty('context');
    expect(send.mock.calls[0][0]).not.toHaveProperty('phase');
  });
});
