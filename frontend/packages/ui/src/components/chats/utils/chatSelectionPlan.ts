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

/** `globalChatSelected` mirror: rewrite the store only while another chat is active. */
export function planGlobalSelected(f: GlobalSelectedFacts): GlobalSelectedPlan {
	const setSelected = f.selected !== f.newId;
	return { setSelected, writeStore: setSelected && f.active !== null && f.active !== f.newId };
}

/** A persisted draft must not activate while a different chat is selected. */
export function skipDraftActivation(selected: string | null, persisted: string): boolean {
	return !!selected && selected !== persisted;
}
