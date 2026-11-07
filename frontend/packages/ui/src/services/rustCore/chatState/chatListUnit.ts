/**
 * `chatState` namespace installer of the shared Rust core Worker.
 *
 * Serves the chat-list ordering and grouping policy (chatListProtocol.ts) on the
 * unit port from the realm's single WASM binding. It holds no per-account state
 * and does no IO, so it is a pre-bind namespace. A malformed payload or any
 * binding rejection answers the fixed code `protocol` (the Rust boundary's only
 * code).
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import { createHiddenHandlers } from './hiddenOps';
import { createForkHandlers } from './forkOps';
import { createBookmarkHighlightHandlers } from './bookmarkHighlightOps';
import { CHAT_STATE_OPS, isChatListBinding, type ChatListBinding, type ChatStateUnitProtocol } from './chatListProtocol';

export function createChatStateHandlers(binding: ChatListBinding): UnitHandlers<ChatStateUnitProtocol> {
	const handlers: Record<string, (payload: unknown) => unknown> = {};
	for (const [op, exportName] of Object.entries(CHAT_STATE_OPS)) {
		handlers[op] = (payload) => {
			if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
			let json: string;
			try {
				json = binding[exportName](JSON.stringify(payload));
			} catch {
				throw new UnitRefusal('protocol');
			}
			return JSON.parse(json);
		};
	}
	return { ...handlers, ...createHiddenHandlers(binding), ...createForkHandlers(binding), ...createBookmarkHighlightHandlers(binding) } as unknown as UnitHandlers<ChatStateUnitProtocol>;
}

export function installChatStateUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isChatListBinding(context.binding)) throw new Error('unavailable');
	const port = context.ports[0];
	const stop = serveUnitPort<ChatStateUnitProtocol>(port, createChatStateHandlers(context.binding));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stop();
		port.close();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}
