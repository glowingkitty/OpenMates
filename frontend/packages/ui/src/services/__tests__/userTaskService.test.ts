// frontend/packages/ui/src/services/__tests__/userTaskService.test.ts
//
// Browser Tasks privacy contract coverage for external chat bindings and
// blocked-reason explanations. The API receives opaque ciphertext, safe
// provider metadata, and an owner-scoped blind index only.
//
// Plan: docs/plans/opencode-external-task-bridge/plan.yml

import { webcrypto } from 'node:crypto';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const masterKey = vi.hoisted(() => ({ value: null as CryptoKey | null }));
const cryptoMocks = vi.hoisted(() => ({
  decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array([1, 2, 3, 4])),
  decryptWithEmbedKey: vi.fn(async (value: string) => value.startsWith('sealed:') ? atob(value.slice('sealed:'.length)) : ''),
  encryptChatKeyWithMasterKey: vi.fn(async () => 'wrapped-task-key'),
  encryptWithEmbedKey: vi.fn(async (value: string) => `sealed:${btoa(value)}`),
  generateEmbedKey: vi.fn(() => new Uint8Array([1, 2, 3, 4])),
  wrapEmbedKeyWithChatKey: vi.fn(async () => 'wrapped-chat-key'),
}));

vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../cryptoService', () => cryptoMocks);
vi.mock('../cryptoKeyStorage', () => ({ getMasterKey: () => masterKey.value }));
vi.mock('../projectService', () => ({ listProjects: vi.fn(async () => []) }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: vi.fn(async () => new Uint8Array([5, 6, 7, 8])) } }));

import {
  blockUserTask,
  createUserTask,
  externalChatLookupHash,
  listUserTasks,
  updateUserTask,
  type EncryptedUserTaskRecord,
  type UserTaskViewModel,
} from '../userTaskService';

const externalChat = { provider: 'opencode' as const, id: 'ses-private-session', title: 'Private external title' };

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
    status: 'blocked', assigneeType: 'user', primaryChatId: null, externalChat: null,
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
    vi.spyOn(crypto, 'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001');
  });

  // contract-test: direct surface=gui.web assertions=tasks.content.client-encrypted,tasks.external-chat.encrypted-context
  it('encrypts external context and sends only the provider plus blind index when filtering', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ task: taskResponse({
        external_chat_provider: 'opencode',
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
      external_chat_provider: 'opencode',
      encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
      encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
    });
    expect(createBody.external_chat_lookup_hash).toBe(await externalChatLookupHash(externalChat));
    expect(JSON.stringify(createBody)).not.toContain(externalChat.id);
    expect(JSON.stringify(createBody)).not.toContain(externalChat.title);
    expect(listUrl).toContain('external_chat_provider=opencode');
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
      external_chat_provider: 'opencode',
      encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
      encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
    }) }), { status: 200 }));

    await updateUserTask(taskViewModel(), { externalChat });

    const body = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)) as Record<string, unknown>;
    expect(body).toMatchObject({
      primary_chat_id: null,
      external_chat_provider: 'opencode',
      encrypted_external_chat_id: 'sealed:c2VzLXByaXZhdGUtc2Vzc2lvbg==',
      encrypted_external_chat_title: 'sealed:UHJpdmF0ZSBleHRlcm5hbCB0aXRsZQ==',
    });
    expect(body.external_chat_lookup_hash).toBe(await externalChatLookupHash(externalChat));
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
});
