import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ records: vi.fn(), plan: vi.fn(), tasks: vi.fn(), scope: vi.fn() }));
vi.mock('../userPlanService', () => ({ listFreshUserPlanRecords: mocks.records, getFreshUserPlan: mocks.plan }));
vi.mock('../userTaskService', () => ({ listUserTasks: mocks.tasks }));
vi.mock('../workspaceQueryCache', () => ({ getWorkspaceCacheIdentity: mocks.scope }));
import { acceptedPlanSummary, collectAcceptedPlanContext } from '../acceptedPlanContext';

const record = (id = 'plan-a', patch: Record<string, unknown> = {}) => ({ plan_id: id, version: 7,
  status: 'active', approval_state: 'approved', submitted_revision_id: 'revision-a',
  approved_revision_id: 'revision-a', primary_chat_id: 'chat-a', updated_at: 20, ...patch });
const plan = (id = 'plan-a', patch: Record<string, unknown> = {}) => ({ plan_id: id, version: 7,
  title: 'Approved outcome', goal: 'Fix duplicate posts', scopeIn: 'Message ordering',
  scopeOut: 'Unrelated UI changes', constraints: 'Preserve privacy', primaryChatId: 'chat-a',
  encrypted: record(id), ...patch }) as any;

describe('accepted Plan foreground context', () => {
  beforeEach(() => {
    vi.clearAllMocks(); mocks.scope.mockReturnValue('owner-team-epoch');
    mocks.records.mockResolvedValue([]); mocks.tasks.mockResolvedValue([]);
    mocks.plan.mockResolvedValue(plan());
  });

  // contract-test: supporting surface=gui.web assertions=chats.direction.context-assessment,plans.approval.revision-bound
  it('loads only an active current approved revision linked to this chat', async () => {
    mocks.records.mockResolvedValueOnce([record('draft', { status: 'draft' }),
      record('unapproved', { approval_state: 'unapproved' }), record('plan-a')]).mockResolvedValueOnce([]);
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a', teamId: 'team-a' })).toMatchObject({
      plan_id: 'plan-a', version: 7, approved_revision_id: 'revision-a',
      summary: expect.stringContaining('Out of scope: Unrelated UI changes'),
    });
    expect(mocks.plan).toHaveBeenCalledTimes(1);
    expect(mocks.plan).toHaveBeenCalledWith('plan-a', 'team-a');
    expect(mocks.records).toHaveBeenCalledWith({ chatId: 'chat-a', activeOnly: true, limit: 12 }, 'team-a');
    expect(mocks.records).toHaveBeenCalledWith({ chatId: 'chat-a', status: 'running_checks', limit: 12 }, 'team-a');
  });

  // contract-test: supporting surface=gui.web assertions=plans.approval.human-web-revision-bound,chats.direction.context-assessment
  it('omits changed approval, completed Plans and unrelated chat records before body loading', async () => {
    mocks.records.mockResolvedValueOnce([record('changed', { submitted_revision_id: 'new' }),
      record('finished', { status: 'completed' }), record('other', { primary_chat_id: 'other-chat' })]);
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toBeNull();
    expect(mocks.plan).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.direction.context-assessment,plans.tasks.only-execution-units
  it('uses only an open owned Task linked to this chat for Plan fallback', async () => {
    mocks.tasks.mockResolvedValue([
      { task_id: 'done-task', primaryChatId: 'chat-a', planId: 'completed-link', status: 'done', updatedAt: 40 },
      { task_id: 'other-task', primaryChatId: 'other-chat', planId: 'foreign-link', status: 'in_progress', updatedAt: 50 },
      { task_id: 'task-a', primaryChatId: 'chat-a', planId: 'plan-a', status: 'blocked', updatedAt: 20 },
    ]);
    mocks.plan.mockResolvedValue(plan('plan-a', { primaryChatId: 'plan-own-chat' }));
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toMatchObject({ plan_id: 'plan-a', linked_task_id: 'task-a' });
    expect(mocks.plan).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=plans.approval.revision-bound,chats.direction.context-assessment
  it('rechecks approval at the fresh selected read and omits revoked revisions', async () => {
    mocks.records.mockResolvedValueOnce([record()]);
    mocks.plan.mockResolvedValue(plan('plan-a', { encrypted: record('plan-a', { approval_state: 'unapproved' }) }));
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=plans.content.client-encrypted,chats.direction.context-assessment
  it('discards snapshots if account or Team scope changes during the selected read', async () => {
    mocks.records.mockResolvedValueOnce([record()]);
    mocks.plan.mockImplementation(async () => { mocks.scope.mockReturnValue('new-owner'); return plan(); });
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.direction.context-assessment
  it('bounds the summary while retaining both scope boundaries and constraints', () => {
    const source = plan('plan-a', { title: 't'.repeat(1_000), goal: 'g'.repeat(10_000),
      scopeIn: 'i'.repeat(5_000), scopeOut: 'o'.repeat(5_000), constraints: 'c'.repeat(5_000) });
    const summary = acceptedPlanSummary(source);
    expect(summary.length).toBeLessThanOrEqual(4_000);
    expect(summary).toContain('In scope:'); expect(summary).toContain('Out of scope:');
    expect(summary).toContain('Constraints:'); expect(source.goal.length).toBe(10_000);
  });

  // contract-test: supporting surface=gui.web assertions=chats.direction.context-assessment
  it('keeps missing Plans and unavailable services optional for ordinary sending', async () => {
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toBeNull();
    mocks.records.mockRejectedValue(new Error('Unavailable'));
    mocks.tasks.mockRejectedValue(new Error('Unavailable'));
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toBeNull();
    expect(mocks.plan).not.toHaveBeenCalled();
    mocks.scope.mockReturnValue(null);
    mocks.records.mockClear();
    expect(await collectAcceptedPlanContext({ chatId: 'chat-a' })).toBeNull();
    expect(mocks.records).not.toHaveBeenCalled();
  });
});
