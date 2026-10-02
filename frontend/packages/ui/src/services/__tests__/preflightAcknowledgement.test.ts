import { describe, expect, it, vi } from "vitest";
import {
	PreflightRejectionError,
	waitForPreflightAcknowledgement,
	type PreflightEventSource,
} from "../preflightAcknowledgement";

function eventSource() {
	const handlers = new Map<string, (payload: unknown) => void>();
	const source: PreflightEventSource = {
		on: (event, handler) => { handlers.set(event, handler); },
		off: (event, handler) => {
			if (handlers.get(event) === handler) handlers.delete(event);
		},
	};
	const emit = (event: string, payload: unknown) => handlers.get(event)?.(payload);
	return { source, emit, handlers };
}

describe("durable preflight acknowledgement", () => {
	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it("ignores another turn's stale error and accepts the current turn's ACK", async () => {
		const { source, emit, handlers } = eventSource();
		const pending = waitForPreflightAcknowledgement("turn-current", source, vi.fn());
		const resolved = vi.fn();
		void pending.then(resolved);

		emit("error", { code: "preflight_mismatch", turn_id: "turn-stale" });
		await Promise.resolve();
		expect(resolved).not.toHaveBeenCalled();
		expect(handlers.has("chat_turn_preflight_ack")).toBe(true);

		emit("chat_turn_preflight_ack", { turn_id: "turn-current", preflight_id: "committed-preflight" });
		await expect(pending).resolves.toEqual({ preflight_id: "committed-preflight" });
		expect(handlers.size).toBe(0);
	});

	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it("still handles a legacy error without turn_id", async () => {
		const { source, emit, handlers } = eventSource();
		const pending = waitForPreflightAcknowledgement("turn-current", source, vi.fn());
		emit("error", { code: "preflight_mismatch" });
		await expect(pending).rejects.toBeInstanceOf(PreflightRejectionError);
		expect(handlers.size).toBe(0);
	});
});
