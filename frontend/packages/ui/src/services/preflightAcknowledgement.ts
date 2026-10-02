/** Wait for the durable preflight result from the turn that opened this waiter. */
const CHAT_PREFLIGHT_TIMEOUT_MS = 60_000;
const CHAT_PREFLIGHT_TIMEOUT_MESSAGE = "Encrypted chat preflight acknowledgement timed out.";
const PREFLIGHT_ERROR_CODES = new Set([
	"client_update_required", "durable_preflight_failed", "immutable_chat_key_mismatch",
	"preflight_expired", "preflight_mismatch", "preflight_required",
	"recovery_key_mismatch", "message_identity_mismatch", "team_chat_scope_mismatch",
	"version_conflict"
]);

type EventHandler = (payload: unknown) => void;
export interface PreflightEventSource {
	on(event: string, handler: EventHandler): void;
	off(event: string, handler: EventHandler): void;
}
type RecordDebugStep = (step: string, details?: Record<string, unknown>) => void;

export class PreflightRejectionError extends Error {
	constructor(readonly code: string, message: string) { super(message); }
}

export function isPreflightAcknowledgementTimeout(error: unknown): boolean {
	return error instanceof Error && error.message === CHAT_PREFLIGHT_TIMEOUT_MESSAGE;
}

export function waitForPreflightAcknowledgement(
	turnId: string,
	events: PreflightEventSource,
	recordDebugStep: RecordDebugStep,
): Promise<{ preflight_id: string }> {
	return new Promise((resolve, reject) => {
		recordDebugStep("preflight_waiter_registered", { turnId });
		const timeout = globalThis.setTimeout(() => {
			recordDebugStep("preflight_ack_timeout", { turnId });
			cleanup();
			reject(new Error(CHAT_PREFLIGHT_TIMEOUT_MESSAGE));
		}, CHAT_PREFLIGHT_TIMEOUT_MS);
		const handleAck = (payload: unknown) => {
			const ack = payload as { turn_id?: string; preflight_id?: string };
			if (ack.turn_id && ack.turn_id !== turnId) {
				recordDebugStep("preflight_ack_ignored_turn_mismatch", {
					turnId, receivedTurnId: ack.turn_id
				});
				return;
			}
			if (!ack.preflight_id) {
				recordDebugStep("preflight_ack_missing_id", { turnId });
				cleanup();
				reject(new Error("Encrypted chat preflight acknowledgement omitted preflight_id."));
				return;
			}
			recordDebugStep("preflight_ack_received", { turnId });
			cleanup();
			resolve({ preflight_id: ack.preflight_id });
		};
		const handleError = (payload: unknown) => {
			const error = payload as { code?: string; message?: string; turn_id?: string };
			if (!error.code || !PREFLIGHT_ERROR_CODES.has(error.code)) return;
			// Old servers omit turn_id; when present it must match this waiter.
			if (error.turn_id && error.turn_id !== turnId) return;
			recordDebugStep("preflight_error_received", { turnId, code: error.code });
			cleanup();
			reject(new PreflightRejectionError(error.code, error.message || "Encrypted chat preflight was rejected."));
		};
		const handleDebug = (payload: unknown) => {
			const debug = payload as { turn_id?: string; phase?: string };
			if (debug.turn_id !== turnId || !debug.phase) return;
			recordDebugStep(`preflight_server_${debug.phase}`, { turnId });
		};
		const cleanup = () => {
			globalThis.clearTimeout(timeout);
			events.off("chat_turn_preflight_ack", handleAck);
			events.off("error", handleError);
			events.off("chat_turn_preflight_debug", handleDebug);
		};
		events.on("chat_turn_preflight_ack", handleAck);
		events.on("error", handleError);
		events.on("chat_turn_preflight_debug", handleDebug);
	});
}
