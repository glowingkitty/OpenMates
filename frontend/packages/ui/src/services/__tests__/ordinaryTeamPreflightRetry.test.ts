import { webcrypto } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { retainOrReuseOrdinaryTeamPreflight } from "../ordinaryTeamPreflightRetry";

beforeAll(() => vi.stubGlobal("crypto", webcrypto));
afterAll(() => vi.unstubAllGlobals());

function ordinaryTeamRetryFixture() {
	const values = new Map<string, string>();
	const storage = {
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => { values.set(key, value); },
	};
	const identity = {
		accountId: "sender-account", teamId: "team-1", chatId: "chat-1", messageId: "message-1",
		content: "private ordinary message", senderName: "Alice", role: "user" as const,
		createdAt: 100, chatKey: new Uint8Array(32).fill(7), encryptedChatKey: "wrapped-key",
	};
	const candidate = {
		protocol_version: 1, team_id: "team-1", chat_id: "chat-1", message_id: "message-1",
		turn_id: "turn-original", encrypted_chat_key: "wrapped-key", expected_messages_v: 0,
		encrypted_chat_metadata: { encrypted_title: "title-cipher-original", encrypted_chat_key: "wrapped-key" },
		encrypted_user_message: { client_message_id: "message-1", encrypted_content: "message-cipher-original" },
		inference_request: {
			team_id: "team-1", chat_id: "chat-1", traceparent: "trace-original",
			message: { message_id: "message-1", encrypted_content: "message-cipher-original" },
			encrypted_embeds: [{ encrypted_content: "embed-cipher-original" }],
		},
	};
	return { values, storage, identity, candidate };
}

describe("ordinary Team preflight retry", () => {
	// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.message.identity-idempotent
	it("replays one exact ordinary Team preflight after a lost ACK", async () => {
		const { values, storage, identity, candidate } = ordinaryTeamRetryFixture();
		const first = await retainOrReuseOrdinaryTeamPreflight(identity, candidate, storage);
		const retry = {
			...candidate, turn_id: "turn-regenerated", expected_messages_v: 1,
			encrypted_chat_metadata: { encrypted_title: "title-cipher-regenerated", encrypted_chat_key: "wrapped-key" },
			encrypted_user_message: { client_message_id: "message-1", encrypted_content: "message-cipher-regenerated" },
			inference_request: {
				...candidate.inference_request, traceparent: "trace-regenerated",
				message: { message_id: "message-1", encrypted_content: "message-cipher-regenerated" },
			},
		};
		const replayed = await retainOrReuseOrdinaryTeamPreflight(identity, retry, storage);
		expect(replayed).toEqual(first);
		expect(replayed).toEqual(candidate);
		expect(values.size).toBe(1);
		expect(JSON.stringify(Array.from(values.values()))).not.toContain(identity.content);
	});

	// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
	it("rejects edited content, changed account or Team, and changed wrapped key", async () => {
		const { storage, identity, candidate } = ordinaryTeamRetryFixture();
		await retainOrReuseOrdinaryTeamPreflight(identity, candidate, storage);
		for (const changed of [
			{ content: "edited message" }, { accountId: "another-account" },
			{ teamId: "another-team" }, { encryptedChatKey: "another-wrapper" },
		]) {
			await expect(retainOrReuseOrdinaryTeamPreflight({ ...identity, ...changed }, candidate, storage))
				.rejects.toThrow();
		}
	});

	// contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
	it("stops before send when the retry snapshot cannot be persisted", async () => {
		const { identity, candidate } = ordinaryTeamRetryFixture();
		await expect(retainOrReuseOrdinaryTeamPreflight(identity, candidate, {
			getItem: () => null,
			setItem: () => { throw new Error("storage quota exceeded"); },
		})).rejects.toThrow("storage quota exceeded");
	});
});
