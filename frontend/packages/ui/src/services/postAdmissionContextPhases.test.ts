import { describe, expect, it, vi } from 'vitest';
import { isSelectionDetailsV2Routing, publishSelectionDetailsPhases, publishContextPreparationFailure } from './postAdmissionContextPhases';

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
