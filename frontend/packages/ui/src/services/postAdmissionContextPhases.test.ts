import { describe, expect, it, vi } from 'vitest';
import { isSelectionDetailsV2Routing, publishSelectionDetailsPhases } from './postAdmissionContextPhases';

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
