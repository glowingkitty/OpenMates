import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

const mocks = vi.hoisted(() => ({
  activeFocus: vi.fn(), getProject: vi.fn(), contents: vi.fn(), settings: vi.fn(),
  readHead: vi.fn(), receipt: vi.fn(), approve: vi.fn(), decrypt: vi.fn(), encrypt: vi.fn(),
}));
vi.mock('../../config/api', () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock('../../stores/authStore', async () => {
  const { writable } = await import('svelte/store');
  return { authStore: writable({ isAuthenticated: true }) };
});
vi.mock('../../stores/userProfile', async () => {
  const { writable } = await import('svelte/store');
  const userProfile = writable({ user_id: 'owner', encrypted_settings: 'existing-ciphertext' });
  return { userProfile, updateProfile: (patch: object) => userProfile.update((value) => ({ ...value, ...patch })) };
});
vi.mock('../../stores/activeChatStore', () => ({ activeChatStore: { get: () => 'chat-1' } }));
vi.mock('../encryption/MetadataEncryptor', () => ({ decryptWithMasterKey: mocks.decrypt, encryptWithMasterKey: mocks.encrypt }));
vi.mock('../encryption/ChatKeyManager', () => ({ chatKeyManager: { getKey: async () => new Uint8Array(32).fill(7) } }));
vi.mock('../cryptoService', () => ({ decryptWithEmbedKey: mocks.decrypt, encryptWithEmbedKey: async () => 'opaque-embed-ciphertext', wrapEmbedKeyWithChatKey: async () => 'wrapped-key' }));
vi.mock('../projectService', () => ({
  getActiveProjectFocus: mocks.activeFocus, getProject: mocks.getProject, getProjectContents: mocks.contents,
  getProjectSettings: mocks.settings, readEncryptedProjectFile: mocks.readHead,
  getProjectFileRevisionReceipt: mocks.receipt, approveProjectWrite: mocks.approve,
}));

import { authStore } from '../../stores/authStore';
import { userProfile } from '../../stores/userProfile';
import { collectCustomRuleDocuments, savePersonalRuleDocument, saveProjectMarkdownDocument, readActiveProjectMarkdownDocuments } from '../ruleDocumentService';

const guide = '---\ntitle: Private Python practices\ndescription: Private reusable service practices.\nwhen_to_use: Writing Python services.\n---\n- Preserve cancellation.\n- Release resources.\n';
const personal = { id: 'personal:r1', document: guide };
const project = { project_id: 'p1', projectKey: new Uint8Array(32).fill(8) };
const focus = { active: true, project_id: 'p1', team_id: null };

describe('encrypted private Rule transport', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    vi.stubGlobal('crypto', webcrypto);
    authStore.set({ isAuthenticated: true, isInitialized: true });
    userProfile.update((value) => ({ ...value, user_id: 'owner', encrypted_settings: 'existing-ciphertext' }));
    mocks.decrypt.mockResolvedValue(JSON.stringify({ rule_documents: [personal], topic_preferences: { version: 1 } }));
    mocks.encrypt.mockResolvedValue('new-opaque-ciphertext');
    mocks.activeFocus.mockResolvedValue(null);
    mocks.getProject.mockResolvedValue(project);
    mocks.contents.mockResolvedValue({ folders: [], items: [{
      project_item_id: 'project-rule-id', item_type: 'embed', target_id: 'embed-rule-id', displayName: '',
      metadata: { path: '.openmates/rules/r1.md' }, encrypted: {},
    }] });
    mocks.settings.mockResolvedValue({ settings: {} });
    mocks.readHead.mockResolvedValue({ content: { code: guide }, revision: 1, embedKey: new Uint8Array(32), hasInitialHistory: true });
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom,rules.selection.focus-aware
  it('never reads Project catalog or bodies before authoritative activation', async () => {
    expect(await collectCustomRuleDocuments({ chatId: 'chat-1', projectId: 'p1' })).toEqual([{ ...personal, source: 'personal' }]);
    expect(mocks.getProject).not.toHaveBeenCalled();
    expect(mocks.contents).not.toHaveBeenCalled();
    expect(mocks.readHead).not.toHaveBeenCalled();
    authStore.set({ isAuthenticated: false, isInitialized: true });
    expect(await collectCustomRuleDocuments({ chatId: 'chat-1' })).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('drops Project documents revoked while the encrypted file is being read', async () => {
    mocks.activeFocus.mockResolvedValue(focus);
    mocks.readHead.mockImplementation(async () => {
      mocks.activeFocus.mockResolvedValue(null);
      return { content: { code: guide }, revision: 1, embedKey: new Uint8Array(32), hasInitialHistory: true };
    });
    expect(await collectCustomRuleDocuments({ chatId: 'chat-1', projectId: 'p1' })).toEqual([{ ...personal, source: 'personal' }]);
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom,rules.definition.guide-format
  it('preserves existing encrypted account namespaces and sends only ciphertext', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ success: true }));
    const saved = await savePersonalRuleDocument({ id: personal.id, document: guide + '- Verify errors.\n' });
    expect(saved.id).toBe(personal.id);
    const plaintext = JSON.parse(mocks.encrypt.mock.calls[0][0]);
    expect(plaintext.topic_preferences).toEqual({ version: 1 });
    expect(plaintext.rule_documents[0].document).toContain('Verify errors.');
    const body = String(fetchMock.mock.calls[0][1]?.body);
    expect(body).toBe(JSON.stringify({ encrypted_settings: 'new-opaque-ciphertext' }));
    expect(body).not.toContain('Private Python');
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.test/v1/settings/encrypted-account');
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('fences an account change while encrypting so no previous-owner settings are sent', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    mocks.encrypt.mockImplementation(async () => {
      userProfile.update((value) => ({ ...value, user_id: 'different-owner', encrypted_settings: 'different-ciphertext' }));
      return 'new-opaque-ciphertext';
    });
    await expect(savePersonalRuleDocument({ id: personal.id, document: guide })).rejects.toThrow('rule_settings_changed');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('drops personal payloads if the owner changes during the activation check', async () => {
    mocks.activeFocus.mockImplementation(async () => {
      userProfile.update((value) => ({ ...value, user_id: 'different-owner' }));
      return null;
    });
    expect(await collectCustomRuleDocuments({ chatId: 'chat-1' })).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom,projects.focus.default-owned
  it('requires approval of the actual draft before an always-ask Project write', async () => {
    mocks.activeFocus.mockResolvedValue(focus);
    mocks.settings.mockResolvedValue({ settings: { writeMode: 'always_ask' } });
    await expect(saveProjectMarkdownDocument({ chatId: 'chat-1', projectId: 'p1', path: '.openmates/focuses/new/SKILL.md',
      document: guide, metadata: {} })).rejects.toThrow('project_document_approval_required');
    expect(mocks.approve).not.toHaveBeenCalled();
    expect(mocks.readHead).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('rejects a changed embed revision before proposing the Markdown write', async () => {
    mocks.activeFocus.mockResolvedValue(focus);
    await expect(saveProjectMarkdownDocument({ chatId: 'chat-1', projectId: 'p1', path: '.openmates/rules/r1.md',
      document: guide, metadata: {}, expectedEmbedRevision: 2, saveApproved: true })).rejects.toThrow('project_document_changed');
    expect(mocks.approve).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('checks the existing private path policy before decrypting selected Markdown bodies', async () => {
    mocks.activeFocus.mockResolvedValue(focus);
    mocks.settings.mockResolvedValue({ settings: { file_access: { private_paths: ['.openmates/rules/r1.md'] } } });
    await expect(readActiveProjectMarkdownDocuments({ chatId: 'chat-1', projectId: 'p1',
      requests: [{ itemId: 'project-rule-id', path: '.openmates/rules/r1.md' }] })).rejects.toThrow();
    expect(mocks.readHead).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=rules.ownership.encrypted-custom
  it('fails closed when encrypted file access settings cannot be decoded', async () => {
    mocks.activeFocus.mockResolvedValue(focus);
    mocks.settings.mockResolvedValue({ settings: {}, encrypted: { encrypted_settings: 'broken-ciphertext' } });
    mocks.decrypt.mockResolvedValue('not JSON');
    await expect(readActiveProjectMarkdownDocuments({ chatId: 'chat-1', projectId: 'p1',
      requests: [{ itemId: 'project-rule-id', path: '.openmates/rules/r1.md' }] })).rejects.toThrow('rule_project_unavailable');
    expect(mocks.readHead).not.toHaveBeenCalled();
  });
});
