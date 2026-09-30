import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { userProfile } from '../../stores/userProfile';
import type { Chat, Message } from '../../types/chat';
import { invalidateWorkspaceCaches, getWorkspaceCacheEpoch } from '../workspaceCacheLifecycle';
import {
  clearRecentChatWindows,
  getRecentChatRevision,
  getRecentChatSelection,
  getRecentChatWindow,
  getRecentChatWindowStats,
  invalidateRecentChatWindow,
  invalidateRecentChatWindowForMessage,
  putRecentChatWindow,
  recentChatHeaderMatches,
  RecentChatWarmReadGuard,
  reconcileRecentChatMessages,
  subscribeRecentChatWindowInvalidation,
  type RecentChatWindow,
} from '../recentChatWindowCache';

const chat = (id: string) => ({ chat_id: id, encrypted_title: 'cipher', title_v: 1 }) as Chat;
const message = (id: string, chatId: string): Message => ({
  message_id: id, chat_id: chatId, role: 'user', created_at: 1, status: 'synced', content: id,
});
const windowFor = (id: string, content = 'original'): RecentChatWindow => ({
  messages: [{ ...message('message', id), content }],
  compressionCheckpoints: [],
  hasMoreBefore: true,
  header: {
    title: 'Decrypted title', category: 'general_knowledge', icon: 'chat', summary: null,
    encryptedTitle: 'cipher', titleVersion: 1,
  },
});

beforeEach(() => userProfile.update((profile) => ({ ...profile, user_id: 'account-a' })));
afterEach(() => {
  clearRecentChatWindows();
  userProfile.update((profile) => ({ ...profile, user_id: null }));
});

describe('recent decrypted chat windows', () => {
  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('refreshes same-ID edits in an expanded window without dropping older pages', () => {
    const older = message('older', 'a');
    const latest = message('latest', 'a');
    const edited = { ...latest, content: 'new canonical text', status: 'delivered' as const };
    expect(reconcileRecentChatMessages([older, latest], [edited], true)).toEqual([older, edited]);
    expect(latest.content).toBe('latest');
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('removes absent rows when the canonical latest window has no older page', () => {
    const retained = message('retained', 'a');
    expect(reconcileRecentChatMessages([message('deleted', 'a'), retained], [retained], false)).toEqual([retained]);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('replays an isolated window and matching header before an asynchronous read', () => {
    const source = windowFor('a');
    // ActiveChat's Svelte $state messages are proxies in the browser.
    source.messages = new Proxy(source.messages, {});
    expect(putRecentChatWindow('a', source)).toBe(true);
    source.messages[0].content = 'mutated after caching';
    const warm = getRecentChatWindow(chat('a'))!;
    expect(warm.messages[0].content).toBe('original');
    expect(warm.hasMoreBefore).toBe(true);
    expect(recentChatHeaderMatches(chat('a'), warm.header)).toBe(true);
    expect(recentChatHeaderMatches({ ...chat('a'), encrypted_title: 'new cipher' }, warm.header)).toBe(false);
    warm.messages[0].content = 'mutated consumer';
    expect(getRecentChatWindow(chat('a'))?.messages[0].content).toBe('original');
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('rejects stale completions after a write, key epoch change, or message deletion', () => {
    const epoch = getWorkspaceCacheEpoch();
    const revision = getRecentChatRevision('a');
    invalidateRecentChatWindow('a');
    expect(putRecentChatWindow('a', windowFor('a'), epoch, revision)).toBe(false);
    expect(putRecentChatWindow('a', windowFor('a'))).toBe(true);
    invalidateRecentChatWindowForMessage('message');
    expect(getRecentChatWindow(chat('a'))).toBeNull();
    invalidateWorkspaceCaches();
    expect(putRecentChatWindow('a', windowFor('a'), epoch)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('rejects live streaming state and evicts older windows at eight entries', () => {
    const streaming = windowFor('live');
    streaming.messages[0].status = 'streaming';
    expect(putRecentChatWindow('live', streaming)).toBe(false);
    const keyPending = windowFor('locked');
    delete keyPending.messages[0].content;
    expect(putRecentChatWindow('locked', keyPending)).toBe(false);
    for (let index = 0; index < 9; index++) putRecentChatWindow(`chat-${index}`, windowFor(`chat-${index}`));
    expect(getRecentChatWindowStats().count).toBe(8);
    expect(getRecentChatWindow(chat('chat-0'))).toBeNull();
    expect(getRecentChatWindow(chat('chat-8'))).not.toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('bounds mutation tokens without accepting a completion after its token was evicted', () => {
    const oldToken = getRecentChatRevision('a');
    invalidateRecentChatWindow('a');
    for (let index = 0; index < 300; index++) invalidateRecentChatWindow(`other-${index}`);
    expect(getRecentChatWindowStats().revisionTokens).toBeLessThanOrEqual(256);
    expect(getRecentChatRevision('a')).not.toBe(oldToken);
    expect(putRecentChatWindow('a', windowFor('a'), getWorkspaceCacheEpoch(), oldToken)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('does not replay a decrypted window after the account identity changes', () => {
    expect(putRecentChatWindow('a', windowFor('a'))).toBe(true);
    userProfile.update((profile) => ({ ...profile, user_id: 'account-b' }));
    expect(getRecentChatWindow(chat('a'))).toBeNull();
    userProfile.update((profile) => ({ ...profile, user_id: null }));
    expect(putRecentChatWindow('a', windowFor('a'))).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('provides a bounded remount shell without carrying a draft or stale selection', () => {
    const sourceChat = { ...chat('a'), encrypted_draft_md: 'private draft ciphertext',
      encrypted_chat_key: 'wrapped key', candidate_encrypted_keys: ['candidate key'],
      encrypted_shared_short_url: 'private share URL', messages: [message('draft', 'a')] };
    expect(putRecentChatWindow('a', windowFor('a'), getWorkspaceCacheEpoch(), getRecentChatRevision('a'), sourceChat)).toBe(true);
    const selected = getRecentChatSelection('a')!;
    expect(selected.chat.chat_id).toBe('a');
    expect(selected.chat.encrypted_draft_md).toBeNull();
    expect(selected.chat.messages).toBeUndefined();
    expect(selected.chat.encrypted_chat_key).toBeUndefined();
    expect(selected.chat.candidate_encrypted_keys).toBeUndefined();
    expect(selected.chat.encrypted_shared_short_url).toBeUndefined();
    expect(selected.window.messages[0].content).toBe('original');
    selected.window.messages[0].content = 'consumer edit';
    expect(getRecentChatSelection('a')?.window.messages[0].content).toBe('original');
    invalidateRecentChatWindow('a');
    expect(getRecentChatSelection('a')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('notifies a mounted warm shell synchronously when its key epoch is cleared', () => {
    let observed = false;
    const unsubscribe = subscribeRecentChatWindowInvalidation(() => { observed = true; });
    invalidateWorkspaceCaches();
    expect(observed).toBe(true);
    unsubscribe();
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('aborts a held canonical read when the key epoch is revoked', async () => {
    const sourceChat = chat('a');
    const epoch = getWorkspaceCacheEpoch();
    const revision = getRecentChatRevision('a');
    expect(putRecentChatWindow('a', windowFor('a'), epoch, revision, sourceChat)).toBe(true);
    const guard = new RecentChatWarmReadGuard('a', epoch, revision);
    let finishRead!: () => void;
    const heldRead = new Promise<void>((resolve) => { finishRead = resolve; });
    let observed: string | null = null;
    const unsubscribe = subscribeRecentChatWindowInvalidation(() => {
      observed = guard.inspect(true, getWorkspaceCacheEpoch(), getRecentChatRevision('a'));
    });
    const pending = heldRead.then(() => guard.canContinue);
    invalidateWorkspaceCaches();
    expect(observed).toBe('revoked');
    expect(getRecentChatSelection('a')).toBeNull();
    finishRead();
    expect(await pending).toBe(false);
    unsubscribe();
  });

  // contract-test: supporting surface=gui.web assertions=chat-navigation.open.local-first-coherent
  it('keeps a held canonical read retryable after an ordinary message write', async () => {
    const epoch = getWorkspaceCacheEpoch();
    const revision = getRecentChatRevision('a');
    const guard = new RecentChatWarmReadGuard('a', epoch, revision);
    let finishRead!: () => void;
    const heldRead = new Promise<void>((resolve) => { finishRead = resolve; });
    let observed: string | null = null;
    const unsubscribe = subscribeRecentChatWindowInvalidation(() => {
      observed = guard.inspect(true, getWorkspaceCacheEpoch(), getRecentChatRevision('a'));
    });
    const pending = heldRead.then(() => ({ canContinue: guard.canContinue, stale: revision !== getRecentChatRevision('a') }));
    invalidateRecentChatWindow('a');
    expect(observed).toBe('mutation');
    expect(guard.active).toBe(true);
    finishRead();
    expect(await pending).toEqual({ canContinue: true, stale: true });
    expect(guard.inspect(true, epoch, getRecentChatRevision('a'))).toBe('current');
    guard.complete();
    expect(guard.active).toBe(false);
    unsubscribe();
  });
});
