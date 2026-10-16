// frontend/packages/ui/src/services/__tests__/userTaskService.test.ts
//
// Browser Tasks privacy contract coverage for external chat bindings and
// blocked-reason explanations. The API receives opaque ciphertext, safe
// provider metadata, and an owner-scoped blind index only.
//
// Specification: specifications/features/tasks/specification.yml

import { webcrypto } from 'node:crypto';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { userProfile } from '../../stores/userProfile';
import { setActiveTeamContext } from '../../stores/teamStore';
import { computeSHA256 } from '../../message_parsing/utils';

const masterKey = vi.hoisted(() => ({ value: null as CryptoKey | null }));
const cryptoMocks = vi.hoisted(() => ({
  decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
  decryptWithEmbedKey: vi.fn(async (value: string) => value.startsWith('sealed:') ? atob(value.slice('sealed:'.length)) : ''),
  encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-task-key'),
  encryptWithEmbedKey: vi.fn(async (value: string) => `sealed:${btoa(value)}`),
  generateEmbedKey: vi.fn(() => new Uint8Array([1, 2, 3, 4])),
  unwrapEmbedKeyWithChatKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
  unwrapEmbedKeyWithEmbedKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
  wrapEmbedKeyWithChatKey: vi.fn(async () => 'wrapped-chat-key'),
}));

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../cryptoService', () => cryptoMocks);
vi.mock('../cryptoKeyStorage', () => ({ getMasterKey: () => masterKey.value }));
vi.mock('../projectService', () => ({ listProjects: vi.fn(async () => []) }));
vi.mock('../teamService', () => ({ getTeamKey: vi.fn(async () => new Uint8Array([5, 6, 7, 8])) }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([5, 6, 7, 8])) } }));

import {
  blockUserTask,
  canSubmitUserTaskActivity,
  createUserTaskActivity,
  createUserTask,
  createTaskMoveSequencer,
  deleteUserTask,
  deleteUserTaskActivity,
  externalChatLookupHash,
  getTaskAssignmentEligibility,
  getUserTask,
  listUserTaskActivity,
  listUserTasks,
  listTaskBoardItems,
  peekUserTasks,
  prependTaskBoardItem,
  reorderUserTasks,
  startUserTaskWithAI,
  updateUserTask,
  type EncryptedUserTaskRecord,
  type UserTaskViewModel,
} from '../userTaskService';

const externalChat = { provider: 'codex' as const, id: 'ses-private-session', title: 'Private external title' };

function taskResponse(overrides: Record<string, unknown> = {}): EncryptedUserTaskRecord {
  return {
    task_id: 'task-server-id',
    encrypted_task_key: 'wrapped-task-key',
    encrypted_title: 'sealed:UHJpdmF0ZSB0YXNrIHRpdGxl',
    encrypted_description: 'sealed:',
    encrypted_tags: 'sealed:W10=',
    status: 'blocked',
    assignee_type: 'user',
    primary_chat_id: null,
    version: 1,
    created_at: 1,
    updated_at: 1,
    ...overrides,
  } as EncryptedUserTaskRecord;
}

function taskViewModel(): UserTaskViewModel {
  return {
    task_id: 'task-server-id', title: 'Private task title', description: '', tags: [], latestInstruction: '',
    status: 'blocked', assigneeType: 'user', assigneeIdentity: null, primaryChatId: null, externalChat: null,
    linkedProjectIds: [], planId: null, dueAt: null, priority: 0, position: 0, version: 1,
    createdAt: 1, updatedAt: 1, blockedReasonCode: 'missing_credentials', blockedReason: '', aiExecutionState: null,
    encrypted: taskResponse(),
  };
}

describe('userTaskService external chat privacy', () => {
  beforeAll(async () => {
    vi.stubGlobal('crypto', webcrypto);
    masterKey.value = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(7), 'AES-GCM', true, ['encrypt', 'decrypt']);
  });

  beforeEach(() => {
    vi.clearAllMocks();
    setActiveTeamContext(null);
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001');
  });

  afterEach(() => {
    setActiveTeamContext(null);
    userProfile.update((profile) => ({ ...profile, user_id: null }));
  });

  // contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.surface.semantic-parity
  it('creates and lists tasks in the active Team with a Team-wrapped key', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'team-task-user' }));
    setActiveTeamContext({ team_id: 'team-a' } as Parameters<typeof setActiveTeamContext>[0]);
    const teamHash = await computeSHA256('team-a');
    const teamWrapper = { key_type: 'team', hashed_team_id: teamHash, team_key_epoch: 1,
      encrypted_task_key: 'wrapped-chat-key', created_at: 1 };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({ hashed_team_id: teamHash, encrypted_task_key: 'wrapped-chat-key' }) }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ hashed_team_id: teamHash,
        encrypted_task_key: null, key_wrappers: [teamWrapper] })], eligible_external_ai: [] }), { status: 200 }));
    const created = await createUserTask({ title: 'Team task', teamId: 'team-a' });
    const createBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(createBody.team_id).toBe('team-a');
    expect(createBody.encrypted_task_key).toBe('wrapped-chat-key');
    expect(createBody.key_wrappers).toEqual(expect.arrayContaining([
      expect.objectContaining({ key_type: 'team', hashed_team_id: teamHash, team_key_epoch: 1 }),
    ]));
    expect(createBody.key_wrappers).not.toEqual(expect.arrayContaining([expect.objectContaining({ key_type: 'master' })]));
    expect(cryptoMocks.encryptChatKeyWithMasterKey).not.toHaveBeenCalled();
    expect(created.teamId).toBe('team-a');
    const listed = await listUserTasks({ teamId: 'team-a' });
    expect(listed[0]?.teamId).toBe('team-a');
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain('team_id=team-a');
    expect(cryptoMocks.unwrapEmbedKeyWithEmbedKey).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.key-wrappers.context-scoped
  it('fails closed for Team rows without a valid Team key wrapper', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'team-task-user' }));
    setActiveTeamContext({ team_id: 'team-a' } as Parameters<typeof setActiveTeamContext>[0]);
    const teamHash = await computeSHA256('team-a');
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
      tasks: [taskResponse({ hashed_team_id: teamHash, encrypted_task_key: 'legacy-personal-key', key_wrappers: [] })],
      eligible_external_ai: [],
    }), { status: 200 }));
    await expect(listUserTasks({ teamId: 'team-a' })).rejects.toThrow(/no unique Team key wrapper/);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('team_id=team-a');
    expect(cryptoMocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=tasks.key-wrappers.context-scoped
  it('loads a Team wrapper for a cold Task detail read', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'team-task-user' }));
    setActiveTeamContext({ team_id: 'team-detail' } as Parameters<typeof setActiveTeamContext>[0]);
    const teamHash = await computeSHA256('team-detail');
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({
        hashed_team_id: teamHash, encrypted_task_key: null,
      }) }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ key_wrappers: [{
        key_type: 'team', hashed_team_id: teamHash, team_key_epoch: 1,
        encrypted_task_key: 'wrapped-chat-key', created_at: 1,
      }] }), { status: 200 }));
    const task = await getUserTask('task-server-id');
    expect(task.teamId).toBe('team-detail');
    expect(task.title).toBe('Private task title');
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('team_id=team-detail');
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain('/key-wrappers?team_id=team-detail');
    expect(cryptoMocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=tasks.lifecycle.visible
  it('waits for a block reorder before starting an immediate unblock of the same Task', async () => {
    const runMove = createTaskMoveSequencer();
    const actions: string[] = [];
    let finishBlockReorder!: () => void;
    const blockReorder = new Promise<void>((resolve) => { finishBlockReorder = resolve; });

    const block = runMove('task-a', async () => {
      actions.push('block response');
      await blockReorder;
      actions.push('block reorder');
    });
    const unblock = runMove('task-a', async () => { actions.push('unblock request'); });
    const otherTask = runMove('task-b', async () => { actions.push('other task request'); });

    await otherTask;
    expect(actions).toEqual(['block response', 'other task request']);
    finishBlockReorder();
    await Promise.all([block, unblock]);
    expect(actions).toEqual(['block response', 'other task request', 'block reorder', 'unblock request']);
  });

  // contract-test: direct surface=gui.web assertions=tasks.surface.semantic-parity,tasks.content.client-encrypted
  it('reuses an exact chat query and its selected entity without decrypting it again', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'cache-test-user' }));
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ primary_chat_id: 'chat-a' })], eligible_external_ai: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [], eligible_external_ai: [] }), { status: 200 }));
    expect((await listUserTasks({ chatId: 'chat-a' })).map((task) => task.task_id)).toEqual(['task-server-id']);
    await listUserTasks({ chatId: 'chat-a' });
    expect((await getUserTask('task-server-id')).title).toBe('Private task title');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(1);
    expect(await listUserTasks({ chatId: 'chat-b' })).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: direct surface=gui.web assertions=tasks.surface.semantic-parity
  it('does not resurrect a deleted task from an older in-flight list response', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'cache-race-user' }));
    let releaseList: ((response: Response) => void) | undefined;
    const listResponse = new Promise<Response>((resolve) => { releaseList = resolve; });
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (init?.method === 'DELETE') return new Response(JSON.stringify({ deleted: true }), { status: 200 });
      if (String(input).includes('chat_id=chat-a')) return listResponse;
      throw new Error(`Unexpected request ${String(input)}`);
    });
    const pending = listUserTasks({ chatId: 'chat-a' });
    await deleteUserTask(taskViewModel());
    releaseList?.(new Response(JSON.stringify({ tasks: [taskResponse({ primary_chat_id: 'chat-a' })], eligible_external_ai: [] }), { status: 200 }));
    await expect(pending).rejects.toThrow('superseded');
    expect(peekUserTasks({ chatId: 'chat-a' })).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=tasks.surface.semantic-parity
  it('uses a newer board record when an older selected entity is cached', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'cache-version-user' }));
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({ version: 1, updated_at: 1 }), eligible_external_ai: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ version: 2, updated_at: 2, encrypted_title: 'sealed:TmV3ZXI=' })], eligible_external_ai: [] }), { status: 200 }));
    expect((await getUserTask('task-server-id')).version).toBe(1);
    await listUserTasks();
    const newest = await getUserTask('task-server-id');
    expect(newest.version).toBe(2);
    expect(newest.title).toBe('Newer');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // contract-test: direct surface=gui.web assertions=tasks.surface.semantic-parity
  it('gets eligibility from metadata-only API when a created task is warm without board provenance', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'warm-task-user' }));
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse() }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ eligible_external_ai: ['codex'] }), { status: 200 }));
    await createUserTask({ title: 'Private task title' });
    expect((await getUserTask('task-server-id')).task_id).toBe('task-server-id');
    expect(await getTaskAssignmentEligibility()).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe('https://api.test/v1/user-tasks/assignment-eligibility');
  });

  // contract-test: direct surface=gui.web assertions=tasks.lifecycle.visible,tasks.surface.semantic-parity
  it('refreshes a conflicted board from the server before retrying a move', async () => {
    userProfile.update((profile) => ({ ...profile, user_id: 'conflict-refresh-user' }));
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ version: 1 })], eligible_external_ai: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ version: 2, updated_at: 2 })], eligible_external_ai: [] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ version: 3, updated_at: 3, status: 'in_progress' })] }), { status: 200 }));
    expect((await listTaskBoardItems())[0]?.version).toBe(1);
    expect((await listTaskBoardItems())[0]?.version).toBe(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [latest] = await listTaskBoardItems({}, { force: true });
    if (!latest || !('encrypted' in latest)) throw new Error('Expected encrypted user task');
    expect(latest.version).toBe(2);
    await reorderUserTasks([{ task: latest, status: 'in_progress' }]);
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body)).moves[0].version).toBe(2);
  });

  // contract-test: direct surface=gui.web assertions=tasks.lifecycle.visible
  it('keeps one keyed card when cache publication precedes the local create result', () => {
    const cached = taskViewModel();
    const created = { ...cached, title: 'New title' };
    const rows = prependTaskBoardItem([cached], created);
    expect(rows).toHaveLength(1);
    expect(rows[0].title).toBe('New title');
  });

  // contract-test: direct surface=gui.web assertions=tasks.surface.semantic-parity,tasks.content.client-encrypted
  it('loads one selected task by ID and receives owner assignment provenance without a list request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({
      task: taskResponse(), eligible_external_ai: ['codex'],
    }), { status: 200 }));
    const task = await getUserTask('task-server-id');
    expect(task.task_id).toBe('task-server-id');
    expect(task.title).toBe('Private task title');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('https://api.test/v1/user-tasks/task-server-id');
    expect(cryptoMocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.external-chat.encrypted-context
  it('encrypts external context and sends only the provider plus blind index when filtering', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({
        external_chat_provider: 'codex',
        encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
        encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
      }) }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [] }), { status: 200 }));

    const created = await createUserTask({ title: 'Private task title', externalChat });
    await listUserTasks({ externalChat });

    const createBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    const listUrl = String(fetchMock.mock.calls[1]?.[0]);
    expect(createBody).toMatchObject({
      primary_chat_id: null,
      external_chat_provider: 'codex',
      encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
      encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
    });
    expect(createBody.external_chat_lookup_hash).toBe(await externalChatLookupHash(externalChat));
    expect(JSON.stringify(createBody)).not.toContain(externalChat.id);
    expect(JSON.stringify(createBody)).not.toContain(externalChat.title);
    expect(listUrl).toContain('external_chat_provider=codex');
    expect(listUrl).toContain(`external_chat_lookup_hash=${await externalChatLookupHash(externalChat)}`);
    expect(listUrl).not.toContain(externalChat.id);
    expect(listUrl).not.toContain(externalChat.title);
    expect(created.externalChat).toEqual(externalChat);
  });

  // contract-test: direct surface=gui.web assertions=tasks.external-chat.encrypted-context,tasks.key-wrappers.context-scoped
  it('rejects native and external context before any mutation request and clears external fields on native assignment', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');

    await expect(createUserTask({ title: 'Conflict', primaryChatId: 'chat-native', externalChat })).rejects.toThrow('both native chat and external chat');
    await expect(updateUserTask(taskViewModel(), { primaryChatId: 'chat-native', externalChat })).rejects.toThrow('both native chat and external chat');
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({ primary_chat_id: 'chat-native' }) }), { status: 200 }));
    await updateUserTask({ ...taskViewModel(), externalChat }, { primaryChatId: 'chat-native' });
    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      primary_chat_id: 'chat-native',
      external_chat_provider: null,
      external_chat_lookup_hash: null,
      encrypted_external_chat_id: null,
      encrypted_external_chat_title: null,
    });
  });

  // contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.external-chat.encrypted-context
  it('encrypts an external context update with a null native chat assignment', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({
      external_chat_provider: 'codex',
      encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
      encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
    }) }), { status: 200 }));

    await updateUserTask(taskViewModel(), { externalChat });

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      primary_chat_id: null,
      external_chat_provider: 'codex',
      encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
      encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
    });
    expect(body.external_chat_lookup_hash).toBe(await externalChatLookupHash(externalChat));
    expect(JSON.stringify(body)).not.toContain(externalChat.id);
    expect(JSON.stringify(body)).not.toContain(externalChat.title);
  });

  // contract-test: supporting surface=gui.web assertions=tasks.external-chat.encrypted-context,tasks.assignment.identity-separated
  it('clears external context metadata when starting the native OpenMates queue', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({
      status: 'todo',
      assignee_type: 'openmates',
      assignee_identity: 'openmates',
      external_chat_provider: null,
      external_chat_lookup_hash: null,
      encrypted_external_chat_id: null,
      encrypted_external_chat_title: null,
    }) }), { status: 200 }));

    await startUserTaskWithAI({ ...taskViewModel(), externalChat });

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      version: 1,
      primary_chat_id: null,
      external_chat_provider: null,
      external_chat_lookup_hash: null,
      encrypted_external_chat_id: null,
      encrypted_external_chat_title: null,
    });
    expect(JSON.stringify(body)).not.toContain(externalChat.id);
    expect(JSON.stringify(body)).not.toContain(externalChat.title);
  });

  // contract-test: direct surface=gui.web assertions=tasks.blocking.encrypted-reason,tasks.lifecycle.visible
  it('encrypts a human blocked explanation and decrypts authorized response data without inventing code-only text', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({ encrypted_blocked_reason: 'sealed:UmVwb3NpdG9yeSBjcmVkZW50aWFsIG5lZWRlZA==' }) }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse({ blocked_reason_code: 'missing_credentials' })] }), { status: 200 }));

    const blocked = await blockUserTask(taskViewModel(), 'missing_credentials', 'Repository credential needed');
    const [codeOnly] = await listUserTasks();
    const blockBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;

    expect(blockBody.encrypted_blocked_reason).toBe('sealed:UmVwb3NpdG9yeSBjcmVkZW50aWFsIG5lZWRlZA==');
    expect(JSON.stringify(blockBody)).not.toContain('Repository credential needed');
    expect(blocked.blockedReason).toBe('Repository credential needed');
    expect(codeOnly?.blockedReasonCode).toBe('missing_credentials');
    expect(codeOnly?.blockedReason).toBe('');
  });

  // contract-test: direct surface=gui.web assertions=tasks.activity.client-encrypted,tasks.activity.context-attribution
  it('encrypts Task Activity locally and exposes only decrypted authorized fields', async () => {
    const activityRecord = {
      entry_id: '00000000-0000-4000-8000-000000000001',
      task_id: 'task-server-id',
      kind: 'comment',
      actor_type: 'user',
      actor_hash: 'actor-hash',
      actor_display_name: 'Ada',
      actor_profile_image_url: '/v1/files/avatar',
      event_type: 'comment_added',
      source_surface: 'web',
      created_at: 123,
      deleted_at: null,
      deleted_by_hash: null,
      deleted_by_display_name: null,
      encrypted_message: 'sealed:UHJpdmF0ZSBhY3Rpdml0eSBjb21tZW50',
      encrypted_embed_key_material: 'sealed:ZW1iZWQta2V5LW1hdGVyaWFs',
      embed_refs: ['embed-1'],
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ entry: activityRecord }), { status: 200 }));

    const entry = await createUserTaskActivity(taskViewModel(), {
      message: 'Private activity comment',
      embedRefs: ['embed-1'],
      embedKeyMaterial: 'embed-key-material',
      createdAt: 123,
      teamId: 'team-1',
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      entry_id: '00000000-0000-4000-8000-000000000001',
      encrypted_message: 'sealed:UHJpdmF0ZSBhY3Rpdml0eSBjb21tZW50',
      encrypted_embed_key_material: 'sealed:ZW1iZWQta2V5LW1hdGVyaWFs',
      embed_refs: ['embed-1'],
      created_at: 123,
    });
    expect(JSON.stringify(body)).not.toContain('Private activity comment');
    expect(JSON.stringify(body)).not.toContain('embed-key-material');
    expect(body).not.toHaveProperty('encrypted_entry_key');
    expect(cryptoMocks.encryptWithEmbedKey).toHaveBeenCalledWith(
      'Private activity comment',
      expect.any(Uint8Array),
      'task_activity_comment:task-server-id:00000000-0000-4000-8000-000000000001:v1',
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('team_id=team-1');
    expect(entry).toMatchObject({
      entryId: activityRecord.entry_id,
      message: 'Private activity comment',
      embedKeyMaterial: 'embed-key-material',
      actorDisplayName: 'Ada',
      actorProfileImageUrl: '/v1/files/avatar',
      sourceSurface: 'web',
    });
  });

  // contract-test: direct surface=gui.web assertions=tasks.activity.client-encrypted,tasks.activity.deletion-tombstone,tasks.activity.single-final-section
  it('paginates Activity and suppresses tombstone content without decrypting it', async () => {
    const comment = {
      entry_id: 'entry-comment', task_id: 'task-server-id', kind: 'comment', actor_type: 'user', actor_hash: 'author-hash',
      event_type: 'comment_added', source_surface: 'cli', created_at: 100,
      encrypted_message: 'sealed:SGVsbG8=', encrypted_embed_key_material: null, embed_refs: [],
    };
    const tombstone = {
      entry_id: 'entry-deleted', task_id: 'task-server-id', kind: 'tombstone', actor_type: 'user', actor_hash: 'author-hash',
      author_hash: 'author-hash', actor_display_name: 'Ada', event_type: 'comment_deleted', source_surface: 'web', created_at: 101,
      deleted_at: 102, deleted_by_hash: 'deleter-hash', deleted_by_display_name: 'Grace', embed_refs: [],
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ entries: [comment], next_cursor: '100:entry-comment' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ entries: [tombstone], next_cursor: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ entry: tombstone }), { status: 200 }));

    const entries = await listUserTaskActivity(taskViewModel(), 'team-1');
    const deleted = await deleteUserTaskActivity(taskViewModel(), 'entry-deleted', 'team-1');

    expect(String(fetchMock.mock.calls[1]?.[0])).toContain('cursor=100%3Aentry-comment');
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('team_id=team-1');
    expect(entries[0]).toMatchObject({ entryId: 'entry-comment', message: 'Hello', sourceSurface: 'cli' });
    expect(entries[1]).toMatchObject({ entryId: 'entry-deleted', kind: 'tombstone', deletedByDisplayName: 'Grace', embedRefs: [] });
    expect(entries[1]).not.toHaveProperty('message');
    expect(cryptoMocks.unwrapEmbedKeyWithChatKey).not.toHaveBeenCalled();
    expect(deleted).not.toHaveProperty('message');
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain('/activity/entry-deleted');
    expect(String(fetchMock.mock.calls[2]?.[0])).toContain('team_id=team-1');
  });

  // contract-test: direct surface=gui.web assertions=tasks.activity.composer-message-parity
  it('blocks Activity submission while uploads or transcription are unresolved and keeps failures visible', () => {
    expect(canSubmitUserTaskActivity('Ready comment', [])).toBe(true);
    expect(canSubmitUserTaskActivity('Ready comment', ['finished'])).toBe(true);
    expect(canSubmitUserTaskActivity('Ready comment', ['uploading'])).toBe(false);
    expect(canSubmitUserTaskActivity('Ready comment', ['transcribing'])).toBe(false);
    expect(canSubmitUserTaskActivity('Ready comment', ['error'])).toBe(false);
    expect(canSubmitUserTaskActivity('  ', [])).toBe(false);
  });
});

// contract-test: supporting surface=gui.web assertions=tasks.assignment.identity-separated
it('uses owner creator eligibility independently of visible Tasks and fails closed', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [], eligible_external_ai: ['codex'] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse()], eligible_external_ai: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ tasks: [taskResponse()] }), { status: 200 }));
  expect(await getTaskAssignmentEligibility()).toBe(true);
  expect(await getTaskAssignmentEligibility()).toBe(false);
  await expect(getTaskAssignmentEligibility()).rejects.toThrow();
});
