/**
 * Worker-side fork operations of the `chatState` unit (spec:
 * specifications/features/chats#chats.fork.non-destructive-boundary). Stateless
 * wrappers over the `chat_state_fork_*` exports; messages and rows travel as JSON
 * text exactly as the binding consumes them. A binding rejection answers the
 * fixed code `protocol` (or the Rust error code when it is a stable lowercase
 * code) and never carries message text.
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { HiddenForkUnitProtocol } from './hiddenForkProtocol';
import { bindingCode } from './chatStateBinding';

type ForkOpName = 'forkNormalizeSelection' | 'forkSelect' | 'forkReencryptBatch' | 'forkCopyField' | 'forkEncryptTitle' | 'forkFinalize';

interface ForkBinding {
	chat_state_normalize_explain_selection?(selected: string): string;
	chat_state_fork_select?(messagesJson: string, upTo: string): string[];
	chat_state_fork_reencrypt_batch?(messagesJson: string, newChatId: string, chatKey: Uint8Array): string;
	chat_state_fork_copy_field?(source: string | undefined, sourceKey: Uint8Array, newKey: Uint8Array): string | undefined;
	chat_state_fork_encrypt_title?(title: string, chatKey: Uint8Array): string;
	chat_state_fork_finalize?(chatJson: string, rowsJson: string): string;
}

const STABLE_CODE = /^[a-z][a-z0-9_]{0,63}$/;

/** Runs a binding call; Rust error codes pass through, web error messages (free text) collapse to `fork_refused`. */
function guarded<T>(run: () => T): T {
	try {
		return run();
	} catch (reason) {
		const code = bindingCode(reason);
		throw new UnitRefusal(STABLE_CODE.test(code) ? code : 'fork_refused');
	}
}

function need<K extends keyof ForkBinding>(binding: ForkBinding, name: K): NonNullable<ForkBinding[K]> {
	const fn = binding[name];
	if (typeof fn !== 'function') throw new UnitRefusal('protocol');
	return fn.bind(binding) as NonNullable<ForkBinding[K]>;
}

export function createForkHandlers(raw: object): Pick<UnitHandlers<HiddenForkUnitProtocol>, ForkOpName> {
	const binding = raw as ForkBinding;
	return {
		forkNormalizeSelection: ({ selectedText }) => ({ value: guarded(() => need(binding, 'chat_state_normalize_explain_selection')(selectedText)) }),
		forkSelect: ({ messagesJson, upToMessageId }) => ({ ids: guarded(() => need(binding, 'chat_state_fork_select')(messagesJson, upToMessageId)) }),
		forkReencryptBatch: ({ messagesJson, newChatId, chatKey }) =>
			({ rows: guarded(() => JSON.parse(need(binding, 'chat_state_fork_reencrypt_batch')(messagesJson, newChatId, chatKey))) }),
		forkCopyField: ({ sourceCiphertext, sourceKey, newKey }) =>
			({ value: guarded(() => need(binding, 'chat_state_fork_copy_field')(sourceCiphertext ?? undefined, sourceKey, newKey)) ?? null }),
		forkEncryptTitle: ({ title, chatKey }) => ({ value: guarded(() => need(binding, 'chat_state_fork_encrypt_title')(title, chatKey)) }),
		forkFinalize: ({ chatJson, rowsJson }) => guarded(() => JSON.parse(need(binding, 'chat_state_fork_finalize')(chatJson, rowsJson))),
	};
}
