/**
 * Page event emitted after the shared core applied server frames (or admitted a
 * chat) and its message window for `chatId` changed. Carries only the chat id and
 * the core's `messagesV` counter, never content; consumers re-read through the
 * core. No UI consumer yet.
 */
export interface ChatWindowChanged { readonly chatId: string; readonly messagesV: number }
type Listener = (event: ChatWindowChanged) => void;

const listeners = new Set<Listener>();

/** Subscribes to `chatWindowChanged`; returns the unsubscribe. */
export function onChatWindowChanged(listener: Listener): () => void {
	listeners.add(listener);
	return () => { listeners.delete(listener); };
}

/** Emits to a snapshot of the listeners; a throwing listener never blocks the rest. */
export function emitChatWindowChanged(event: ChatWindowChanged): void {
	for (const listener of [...listeners]) {
		try { listener(event); } catch { console.warn('[RustCore] chatWindowChanged listener failed'); }
	}
}
