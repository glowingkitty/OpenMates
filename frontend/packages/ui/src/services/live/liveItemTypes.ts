/**
 * Types shared by the live-item facade, the live editors and the preview fake.
 * Mirrors docs/plans/live-collaboration-crdt/build-contract.md sections 1 and 5.
 * The values are opaque to the page: the Rust core decides, the page renders.
 */
export type LiveItemKind = 'doc' | 'sheet' | 'deck' | 'code';
export type LiveStatus = 'saved' | 'saving' | 'offline' | 'read_only' | 'access_revoked';

/** Local selection as Yjs relative positions (opaque bytes/JSON produced by the mirror binding). */
export interface LivePresence {
	/** Cursor payload the core seals and relays (`kind_cursor`). */
	kind_cursor?: unknown;
	[key: string]: unknown;
}

export interface LivePeer {
	user_id: string;
	display_name: string;
	color: string;
	kind_cursor?: unknown;
	/** Present when the peer is an assistant ("<mate> is editing here"). */
	mate_name?: string;
	/** Same as `mate_name` (the core may send either); set when the peer is an assistant. */
	mate?: string;
	/** Structured selection of a sheet or deck peer (`{row_id,col_id}` / `{slide_id,element_id}`). */
	cursor?: unknown;
}

export interface LiveEvents {
	liveRemoteUpdate: { itemId: string; bytes: Uint8Array };
	liveView: { itemId: string; view: unknown };
	livePresence: { itemId: string; peers: LivePeer[] };
	liveStatus: { itemId: string; status: LiveStatus };
	/** The core stored a version (session end, leaving the editor); `text` is its text form. */
	liveVersion: { itemId: string; version: number; text: string };
}
export type LiveEventName = keyof LiveEvents;

/** The calls the editors need from the core's live item (forwarding only). */
export interface LiveItemClient {
	/** `projectId`: the (Team) Project the item is opened in; checkpoints then use its scope. */
	liveOpen(itemId: string, kind: LiveItemKind, projectId?: string, teamId?: string): Promise<void>;
	liveApplyMirrorUpdate(itemId: string, bytes: Uint8Array): Promise<void>;
	liveApplyOp(itemId: string, op: unknown): Promise<void>;
	liveSetPresence(itemId: string, presence: LivePresence): Promise<void>;
	liveClose(itemId: string): Promise<void>;
	liveUndoLatestAssistant?(itemId: string): Promise<boolean>;
	liveRestoreVersion?(itemId: string, source: number, head: number): Promise<{ version: number; content: string }>;
	/** Subscribes to one worker event; returns the unsubscribe function. */
	on<E extends LiveEventName>(event: E, listener: (payload: LiveEvents[E]) => void): () => void;
}
