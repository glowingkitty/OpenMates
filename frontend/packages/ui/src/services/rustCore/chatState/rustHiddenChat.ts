/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) hidden-chat service: the page adapter over
 * the shared Rust core Worker `chatState` hidden operations. Loaded only by the
 * guarded branches of hiddenChatService.ts, so default builds never bundle it.
 *
 * The PBKDF2 combined secret, the 3-failure / 30 s lockout and the wrap, unwrap,
 * classify, hide and unhide decisions run in the Worker; the page keeps only a
 * boolean lock mirror (so the synchronous `isUnlocked()` callers stay valid),
 * the salt lookup, the master CryptoKey handle, IndexedDB and the socket. There
 * is no TypeScript fallback: a refused call rejects with its fixed code.
 */
import { getKeyFromStorage } from '../../cryptoService';
import { chatStateCall } from './chatListUnitClient';
import { hiddenLockMirror } from './hiddenLockMirror';
import { readHiddenChatSalt } from './hiddenChatAdapter';
import type { HiddenClass, HiddenLockView, HiddenPlanReply } from './hiddenForkProtocol';

const LOCKOUT_MESSAGE = 'Too many failed attempts. Please wait before trying again.';

function mirror(view: HiddenLockView, nowMs: number): void {
	hiddenLockMirror.unlocked = view.unlocked;
	hiddenLockMirror.lockoutUntilMs = view.lockoutSeconds > 0 ? nowMs + view.lockoutSeconds * 1000 : 0;
}

async function master(): Promise<CryptoKey> {
	const key = await getKeyFromStorage();
	if (!key) throw new Error('Master key not found');
	return key;
}

function salt(): Uint8Array | null {
	return readHiddenChatSalt(sessionStorage, localStorage) ?? null;
}

/** `unlockHiddenChats`; throws only for the lockout, like the web service. */
export async function rustHiddenUnlock(code: string, encryptedChatKeys: string[], verified: string | undefined): Promise<{ success: boolean; decryptedCount: number }> {
	const nowMs = Date.now();
	const key = await master().catch(() => null);
	if (!key) return { success: false, decryptedCount: 0 };
	const reply = await chatStateCall('hiddenUnlock', {
		masterKey: key, code, salt: salt(), encryptedChatKeys, verifiedEncryptedChatKey: verified ?? null, nowMs,
	});
	mirror(reply, nowMs);
	if (reply.lockedOut) throw new Error(LOCKOUT_MESSAGE);
	return { success: reply.success, decryptedCount: reply.decryptedCount };
}

/** `encryptChatKeyWithCode`: `null` on failure, throws during lockout. */
export async function rustHiddenWrapWithCode(chatKey: Uint8Array, code: string): Promise<string | null> {
	const nowMs = Date.now();
	const key = await master().catch(() => null);
	if (!key) return null;
	const reply = await chatStateCall('hiddenWrapWithCode', { masterKey: key, chatKey, code, salt: salt(), nowMs });
	mirror(reply, nowMs);
	if (reply.lockedOut) throw new Error(LOCKOUT_MESSAGE);
	return reply.encryptedChatKey;
}

/** `encryptChatKeyWithCombinedSecret`: `null` while locked. */
export async function rustHiddenWrap(chatKey: Uint8Array): Promise<string | null> {
	return (await chatStateCall('hiddenWrap', { chatKey })).encryptedChatKey;
}

/** `decryptChatKeyWithCombinedSecret`. */
export async function rustHiddenUnwrap(encryptedChatKey: string): Promise<Uint8Array | null> {
	return (await chatStateCall('hiddenUnwrap', { encryptedChatKey })).chatKey;
}

/** `tryDecryptChatKey`. */
export async function rustHiddenTryDecrypt(encryptedChatKey: string): Promise<{ chatKey: Uint8Array | null; isHidden: boolean; isHiddenCandidate: boolean }> {
	const reply = await chatStateCall('hiddenClassify', { masterKey: await master(), encryptedChatKey });
	const cls: HiddenClass = reply.class;
	if (cls === 'normal') return { chatKey: reply.chatKey, isHidden: false, isHiddenCandidate: false };
	if (cls === 'hidden') return { chatKey: reply.chatKey, isHidden: true, isHiddenCandidate: true };
	return { chatKey: null, isHidden: false, isHiddenCandidate: true };
}

/** `hideChat` decision (the caller persists, syncs and caches). */
export async function rustHiddenPlanHide(cachedChatKey: Uint8Array | null, encryptedChatKey: string | null): Promise<HiddenPlanReply> {
	return chatStateCall('hiddenPlanHide', { masterKey: await master(), cachedChatKey, encryptedChatKey });
}

/** `unhideChat` re-wrap with the master key; `null` when it cannot open. */
export async function rustHiddenUnhide(encryptedChatKey: string): Promise<string | null> {
	return (await chatStateCall('hiddenUnhide', { masterKey: await master(), encryptedChatKey })).encryptedChatKey;
}

/** `lockHiddenChats`: drops the Worker vault (secret zeroized). */
export async function rustHiddenLock(): Promise<void> {
	mirror(await chatStateCall('hiddenLock', { nowMs: Date.now() }), Date.now());
}
