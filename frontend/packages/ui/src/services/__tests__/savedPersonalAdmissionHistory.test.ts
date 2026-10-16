import { describe, expect, it } from 'vitest';
import type { Message } from '../../types/chat';
import { prepareSavedPersonalAdmissionHistory, selectPersonalPhasedAdmission } from '../savedPersonalAdmissionHistory';

const rows = [
  { message_id: 'u1', chat_id: 'chat', role: 'user', content: 'prior question', created_at: 1 },
  { message_id: 'a1', chat_id: 'chat', role: 'assistant', content: 'prior answer', created_at: 2,
    encrypted_content: 'ciphertext', encrypted_category: 'category-ciphertext', encrypted_model_name: 'model-ciphertext', encrypted_pii_mappings: 'pii-ciphertext' },
  { message_id: 'u2', chat_id: 'chat', role: 'user', content: 'unfiltered local text', created_at: 3 },
] as Message[];
function prepare(overrides: Partial<Parameters<typeof prepareSavedPersonalAdmissionHistory>[0]> = {}) {
  return prepareSavedPersonalAdmissionHistory({ chatId: 'chat', messageId: 'u2', currentContent: 'filtered request',
    read: async () => structuredClone(rows), category: async row => row.role === 'assistant' ? 'general_knowledge' : undefined,
    assertCurrent: () => {}, ...overrides });
}
describe('saved Personal phased admission history', () => {
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('retains every prior row, exact identities, ciphertext and resolved assistant category', async () => {
    const history = await prepare();
    expect(history.map(row => row.message_id)).toEqual(['u1', 'a1', 'u2']);
    expect(history[1]).toMatchObject({ content: 'prior answer', encrypted_content: 'ciphertext',
      encrypted_category: 'category-ciphertext', encrypted_model_name: 'model-ciphertext',
      encrypted_pii_mappings: 'pii-ciphertext', category: 'general_knowledge' });
    expect(history[2].content).toBe('filtered request'); expect(rows[2].content).toBe('unfiltered local text');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('never admits a saved follow-up with blank or unavailable history', async () => {
    await expect(prepare({ read: async () => [] })).rejects.toThrow('requires previous history');
    await expect(prepare({ read: async () => [rows[2]] })).rejects.toThrow('requires previous history');
    await expect(prepare({ read: async () => { throw new Error('history unavailable'); } })).rejects.toThrow('history unavailable');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('rejects cross-chat and duplicate row identities', async () => {
    await expect(prepare({ read: async () => [{ ...rows[0], chat_id: 'other' }] })).rejects.toThrow('identity mismatch');
    await expect(prepare({ read: async () => [rows[0], rows[0]] })).rejects.toThrow('identity mismatch');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('fails closed when historical plaintext is unavailable', async () => {
    await expect(prepare({ read: async () => [{ ...rows[0], content: undefined }] })).rejects.toThrow('not decrypted');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('requires current account/workspace/key ownership before and after asynchronous reads', async () => {
    let current = true;
    const assertCurrent = () => { if (!current) throw new Error('scope changed'); };
    await expect(prepare({ assertCurrent, read: async () => { current = false; return rows; } })).rejects.toThrow('scope changed');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('rejects a scope switch while resolving encrypted assistant category', async () => {
    let current = true;
    await expect(prepare({ assertCurrent: () => { if (!current) throw new Error('key epoch changed'); },
      category: async () => { current = false; return 'category'; } })).rejects.toThrow('key epoch changed');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('does not truncate long saved history or mutate the captured source rows', async () => {
    const long = Array.from({ length: 150 }, (_, index) => ({ ...rows[index % 2], message_id: `row${index}` }));
    expect(await prepare({ read: async () => long })).toHaveLength(150);
    expect(long[0].message_id).toBe('row0');
  });
  // contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,chats.message.identity-idempotent
  it('never converts an immutable legacy retry to phased or a phased retry to legacy', () => {
    expect(selectPersonalPhasedAdmission(true, true, false)).toBe(false);
    expect(selectPersonalPhasedAdmission(false, true, true)).toBe(true);
    expect(selectPersonalPhasedAdmission(true, false, false)).toBe(true);
    expect(selectPersonalPhasedAdmission(false, false, false)).toBe(false);
  });
});
