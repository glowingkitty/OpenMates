import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const scope = { workspace: 'account-a|personal', teamId: null as string | null,
    teamEpoch: 1, authenticated: true };
  return { scope, read: vi.fn(), phases: vi.fn(),
    store: <T>(read: () => T) => ({ subscribe(run: (value: T) => void) {
      run(read()); return () => undefined;
    } }),
  };
});
vi.mock('../../stores/authStore', () => ({ authStore: mocks.store(() => ({ isAuthenticated: mocks.scope.authenticated })) }));
vi.mock('../../stores/teamStore', () => ({ getActiveTeamContextSnapshot: () => ({
  teamId: mocks.scope.teamId, epoch: mocks.scope.teamEpoch,
}) }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: () => mocks.scope.workspace }));
vi.mock('../projectService', () => ({ listFreshProjectsForSend: mocks.read }));

import { beginFreshProjectRoutingForSend, forgetFreshProjectRoutingForSend,
  reserveFreshProjectRoutingForSend } from '../earlyProjectRoutingForSend';

function pending<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const input = { chatId: 'first-chat', messageId: 'first-message',
  draftChatId: 'first-chat', recordPhase: mocks.phases };

describe('click-time fresh Project read', () => {
  beforeEach(() => {
    forgetFreshProjectRoutingForSend(input.messageId);
    mocks.scope.workspace = 'account-a|personal';
    mocks.scope.teamId = null;
    mocks.scope.teamEpoch += 1;
    mocks.scope.authenticated = true;
    mocks.read.mockReset();
    mocks.phases.mockReset();
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.selection-after-acceptance
  it('starts at click and hands the same result to only the exact message', async () => {
    const fresh = pending<{ projects: unknown[]; mutationVersion: number }>();
    mocks.read.mockReturnValue(fresh.promise);
    beginFreshProjectRoutingForSend(input);
    expect(mocks.read).toHaveBeenCalledOnce();
    expect(mocks.phases).toHaveBeenCalledWith('project_read_begin');
    expect(reserveFreshProjectRoutingForSend('another-chat', input.messageId)).toBeNull();
    expect(reserveFreshProjectRoutingForSend(input.chatId, input.messageId)).toBeNull();
    beginFreshProjectRoutingForSend(input);
    const consumeAfterAck = reserveFreshProjectRoutingForSend(input.chatId, input.messageId);
    forgetFreshProjectRoutingForSend(input.messageId);
    const accepted = consumeAfterAck?.();
    fresh.resolve({ projects: [{ project_id: 'project-1' }], mutationVersion: 4 });
    await expect(accepted).resolves.toEqual({ projects: [{ project_id: 'project-1' }], mutationVersion: 4 });
    expect(reserveFreshProjectRoutingForSend(input.chatId, input.messageId)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission
  it('preserves a failed fresh read for the admitted failure path', async () => {
    const fresh = pending<{ projects: unknown[]; mutationVersion: number }>();
    mocks.read.mockReturnValue(fresh.promise);
    beginFreshProjectRoutingForSend(input);
    fresh.reject(new Error('Project discovery failed'));
    await Promise.resolve();
    const accepted = reserveFreshProjectRoutingForSend(input.chatId, input.messageId)?.();
    await expect(accepted).rejects.toThrow('Project discovery failed');
    expect(mocks.phases).toHaveBeenCalledWith('project_read_failed');
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it.each(['account', 'team', 'team epoch', 'logout'])('drops results after %s changes', async (changed) => {
    mocks.read.mockResolvedValue({ projects: [], mutationVersion: 1 });
    beginFreshProjectRoutingForSend(input);
    const consumeAfterAck = reserveFreshProjectRoutingForSend(input.chatId, input.messageId);
    if (changed === 'account') mocks.scope.workspace = 'account-b|personal';
    if (changed === 'team') mocks.scope.teamId = 'team-b';
    if (changed === 'team epoch') mocks.scope.teamEpoch += 1;
    if (changed === 'logout') mocks.scope.authenticated = false;
    expect(consumeAfterAck?.()).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('records a content-free scope reason when a click cannot start discovery', () => {
    mocks.scope.workspace = '';
    beginFreshProjectRoutingForSend(input);
    expect(mocks.phases).toHaveBeenCalledWith('project_read_gate_scope_unavailable');
    expect(mocks.read).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it('drops cancelled sends and rejects a changed draft/chat identity', () => {
    mocks.read.mockResolvedValue({ projects: [], mutationVersion: 1 });
    beginFreshProjectRoutingForSend(input);
    forgetFreshProjectRoutingForSend(input.messageId);
    expect(reserveFreshProjectRoutingForSend(input.chatId, input.messageId)).toBeNull();
    beginFreshProjectRoutingForSend({ ...input, draftChatId: 'other-draft' });
    expect(mocks.phases).toHaveBeenCalledWith('project_read_gate_draft_mismatch');
    expect(mocks.read).toHaveBeenCalledOnce();
    expect(reserveFreshProjectRoutingForSend(input.chatId, input.messageId)).toBeNull();
  });
});
