import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('../activeChatStore', () => ({
  activeChatStore: { subscribe: (run: (value: string | null) => void) => { run(null); return () => {}; }, setActiveChat: vi.fn() },
}));
vi.mock('../notificationStore', () => ({
  notificationStore: { addNotificationWithOptions: vi.fn(() => 'notification'), removeNotification: vi.fn() },
}));
vi.mock('../../i18n/translations', () => ({
  text: { subscribe: (run: (value: (key: string) => string) => void) => { run((key) => key); return () => {}; } },
}));

import {
  clearProjectFileApprovals, projectFileApprovals, recordProjectFileChange,
  requestProjectIgnoredReadApproval, requestProjectWriteApproval, resolveProjectFileApproval,
} from '../projectFileApprovalStore';

const write = (chatId = 'chat-one') => ({
  projectId: 'project-one', chatId,
  mutation: { operation: 'create_file' as const, operation_id: 'operation-one',
    path: 'README.md', expected_base: null, content: 'A proposed file\n' },
});

beforeEach(() => clearProjectFileApprovals());

// contract-test: supporting surface=gui.web assertions=projects.files.write-policy-enforcement,projects.files.concurrent-chat-safety
describe('Project file approval state', () => {
  it('keeps concrete proposals isolated between chats and replaces stale consent', async () => {
    const first = requestProjectWriteApproval(write());
    const other = requestProjectWriteApproval(write('chat-two'));
    const revised = requestProjectWriteApproval({ ...write(), mutation: { ...write().mutation, content: 'Revised\n' } });
    expect(await first).toBe(false);
    const entries = get(projectFileApprovals);
    expect(entries).toHaveLength(2);
    const selected = entries.find((entry) => entry.request.chatId === 'chat-one')!;
    resolveProjectFileApproval(selected.id, true);
    expect(await revised).toBe(true);
    expect(get(projectFileApprovals).map((entry) => entry.request.chatId)).toEqual(['chat-two']);
    clearProjectFileApprovals();
    expect(await other).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.ignored-exact-inclusion,projects.files.exact-patch
  it('stores exact ignored-read consent and only explicit successful-change records', async () => {
    const pending = requestProjectIgnoredReadApproval({
      projectId: 'project-one', sourceId: 'source-one', chatId: 'chat-one', operationId: 'read-one', path: 'build/output.log',
    });
    expect(get(projectFileApprovals)[0]).toMatchObject({ kind: 'read', status: 'pending', request: { path: 'build/output.log' } });
    clearProjectFileApprovals('chat-one');
    expect(await pending).toBe(false);
    recordProjectFileChange(write());
    expect(get(projectFileApprovals)[0]).toMatchObject({ kind: 'write', status: 'applied', request: write() });
    clearProjectFileApprovals();
    expect(get(projectFileApprovals)).toEqual([]);
  });
});
