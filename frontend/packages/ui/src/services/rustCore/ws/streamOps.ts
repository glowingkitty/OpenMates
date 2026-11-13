/**
 * Stateful AI stream assembler ops of the shared Rust core Worker `ws` unit.
 *
 * Rust (packages/openmates-rust/src/web_stream/assembler.rs) keeps the per-account
 * stream state in the Worker realm: the buffered thinking stream, the recovery
 * final-event timestamps and the final-chunk completion plan. The ws unit mounts
 * `createStreamHandlers` with one line; the page receives small render-ready
 * decisions and never holds the stream state. Not an own namespace: the state
 * must not live on the pre-bind, stateless `sync` unit.
 */
import { UnitRefusal, type UnitHandlers, type UnitProtocol } from '../host/unitPort';

type JsonRecord = Record<string, unknown>;

export type StreamFinalPlan =
	| { action: 'ignore'; reason: 'awaiting' | 'stale' }
	| { action: 'final'; status: 'cancelled' | 'timed_out' | 'completed'; matched: boolean; userMessageId: string | null };

export interface StreamUnitProtocol extends UnitProtocol {
	thinkingChunk: { request: { message_id?: string; task_id?: string; chat_id: string; content?: string }; response: { message_id: string } };
	thinkingComplete: {
		request: { message_id?: string; task_id?: string; signature?: string | null; total_tokens?: number | null };
		response: { message_id: string; chat_id?: string; fields: JsonRecord | null };
	};
	finalTimestampRecord: { request: { event: JsonRecord; now: number }; response: { recorded: boolean; createdAt?: number } };
	finalTimestampGet: {
		request: { chat_id: string; message_id: string; job_id: string; turn_id: string; now: number };
		response: { createdAt: number | null };
	};
	finalChunkPlan: {
		request: { payload: JsonRecord; activeTask: { taskId: string; userMessageId: string } | null };
		response: StreamFinalPlan;
	};
	reset: { request: JsonRecord; response: { ok: true } };
}

/** Worker module export (JSON text in, JSON text out) of browser_stream.rs. */
export interface StreamBinding {
	stream_assembler_op(op: string, input: string): string;
}

/** Operations the assembler serves, in protocol order. */
export const STREAM_OPS: readonly (keyof StreamUnitProtocol & string)[] = /* @__PURE__ */ Object.freeze([
	'thinkingChunk', 'thinkingComplete', 'finalTimestampRecord', 'finalTimestampGet', 'finalChunkPlan', 'reset',
]);

export function isStreamBinding(value: unknown): value is StreamBinding {
	return typeof value === 'object' && value !== null && typeof (value as StreamBinding).stream_assembler_op === 'function';
}

export function createStreamHandlers(binding: StreamBinding): UnitHandlers<StreamUnitProtocol> {
	const handlers: Record<string, (payload: unknown) => unknown> = {};
	for (const op of STREAM_OPS) {
		handlers[op] = (payload) => {
			if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
			try {
				return JSON.parse(binding.stream_assembler_op(op, JSON.stringify(payload)));
			} catch {
				// A thrown JsValue is the Rust `protocol` code.
				throw new UnitRefusal('protocol');
			}
		};
	}
	return handlers as UnitHandlers<StreamUnitProtocol>;
}
