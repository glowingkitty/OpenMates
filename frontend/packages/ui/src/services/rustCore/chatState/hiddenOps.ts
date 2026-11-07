/**
 * Worker-side hidden-chat operations of the `chatState` unit (spec:
 * specifications/architecture/sync#sync.client.shared-rust-policy (hidden-chat PIN wrapping has no assertion yet; see web-lanes.yml spec_gaps)). Wraps one
 * `BrowserHiddenChatVault` (created lazily with the first master CryptoKey the
 * page sends) so the combined secret stays inside the Worker. Binding rejections
 * are mapped to stable fields (`lockedOut`, `success`) exactly like the legacy
 * `hiddenChatService` results; chat keys cross only as the bytes the page already
 * caches today.
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { HiddenForkUnitProtocol, HiddenLockView } from './hiddenForkProtocol';
import { bindingCode, type HiddenChatVaultBinding } from './chatStateBinding';

type HiddenOpName = 'hiddenState' | 'hiddenUnlock' | 'hiddenWrapWithCode' | 'hiddenWrap' | 'hiddenUnwrap' | 'hiddenClassify'
	| 'hiddenPlanHide' | 'hiddenUnhide' | 'hiddenLock' | 'hiddenRelease' | 'hiddenKeyUpdate';

interface HiddenBinding {
	BrowserHiddenChatVault?: new (masterKey: CryptoKey) => HiddenChatVaultBinding;
	chat_state_hidden_key_update_payload?: (chatId: string, key: string, messagesV: number | undefined, titleV: number | undefined, edited: number | undefined, nowSeconds: number) => string;
}

export function createHiddenHandlers(raw: object): Pick<UnitHandlers<HiddenForkUnitProtocol>, HiddenOpName> {
	const binding = raw as HiddenBinding;
	let vault: HiddenChatVaultBinding | null = null;

	const open = (masterKey: CryptoKey): HiddenChatVaultBinding => {
		if (vault) return vault;
		if (typeof binding.BrowserHiddenChatVault !== 'function' || typeof masterKey !== 'object' || masterKey === null) throw new UnitRefusal('protocol');
		vault = new binding.BrowserHiddenChatVault(masterKey);
		return vault;
	};
	const view = (nowMs: number): HiddenLockView => ({
		unlocked: vault?.is_unlocked() ?? false,
		lockoutSeconds: vault ? vault.remaining_lockout_seconds(nowMs) : 0,
	});
	const bytes = (value: unknown): Uint8Array => {
		if (!(value instanceof Uint8Array)) throw new UnitRefusal('protocol');
		return value;
	};

	return {
		hiddenState: ({ nowMs }) => view(nowMs),
		async hiddenUnlock(request) {
			const target = open(request.masterKey);
			try {
				const count = await target.unlock(request.code, request.salt ?? undefined, request.encryptedChatKeys,
					request.verifiedEncryptedChatKey ?? undefined, request.nowMs);
				return { ...view(request.nowMs), success: true, decryptedCount: count, lockedOut: false };
			} catch (reason) {
				return { ...view(request.nowMs), success: false, decryptedCount: 0, lockedOut: bindingCode(reason) === 'locked' };
			}
		},
		async hiddenWrapWithCode(request) {
			const target = open(request.masterKey);
			try {
				const wrapped = await target.wrap_with_code(bytes(request.chatKey), request.code, request.salt ?? undefined, request.nowMs);
				return { ...view(request.nowMs), encryptedChatKey: wrapped, lockedOut: false };
			} catch (reason) {
				return { ...view(request.nowMs), encryptedChatKey: null, lockedOut: bindingCode(reason) === 'locked' };
			}
		},
		hiddenWrap({ chatKey }) {
			if (!vault || !vault.is_unlocked()) return { encryptedChatKey: null };
			try {
				return { encryptedChatKey: vault.wrap(bytes(chatKey)) };
			} catch {
				return { encryptedChatKey: null };
			}
		},
		hiddenUnwrap({ encryptedChatKey }) {
			return { chatKey: vault?.unwrap(encryptedChatKey) ?? null };
		},
		async hiddenClassify({ masterKey, encryptedChatKey }) {
			const result = await open(masterKey).classify(encryptedChatKey);
			return { class: result.class, chatKey: result.chatKey ?? null };
		},
		async hiddenPlanHide({ masterKey, cachedChatKey, encryptedChatKey }) {
			const plan = await open(masterKey).plan_hide(cachedChatKey ?? undefined, encryptedChatKey ?? undefined);
			return plan.plan === 'hide'
				? { plan: 'hide', encryptedChatKey: plan.encryptedChatKey, decryptedChatKey: plan.decryptedChatKey ?? null }
				: { plan: plan.plan };
		},
		async hiddenUnhide({ masterKey, encryptedChatKey }) {
			if (!vault?.is_unlocked()) return { encryptedChatKey: null };
			try {
				return { encryptedChatKey: (await open(masterKey).unhide(encryptedChatKey)).encryptedChatKey };
			} catch {
				return { encryptedChatKey: null };
			}
		},
		hiddenLock({ nowMs }) {
			vault?.lock();
			const state = view(nowMs);
			// A lockout survives a lock (like the web service); an idle vault is dropped so a
			// later account never reuses this master key handle.
			if (state.lockoutSeconds === 0) {
				vault?.free();
				vault = null;
			}
			return state;
		},
		hiddenRelease() {
			// Logout and account switch: the secret, the master-key handle and any lockout
			// belong to the previous account, so nothing may survive (unlike hiddenLock).
			if (vault) {
				vault.lock();
				vault.free();
				vault = null;
			}
			return { unlocked: false, lockoutSeconds: 0 };
		},
		hiddenKeyUpdate(request) {
			if (typeof binding.chat_state_hidden_key_update_payload !== 'function') throw new UnitRefusal('protocol');
			return {
				payload: JSON.parse(binding.chat_state_hidden_key_update_payload(request.chatId, request.encryptedChatKey,
					request.messagesV || undefined, request.titleV || undefined, request.lastEdited || undefined, request.nowSeconds)),
			};
		},
	};
}
