/**
 * `chatState` unit protocol: hidden chats and forks (unitPort.ts wire v1).
 *
 * Hidden chats: the PBKDF2 combined secret, the 3-failure / 30 s lockout and the
 * wrap/unwrap/classify/hide/unhide decisions live in the shared Worker (one
 * `BrowserHiddenChatVault` per realm). The page sends the session master
 * CryptoKey (structured clone) only with the operations that need it and keeps
 * a boolean view mirror of the lock state. The combined secret never leaves the
 * Worker. Forks: message selection, re-encryption and the finalize payloads are
 * stateless Rust decisions; the page keeps IndexedDB and the socket.
 * spec: specifications/architecture/sync#sync.client.shared-rust-policy
 */
/** Lock state echoed by every hidden-chat operation so the page mirror stays exact. */
export interface HiddenLockView { unlocked: boolean; lockoutSeconds: number }

export type HiddenClass = 'normal' | 'hidden' | 'locked_candidate';
export type HiddenPlanReply =
	| { plan: 'needs_unlock' | 'already_hidden' | 'missing_key' }
	| { plan: 'hide'; encryptedChatKey: string; decryptedChatKey: Uint8Array | null };

// A type alias (not an interface) so the operation names stay literal keys of `UnitHandlers`.
export type HiddenForkUnitProtocol = {
	hiddenState: { request: { nowMs: number }; response: HiddenLockView };
	hiddenUnlock: {
		request: { masterKey: CryptoKey; code: string; salt: Uint8Array | null; encryptedChatKeys: string[]; verifiedEncryptedChatKey: string | null; nowMs: number };
		response: HiddenLockView & { success: boolean; decryptedCount: number; lockedOut: boolean };
	};
	hiddenWrapWithCode: {
		request: { masterKey: CryptoKey; chatKey: Uint8Array; code: string; salt: Uint8Array | null; nowMs: number };
		response: HiddenLockView & { encryptedChatKey: string | null; lockedOut: boolean };
	};
	hiddenWrap: { request: { chatKey: Uint8Array }; response: { encryptedChatKey: string | null } };
	hiddenUnwrap: { request: { encryptedChatKey: string }; response: { chatKey: Uint8Array | null } };
	hiddenClassify: { request: { masterKey: CryptoKey; encryptedChatKey: string }; response: { class: HiddenClass; chatKey: Uint8Array | null } };
	hiddenPlanHide: {
		request: { masterKey: CryptoKey; cachedChatKey: Uint8Array | null; encryptedChatKey: string | null };
		response: HiddenPlanReply;
	};
	hiddenUnhide: { request: { masterKey: CryptoKey; encryptedChatKey: string }; response: { encryptedChatKey: string | null } };
	hiddenLock: { request: { nowMs: number }; response: HiddenLockView };
	/** Drops the vault and its lockout unconditionally (logout, account switch). */
	hiddenRelease: { request: Record<string, never>; response: HiddenLockView };
	hiddenKeyUpdate: {
		request: { chatId: string; encryptedChatKey: string; messagesV?: number; titleV?: number; lastEdited?: number; nowSeconds: number };
		response: { payload: Record<string, unknown> };
	};
	forkNormalizeSelection: { request: { selectedText: string }; response: { value: string } };
	forkSelect: { request: { messagesJson: string; upToMessageId: string }; response: { ids: string[] } };
	forkReencryptBatch: { request: { messagesJson: string; newChatId: string; chatKey: Uint8Array }; response: { rows: Record<string, unknown>[] } };
	forkCopyField: { request: { sourceCiphertext: string | null; sourceKey: Uint8Array; newKey: Uint8Array }; response: { value: string | null } };
	forkEncryptTitle: { request: { title: string; chatKey: Uint8Array }; response: { value: string } };
	forkFinalize: {
		request: { chatJson: string; rowsJson: string };
		response: { record: Record<string, unknown>; payload: Record<string, unknown> };
	};
}
