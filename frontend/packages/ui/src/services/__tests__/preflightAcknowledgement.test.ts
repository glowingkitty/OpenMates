import { describe, expect, it, vi } from "vitest";
import {
	PreflightRejectionError,
	recoverTimedOutAdmission,
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
	it.each(["preflight_mismatch", "existing_chat_metadata_forbidden"])("rejects %s promptly and removes pending listeners", async (code) => {
		const { source, emit, handlers } = eventSource();
		const pending = waitForPreflightAcknowledgement("turn-current", source, vi.fn());
		emit("error", { code });
		await expect(pending).rejects.toBeInstanceOf(PreflightRejectionError);
		await expect(pending).rejects.toHaveProperty("code", code);
		expect(handlers.size).toBe(0);
	});

	// contract-test: supporting surface=gui.web assertions=message-input.send.ownership
	it("cancels a waiter when the admission frame could not be sent", async () => {
		const { source, handlers } = eventSource();
		const controller = new AbortController();
		const pending = waitForPreflightAcknowledgement("turn-current", source, vi.fn(), controller.signal);
		controller.abort();
		await expect(pending).rejects.toHaveProperty("name", "AbortError");
		expect(handlers.size).toBe(0);
	});


	// contract-test: supporting surface=gui.web assertions=message-input.send.ownership
	it("requires the exact turn ID before releasing private context", async () => {
		const { source, emit, handlers } = eventSource();
		const pending = waitForPreflightAcknowledgement("turn-current", source, vi.fn(), undefined, true);
		const resolved = vi.fn();
		void pending.then(resolved);
		emit("chat_turn_preflight_ack", { preflight_id: "unbound" });
		emit("chat_turn_preflight_ack", { turn_id: "turn-other", preflight_id: "other" });
		await Promise.resolve();
		expect(resolved).not.toHaveBeenCalled();
		expect(handlers.has("chat_turn_preflight_ack")).toBe(true);
		emit("chat_turn_preflight_ack", { turn_id: "turn-current", preflight_id: "matched" });
		await expect(pending).resolves.toEqual({ preflight_id: "matched" });
	});

	// contract-test: supporting surface=gui.web assertions=chats.send.immediate-admission,message-input.send.ownership
	it("finishes a pending retry status write before reconnect can mark the row synced", async () => {
		let releaseWrite!: () => void;
		let status = "sending";
		const reconnect = vi.fn(() => { status = "synced"; });
		const persistWaiting = vi.fn(() => new Promise<void>((resolve) => {
			releaseWrite = () => { status = "waiting_for_internet"; resolve(); };
		}));
		const recovery = recoverTimedOutAdmission({ isCurrent: () => true, persistWaiting, reconnect });
		expect(persistWaiting).toHaveBeenCalledOnce();
		expect(reconnect).not.toHaveBeenCalled();
		releaseWrite();
		await recovery;
		expect(reconnect).toHaveBeenCalledOnce();
		expect(status).toBe("synced");
	});

	// contract-test: supporting surface=gui.web assertions=message-input.send.ownership
	it("does not reconnect another owner after a pending status write", async () => {
		let releaseWrite!: () => void;
		let current = true;
		const reconnect = vi.fn();
		const recovery = recoverTimedOutAdmission({
			isCurrent: () => current,
			persistWaiting: () => new Promise<void>((resolve) => { releaseWrite = resolve; }),
			reconnect,
		});
		current = false;
		releaseWrite();
		await recovery;
		expect(reconnect).not.toHaveBeenCalled();
	});

});
