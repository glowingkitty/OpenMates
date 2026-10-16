/**
 * Account-scoped identity and participant-bound keys for private Team chats.
 * The public key is registered once after account unlock; its private half is
 * backed up with the existing master-key format for cross-device recovery.
 * Each direct chat receives its own random key, wrapped separately for both
 * participants. Direct envelopes never enter the shared Team-key path.
 * Async operations fence account and Team changes before storing key material.
 */
import { get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import { computeSHA256 } from '../message_parsing/utils';
import { userProfile } from '../stores/userProfile';
import { authStore } from '../stores/authStore';
import { getActiveTeamContextSnapshot, isActiveTeamContext } from '../stores/teamStore';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';
import { getKeyFromStorage } from './cryptoService';
import { decryptWithMasterKey, encryptWithMasterKey } from './encryption/MetadataEncryptor';
import { chatKeyManager } from './encryption/ChatKeyManager';
import { chatDB } from './db';
import { userDB, type AccountChatKeyCacheRecord } from './userDB';
import { chatListCache } from './chatListCache';
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from './drafts/draftConstants';
import { encryptWithChatKey } from './encryption/MessageEncryptor';
import type { Chat } from '../types/chat';
import {
  directChatKeyId, generateIdentity, openDirectChatKey, sealDirectChatKey,
} from '@repo/pairing-crypto/direct-chat';

type Identity = { publicKey: string; privateKey: string; keyId: string };
type KeyRecord = {
  version: 1; algorithm: 'x25519-xsalsa20poly1305'; key_id: string;
  public_key: string; encrypted_private_key: string;
};
type MemberKey = { key_id: string; public_key: string };
type Scope = { epoch: number; accountId: string; apiEndpoint: string };

export class DirectChatError extends Error {
  constructor(public readonly code: 'pending' | 'unavailable' | 'cancelled' | 'invalid', message: string, public readonly status?: number) {
    super(message);
    this.name = 'DirectChatError';
  }
}

let cachedIdentity: { scope: Scope; identity: Identity } | null = null;
let pendingIdentity: { scope: Scope; promise: Promise<Identity> } | null = null;
const directChatIds = new Set<string>();
registerWorkspaceCacheClear(() => {
  cachedIdentity = null;
  pendingIdentity = null;
  for (const chatId of directChatIds) chatKeyManager.removeKey(chatId);
  directChatIds.clear();
});

function currentScope(): Scope {
  const accountId = get(userProfile).user_id;
  if (!accountId || !get(authStore).isAuthenticated) {
    throw new DirectChatError('unavailable', 'Sign in to use private messages.');
  }
  return { epoch: getWorkspaceCacheEpoch(), accountId, apiEndpoint: getApiEndpoint('/v1/account/chat-encryption-key') };
}

function assertScope(scope: Scope): void {
  if (getWorkspaceCacheEpoch() !== scope.epoch || get(userProfile).user_id !== scope.accountId ||
      getApiEndpoint('/v1/account/chat-encryption-key') !== scope.apiEndpoint || !get(authStore).isAuthenticated) {
    throw new DirectChatError('cancelled', 'The account changed while opening a private message.');
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(getApiEndpoint(path), {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    if (response.status === 404) throw new DirectChatError('pending', 'Secure messaging setup is pending. Ask this member to open OpenMates.', response.status);
    throw new DirectChatError('unavailable', `Private messaging is unavailable (${response.status}).`, response.status);
  }
  return await response.json() as T;
}

function base64Url(value: string): string { return value.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, ''); }
function fromBase64Url(value: string): string {
  const base = value.replace(/-/g, '+').replace(/_/g, '/');
  return base + '='.repeat((4 - base.length % 4) % 4);
}

async function decodeIdentity(record: KeyRecord): Promise<Identity> {
  if (record.version !== 1 || record.algorithm !== 'x25519-xsalsa20poly1305' || !record.key_id || !record.public_key || !record.encrypted_private_key) {
    throw new DirectChatError('invalid', 'The saved private messaging identity is invalid.');
  }
  const privateKey = await decryptWithMasterKey(fromBase64Url(record.encrypted_private_key));
  if (!privateKey) throw new DirectChatError('unavailable', 'The private messaging identity could not be unlocked.');
  if (await directChatKeyId(record.public_key) !== record.key_id) {
    throw new DirectChatError('invalid', 'The saved private messaging identity has a mismatched key ID.');
  }
  // Validate that the encrypted private key actually belongs to the published
  // key. A mismatched backup must never be used to create unreadable chats.
  const probe = crypto.getRandomValues(new Uint8Array(32));
  const binding = { teamId: 'identity-check', chatId: 'identity-check', recipientHash: 'identity-check', keyId: record.key_id };
  try {
    const envelope = await sealDirectChatKey(probe, binding, record.public_key);
    const opened = await openDirectChatKey(envelope, binding, privateKey);
    if (!opened.every((byte, index) => byte === probe[index])) throw new Error('private key mismatch');
  } catch {
    throw new DirectChatError('invalid', 'The saved private messaging identity could not be verified.');
  }
  return { publicKey: record.public_key, privateKey, keyId: record.key_id };
}

/** GET before PUT prevents replacing a previously enrolled device identity. */
export async function ensureDirectChatIdentity(): Promise<Identity> {
  const scope = currentScope();
  const sameScope = (other: Scope) => other.epoch === scope.epoch && other.accountId === scope.accountId && other.apiEndpoint === scope.apiEndpoint;
  if (cachedIdentity && sameScope(cachedIdentity.scope)) return cachedIdentity.identity;
  if (pendingIdentity && sameScope(pendingIdentity.scope)) return pendingIdentity.promise;
  const promise = (async () => {
    if (!await getKeyFromStorage()) throw new DirectChatError('unavailable', 'Unlock your account to use private messages.');
    assertScope(scope);
    // The cached value is still encrypted under the account master key. A Team
    // switch clears decrypted memory, but this account-wide backup remains usable.
    let cached: AccountChatKeyCacheRecord | null = null;
    try { cached = await userDB.getAccountChatKeyCache(() => assertScope(scope)); }
    catch { assertScope(scope); /* Storage failure leaves online recovery available. */ }
    assertScope(scope);
    if (cached?.accountId === scope.accountId && cached.apiEndpoint === scope.apiEndpoint) {
      const identity = await decodeIdentity(cached.key);
      assertScope(scope);
      cachedIdentity = { scope, identity };
      return identity;
    }
    let { key: record } = await request<{ key: KeyRecord | null }>('/v1/account/chat-encryption-key');
    assertScope(scope);
    if (!record) {
      const generated = await generateIdentity();
      assertScope(scope);
      const encryptedPrivate = await encryptWithMasterKey(generated.privateKey);
      assertScope(scope);
      if (!encryptedPrivate) throw new DirectChatError('unavailable', 'Could not protect the private messaging identity.');
      const proposal: KeyRecord = {
        version: 1, algorithm: 'x25519-xsalsa20poly1305', key_id: generated.keyId,
        public_key: generated.publicKey, encrypted_private_key: base64Url(encryptedPrivate),
      };
      try {
        ({ key: record } = await request<{ key: KeyRecord }>('/v1/account/chat-encryption-key', { method: 'PUT', body: JSON.stringify(proposal) }));
      } catch (error) {
        // Another unlocked device may have enrolled first. Its immutable record wins.
        if (!(error instanceof DirectChatError) || error.status !== 409) throw error;
        ({ key: record } = await request<{ key: KeyRecord }>('/v1/account/chat-encryption-key'));
      }
    }
    assertScope(scope);
    if (!record) throw new DirectChatError('unavailable', 'Private messaging identity was not saved.');
    const identity = await decodeIdentity(record);
    assertScope(scope);
    // Quota and storage errors must not break a successfully unlocked identity.
    try { await userDB.setAccountChatKeyCache({ accountId: scope.accountId, apiEndpoint: scope.apiEndpoint, key: record }, () => assertScope(scope)); }
    catch { assertScope(scope); }
    assertScope(scope);
    cachedIdentity = { scope, identity };
    return identity;
  })();
  pendingIdentity = { scope, promise };
  try { return await promise; }
  finally { if (pendingIdentity?.promise === promise) pendingIdentity = null; }
}

/** Enrollment starts on normal authenticated unlock, making the public key available while offline. */
export function startDirectChatIdentityEnrollment(): void {
  if (typeof window === 'undefined') return;
  let scheduled = false;
  const schedule = () => {
    if (scheduled || !get(authStore).isAuthenticated || !get(userProfile).user_id) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      void ensureDirectChatIdentity().catch(() => { /* The Message action surfaces recoverable errors. */ });
    });
  };
  authStore.subscribe(schedule);
  userProfile.subscribe(schedule);
}

export function isDirectChatEnvelope(value: string | null | undefined): boolean {
  return !!value && value.startsWith('OMDM1.');
}

export async function unwrapDirectTeamChatKey(teamId: string, chatId: string, envelope: string): Promise<Uint8Array> {
  if (!isDirectChatEnvelope(envelope)) throw new DirectChatError('invalid', 'Private chat key envelope is invalid.');
  const scope = currentScope();
  const team = getActiveTeamContextSnapshot();
  const teamEpoch = team.epoch;
  if (team.teamId !== teamId) throw new DirectChatError('cancelled', 'The active Team changed.');
  const identity = await ensureDirectChatIdentity();
  assertScope(scope);
  const ownHash = await computeSHA256(scope.accountId);
  assertScope(scope);
  if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
  const key = await openDirectChatKey(envelope, { teamId, chatId, recipientHash: ownHash, keyId: identity.keyId }, identity.privateKey);
  assertScope(scope);
  if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
  directChatIds.add(chatId);
  return key;
}

/** A direct chat key is never wrapped with the Team key or account master key. */
export async function unwrapTeamOrDirectChatKey(teamId: string, chatId: string, encryptedKey: string, visibility?: string | null): Promise<Uint8Array> {
  if (visibility === 'direct' || isDirectChatEnvelope(encryptedKey)) return unwrapDirectTeamChatKey(teamId, chatId, encryptedKey);
  const { unwrapTeamChatKey } = await import('./teamService');
  return unwrapTeamChatKey(teamId, encryptedKey);
}

export async function createDirectChat(teamId: string, recipientHash: string): Promise<Chat> {
  const scope = currentScope();
  const team = getActiveTeamContextSnapshot();
  const teamEpoch = team.epoch;
  if (team.teamId !== teamId || team.team?.status !== 'active') throw new DirectChatError('cancelled', 'Select an active Team to open a private message.');
  const ownHash = await computeSHA256(scope.accountId);
  if (ownHash === recipientHash) throw new DirectChatError('invalid', 'You cannot message yourself.');
  assertScope(scope);
  const identity = await ensureDirectChatIdentity();
  const existing = (await chatDB.getAllChats()).find(chat =>
    chat.team_id === teamId && chat.chat_visibility === 'direct' &&
    chat.participant_user_hashes?.length === 2 &&
    chat.participant_user_hashes.includes(ownHash) && chat.participant_user_hashes.includes(recipientHash) &&
    isDirectChatEnvelope(chat.encrypted_chat_key),
  );
  assertScope(scope);
  if (existing) {
    const key = await unwrapDirectTeamChatKey(teamId, existing.chat_id, existing.encrypted_chat_key!);
    assertScope(scope);
    if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
    chatKeyManager.injectKey(existing.chat_id, key, 'direct_chat');
    return existing;
  }
  const recipient = await request<MemberKey>(`/v1/teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(recipientHash)}/chat-encryption-key`);
  assertScope(scope);
  if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
  const chatId = crypto.randomUUID();
  const rawKey = crypto.getRandomValues(new Uint8Array(32));
  const [ownEnvelope, recipientEnvelope, encryptedTitle] = await Promise.all([
    sealDirectChatKey(rawKey, { teamId, chatId, recipientHash: ownHash, keyId: identity.keyId }, identity.publicKey),
    sealDirectChatKey(rawKey, { teamId, chatId, recipientHash, keyId: recipient.key_id }, recipient.public_key),
    // One encrypted title is shared by both participants, so it cannot contain
    // a name from only the sender's perspective.
    encryptWithChatKey('Private Team message', rawKey),
  ]);
  assertScope(scope);
  if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
  const result = await request<{ chat: Chat & { id?: string } }>(`/v1/teams/${encodeURIComponent(teamId)}/direct-chats`, {
    method: 'POST', body: JSON.stringify({
      chat_id: chatId, recipient_user_hash: recipientHash,
      participant_key_envelopes: {
        [ownHash]: { key_id: identity.keyId, encrypted_chat_key: ownEnvelope },
        [recipientHash]: { key_id: recipient.key_id, encrypted_chat_key: recipientEnvelope },
      },
      encrypted_title: encryptedTitle,
    }),
  });
  assertScope(scope);
  if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
  const returned = result.chat;
  if (!returned || (returned.chat_id ?? returned.id) !== chatId || returned.team_id !== teamId || returned.chat_visibility !== 'direct' ||
      !returned.participant_user_hashes?.includes(ownHash) || !returned.participant_user_hashes.includes(recipientHash) ||
      returned.participant_user_hashes.length !== 2 || returned.encrypted_chat_key !== ownEnvelope) {
    throw new DirectChatError('invalid', 'The private chat response did not match the requested participants.');
  }
  const chat: Chat = { ...returned, chat_id: chatId, encrypted_title: returned.encrypted_title ?? encryptedTitle };
  chatKeyManager.injectKey(chatId, rawKey, 'created');
  directChatIds.add(chatId);
  const writeGuard = () => {
    assertScope(scope);
    if (!isActiveTeamContext(teamId, teamEpoch)) throw new DirectChatError('cancelled', 'The active Team changed.');
  };
  await chatDB.addChat(chat, undefined, { isFromSync: true, writeGuard });
  writeGuard();
  chatListCache.upsertChat(chat);
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: chatId, chat } }));
  return chat;
}
