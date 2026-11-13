/**
 * Selection guards of Chats.svelte as pure decisions (flag-off path; with
 * VITE_OPENMATES_RUST_CORE the chatState unit decides, see
 * packages/openmates-rust/src/web_chat_state/selection.rs).
 */
export interface GlobalSelectedFacts {
	selected: string | null;
	newId: string;
	/** activeChatStore value; null means the user is in new-chat mode. */
	active: string | null;
}
export interface GlobalSelectedPlan {
	setSelected: boolean;
	writeStore: boolean;
}

