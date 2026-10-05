import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { userProfile } from '../../stores/userProfile';

const cryptoMocks = vi.hoisted(() => ({
  decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
  decryptWithEmbedKey: vi.fn(async (value: string) => value.replace(/^sealed:/, '')),
  encryptWithEmbedKey: vi.fn(async (value: string) => `sealed:${value}`),
}));

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../cryptoService', () => cryptoMocks);
vi.mock('../projectService', () => ({ listProjects: vi.fn(async () => []) }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => null) } }));

import { getFreshUserPlan, getUserPlan, listUserPlans, peekUserPlans, updateUserPlan, type EncryptedUserPlanRecord } from '../userPlanService';

function planRecord(status: 'draft' | 'active' = 'draft', version = 1): EncryptedUserPlanRecord {
  return {
    plan_id: 'plan-1', encrypted_title: 'sealed:Private plan', encrypted_goal: 'sealed:Goal',
    status, version, primary_chat_id: 'chat-a', created_at: 1, updated_at: version,
    key_wrappers: [{ key_type: 'master', encrypted_plan_key: 'wrapped-key', created_at: 1 }],
  };
}

describe('userPlanService selected reads and query membership', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => userProfile.update((profile) => ({ ...profile, user_id: null })));

  // contract-test: direct surface=gui.web assertions=plans.content.client-encrypted
  it('reads and decrypts only the selected Plan by ID', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ plan: planRecord() }), { status: 200 }));
    const plan = await getUserPlan('plan-1');
    expect(plan.title).toBe('Private plan');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('https://api.test/v1/user-plans/plan-1');
    expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=plans.content.client-encrypted
  it('reuses exact Plan queries and moves a changed Plan between status filters', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'plan-cache-user' }));
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ plans: [planRecord()] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ plans: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ plan: planRecord('active', 2) }), { status: 200 }));
    const [plan] = await listUserPlans({ status: 'draft' });
    await listUserPlans({ status: 'draft' });
    expect((await getUserPlan('plan-1')).plan_id).toBe('plan-1');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await listUserPlans({ status: 'active' });
    await updateUserPlan(plan, { status: 'active' });
    expect(peekUserPlans({ status: 'draft' })).toEqual([]);
    expect(peekUserPlans({ status: 'active' })?.map((candidate) => candidate.plan_id)).toEqual(['plan-1']);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  // contract-test: supporting surface=gui.web assertions=plans.approval.revision-bound,chats.direction.context-assessment
  it('bypasses warm workspace records for the exact current approved Plan snapshot', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'fresh-plan-reader' }));
    const current = { ...planRecord('active', 9), approval_state: 'approved',
      submitted_revision_id: 'revision-9', approved_revision_id: 'revision-9' };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ plans: [planRecord('active', 1)] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ plan: current }), { status: 200 }));
    await listUserPlans({ status: 'active' });
    const fresh = await getFreshUserPlan('plan-1', 'team-a');
    expect(fresh.version).toBe(9);
    expect(fresh.approvalState).toBe('approved');
    expect(fresh.approvedRevisionId).toBe('revision-9');
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe('https://api.test/v1/user-plans/plan-1?team_id=team-a');
  });
});
