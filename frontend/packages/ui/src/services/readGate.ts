/**
 * Mark-as-read gate of `markWhenSettled` (chatReadState.ts) as a pure decision.
 * `pre` runs before the settle delay, `post` after it (the chat must still be
 * open). The flag-off path evaluates it here; with VITE_OPENMATES_RUST_CORE the
 * chatState unit decides (packages/openmates-rust/src/web_chat_state/unread.rs).
 */
export interface ReadGateFacts {
	stage: 'pre' | 'post';
	/** document.visibilityState === 'visible' */
	visible: boolean;
	/** The user explicitly marked the chat unread. */
	manual: boolean;
	hasUnread: boolean;
	/** The end of the newest reply is inside the chat viewport. */
	endVisible: boolean;
	/** Result of the caller's isChatStillOpen, null when it gave none. */
	stillOpen: boolean | null;
}

export function readGateAllows(facts: ReadGateFacts): boolean {
	if (facts.stage === 'post' && facts.stillOpen === false) return false;
	return facts.visible && !facts.manual && facts.hasUnread && facts.endVisible;
}
