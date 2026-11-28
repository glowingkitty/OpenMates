/**
 * `live` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 * The core owns the replica of every open live item (client/live/); the page only
 * forwards typed calls and receives the core's events (unit-pushed `event` messages).
 */
import type { UnitProtocol } from '../host/unitPort';
import type { LiveItemKind, LivePresence } from '../../live/liveItemTypes';

export interface LiveItemUnitProtocol extends UnitProtocol {
	liveScanRecovery: { request: undefined; response: true };
	liveOpen: { request: { itemId: string; kind: LiveItemKind; projectId?: string; teamId?: string }; response: true };
	liveApplyMirrorUpdate: { request: { itemId: string; bytes: Uint8Array }; response: true };
	liveApplyOp: { request: { itemId: string; op: unknown }; response: true };
	liveSetPresence: { request: { itemId: string; presence: LivePresence }; response: true };
	liveClose: { request: { itemId: string }; response: true };
	liveOpenTeamRevisionContent: {
		request: { itemId: string; teamId: string; version: number; ciphertext: string; displayText: boolean };
		response: string | null;
	};
	liveUndoLatestAssistant: { request: { itemId: string }; response: boolean };
	liveRestoreVersion: {
		request: { itemId: string; source: number; head: number };
		response: { version: number; content: string };
	};
	/** One server frame from the page's socket; `true` when the core consumed it. */
	liveFrame: { request: { type: string; payload: unknown }; response: boolean };
	liveConnected: { request: { connected: boolean }; response: true };
	liveSetUser: { request: { userId: string }; response: true };
}

/** Calls on the admitted core client (browser_live_item.rs); each runs the core's `LiveDriver`. */
export interface LiveCoreClient {
	live_scan_recovery(connection: string, handle: string, generation: number): Promise<void>;
	live_open(connection: string, handle: string, generation: number, itemId: string, kind: string, projectId?: string, teamId?: string): Promise<void>;
	live_apply_mirror_update(connection: string, handle: string, generation: number, itemId: string, bytes: Uint8Array): Promise<void>;
	live_apply_op(connection: string, handle: string, generation: number, itemId: string, opJson: string): Promise<void>;
	live_set_presence(connection: string, handle: string, generation: number, itemId: string, presenceJson: string): Promise<void>;
	live_close(connection: string, handle: string, generation: number, itemId: string): Promise<void>;
	live_open_team_revision_content(handle: string, generation: number, teamId: string, itemId: string,
		version: number, ciphertext: string, displayText: boolean): Promise<string | undefined>;
	live_undo_latest_assistant(connection: string, handle: string, generation: number, itemId: string): Promise<boolean>;
	live_restore_version(connection: string, handle: string, generation: number, itemId: string, source: number, head: number): Promise<{ version: number; content: string }>;
	live_set_connected(connection: string, connected: boolean): Promise<void>;
	live_tick(connection: string): Promise<void>;
	live_on_frame(connection: string, messageType: string, payloadJson: string): Promise<boolean>;
}

export interface LiveItemBinding {
	/** `sink` receives (eventName, payload); `send` writes one frame (type, payloadJson) on the page's socket. */
	live_configure(
		connection: string,
		sink: (event: string, payload: unknown) => void,
		send: (type: string, payloadJson: string) => void,
		listOutbox: (prefix: string) => Promise<string[]>,
		readOutbox: (key: string) => Promise<string | null>,
		compareAndPutOutbox: (key: string, expected: string | null, next: string | null) => Promise<boolean>
	): void;
	live_dispose(connection: string): void;
	live_set_user(connection: string, userId: string): void;
	live_is_frame(messageType: string): boolean;
}

export function isLiveItemBinding(value: unknown): value is LiveItemBinding {
	return typeof value === 'object' && value !== null && typeof (value as Record<string, unknown>).live_configure === 'function';
}
