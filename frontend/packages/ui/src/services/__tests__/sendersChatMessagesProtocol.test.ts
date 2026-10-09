/**
 * frontend/packages/ui/src/services/__tests__/sendersChatMessagesProtocol.test.ts
 *
 * Regression tests for protocol fenced blocks in the client message sender.
 * Interactive question answers are chat protocol, not user-authored code embeds.
 */

import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../websocketService", () => ({
  webSocketService: {
    forceReconnect: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    off: vi.fn(),
    on: vi.fn(),
    sendMessage: vi.fn(),
  },
}));
// Imported preview/speech services register listeners on this singleton at
// module load. The protocol helper tests do not start the sync service.
vi.mock("../chatSyncService", () => ({ chatSyncService: new EventTarget() }));
import { webSocketService } from "../websocketService";
import { chatDB } from "../db";
import { EmbedStore } from "../embedStore";
import * as cryptoService from "../cryptoService";
import { computeSHA256 } from "../../message_parsing/utils";
import {
	buildTeamMessageTransport,
	canonicalUserMessageForSend,
	reconcileOptimisticUserCiphertext,
	reconcileOptimisticUserCreatedAt,
	nextPersonalUserCreatedAt,
	stableMessageEmbedId,
	applyTeamPreflightScope,
  requireEmbedOwnerId,
	retainOrReuseEncryptedMessageEmbedBundle,
	persistRetainedMessageEmbedKeys,
	verifyRetainedMessageEmbedHeads,
	retainOrReuseDurableTurnPreflight,
	watchDurableTurnPreflightConfirmation,
	watchMessageEmbedBundleConfirmation,
	selectRequiredMessageEmbedEntries,
	isPreflightAcknowledgementTimeout,
  preflightExpectedMessagesVersion,
	resolveHistoryCategoryForInference,
  shouldIncludePreflightChatMetadata,
	shouldSkipClientCodeBlockExtraction,
} from "../sendersChatMessages";
import { shouldUpdateMessage } from "../db/messageOperations";

const TEAM_MESSAGE = {
	message_id: "message-2",
	chat_id: "chat-1",
	role: "user" as const,
	content: "hello team",
	status: "sending" as const,
	created_at: 200,
	sender_name: "Alice",
};

describe("sendersChatMessages protocol fences", () => {
	describe("durable embed bundle HMAC", () => {
		let previousCrypto: Crypto;
		beforeEach(() => {
			previousCrypto = globalThis.crypto;
			Object.defineProperty(globalThis, "crypto", {
				value: webcrypto, writable: true, configurable: true,
			});
		});
		afterEach(() => {
			Object.defineProperty(globalThis, "crypto", {
				value: previousCrypto, writable: true, configurable: true,
			});
		});
	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,code-run.artifacts.chat-bound-versioned
	it("reuses the same code and table head IDs for an unchanged message retry", async () => {
		const secret = new Uint8Array(32).fill(3);
		const code = await stableMessageEmbedId(secret, "chat", "message", "code", 12, "```js\nconst x = 1\n```");
		expect(await stableMessageEmbedId(secret, "chat", "message", "code", 12, "```js\nconst x = 1\n```")).toBe(code);
		expect(code).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-8[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
		expect(await stableMessageEmbedId(secret, "chat", "message", "sheet", 12, "```js\nconst x = 1\n```")).not.toBe(code);
		expect(await stableMessageEmbedId(secret, "chat", "message", "code", 12, "```js\nconst x = 2\n```")).not.toBe(code);
		expect(await stableMessageEmbedId(secret, "other-chat", "message", "code", 12, "```js\nconst x = 1\n```")).not.toBe(code);
		expect(await stableMessageEmbedId(new Uint8Array(32).fill(4), "chat", "message", "code", 12, "```js\nconst x = 1\n```")).not.toBe(code);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,teams.chat.encrypted-until-invoked
	it("encrypts the same embed reference sent to inference and ordinary Team preflight", async () => {
		const embedId = await stableMessageEmbedId(new Uint8Array(32).fill(5), "chat-1", "message-2", "code", 0, "```js\nconst x = 1\n```");
		const finalContent = `Look at this:\n\n\`\`\`json\n{"type": "code", "embed_id": "${embedId}"}\n\`\`\``;
		const canonical = canonicalUserMessageForSend({ ...TEAM_MESSAGE, content: "Look at this:\n\n```js\nconst x = 1\n```" }, finalContent);
		const encrypt = vi.fn(async (value: typeof canonical) => `cipher:${value.content}`);
		const ciphertext = await encrypt(canonical);
		expect(ciphertext).toContain(embedId);
		expect(ciphertext).not.toContain("const x = 1");
		const team = buildTeamMessageTransport({ message: canonical, content: finalContent,
			encryptedContent: ciphertext, history: [] });
		expect(team.message.encrypted_content).toBe(ciphertext);
		expect(team.message).not.toHaveProperty("content");
		const plain = canonicalUserMessageForSend({ ...TEAM_MESSAGE, content: "unchanged" }, "unchanged");
		expect(plain.content).toBe("unchanged");
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.embeds.gated-send
	it("reconciles the optimistic row to exact canonical ciphertext before a synced reload", async () => {
		const row: Record<string, unknown> = {
			message_id: "message-2", chat_id: "chat-1", role: "user", created_at: 200,
			status: "synced", encrypted_content: "original-editor-fence-cipher",
			pending_encrypted_embed_bundle_v1: "sealed-bundle",
			pending_encrypted_turn_preflight_v1: "sealed-turn",
		};
		const transaction = {
			error: null,
			oncomplete: null as (() => void) | null,
			onabort: null as (() => void) | null,
			onerror: null as (() => void) | null,
			abort() { queueMicrotask(() => this.onabort?.()); },
			objectStore: () => ({
				get: () => {
					const request = { result: row, error: null, onsuccess: null as (() => void) | null,
						onerror: null as (() => void) | null };
					queueMicrotask(() => request.onsuccess?.());
					return request;
				},
				put: (next: Record<string, unknown>) => {
					Object.assign(row, next);
					queueMicrotask(() => transaction.oncomplete?.());
				},
			}),
		};
		const canonicalCiphertext = "sealed-embed-reference-cipher";
		await reconcileOptimisticUserCiphertext("chat-1", "message-2", 200,
			canonicalCiphertext, async () => transaction as unknown as IDBTransaction);
		expect(row.encrypted_content).toBe(canonicalCiphertext);
		expect(row).not.toHaveProperty("content");
		expect(row.status).toBe("synced");
		expect(row.pending_encrypted_embed_bundle_v1).toBe("sealed-bundle");
		expect(row.pending_encrypted_turn_preflight_v1).toBe("sealed-turn");
		// A phased-sync delivered row cannot repair a stale synced local row.
		expect(shouldUpdateMessage(row as never, { ...row, status: "delivered" } as never)).toBe(false);
	});

	// contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
	it("orders immediate personal follow-ups after committed replies without changing later wall time", async () => {
		const rows = [
			{ message_id: "user-1", status: "synced", created_at: 100 },
			{ message_id: "assistant-1", status: "synced", created_at: 101 },
			{ message_id: "user-2", status: "sending", created_at: 100 },
		] as const;
		const second = nextPersonalUserCreatedAt(100, 100, [...rows], "user-2");
		expect(second).toBe(102);
		const third = nextPersonalUserCreatedAt(100, 100, [
			...rows, { message_id: "assistant-2", status: "synced", created_at: 103 },
		], "user-3");
		expect(third).toBe(104);
		expect(nextPersonalUserCreatedAt(200, 200, [...rows], "user-later")).toBe(200);

		const row = { message_id: "user-2", chat_id: "chat-1", role: "user", status: "sending",
			created_at: 100, encrypted_content: "sealed-user", pending_encrypted_turn_preflight_v1: "sealed-turn" };
		const transaction = {
			error: null, oncomplete: null as (() => void) | null, onabort: null as (() => void) | null,
			onerror: null as (() => void) | null,
			abort() { queueMicrotask(() => this.onabort?.()); },
			objectStore: () => ({
				get: () => {
					const request = { result: row, error: null, onsuccess: null as (() => void) | null,
						onerror: null as (() => void) | null };
					queueMicrotask(() => request.onsuccess?.());
					return request;
				},
				put: (next: typeof row) => {
					Object.assign(row, next);
					queueMicrotask(() => transaction.oncomplete?.());
				},
			}),
		};
		await reconcileOptimisticUserCreatedAt("chat-1", "user-2", 100, second,
			async () => transaction as unknown as IDBTransaction);
		expect(row).toMatchObject({ created_at: 102, encrypted_content: "sealed-user",
			pending_encrypted_turn_preflight_v1: "sealed-turn" });
	});

	// contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.persistence.client-encrypted
	it("replays the exact sealed turn, user ciphertext, and commitment after a lost ACK", async () => {
		const identity = {
			accountId: "owner", chatId: "chat", messageId: "message", createdAt: 12,
			finalContent: "sealed ref", chatKey: new Uint8Array(32).fill(9),
			encryptedChatKey: "wrapped-chat-key", recoveryPublicKey: "recovery-public-key",
		};
		const original = {
			chat_id: "chat", message_id: "message", turn_id: "original-turn",
			expected_messages_v: 6,
			encrypted_chat_key: "wrapped-chat-key", recovery_public_key: "recovery-public-key",
			inference_commitment: "original-commitment",
			encrypted_user_message: { chat_id: "chat", client_message_id: "message", role: "user",
				encrypted_content: "original-user-cipher" },
			inference_request: { chat_id: "chat", turn_id: "original-turn",
				message: { message_id: "message", content: "sealed ref" } },
		};
		let raw: string | null = null;
		const storage = {
			read: async () => raw,
			commit: async (candidate: string) => { raw ??= candidate; return raw; },
		};
		const first = await retainOrReuseDurableTurnPreflight(identity, original, storage);
		expect(first.payload).toEqual(original);
		expect(raw).not.toContain("sealed ref");
		expect(raw).not.toContain("original-user-cipher");
		const retryCandidate = { ...original, turn_id: "fresh-turn",
			inference_commitment: "fresh-commitment",
			encrypted_user_message: { ...original.encrypted_user_message,
				encrypted_content: "fresh-user-cipher" } };
		const retry = await retainOrReuseDurableTurnPreflight(identity, retryCandidate, storage);
		expect(retry.sealed).toBe(first.sealed);
		expect(retry.payload).toEqual(original);
		await expect(retainOrReuseDurableTurnPreflight({ ...identity, finalContent: "changed ref" }, retryCandidate, storage))
			.rejects.toThrow("changed account, key, scope, content, or ciphertext");
		await expect(retainOrReuseDurableTurnPreflight({ ...identity, accountId: "another-owner" }, retryCandidate, storage))
			.rejects.toThrow("changed account, key, scope, content, or ciphertext");
	});

	// contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.persistence.client-encrypted
	it("retains the sealed preflight across legacy and stale ACKs, clearing only admitted turn confirmation", async () => {
		const clear = vi.fn(async () => undefined);
		watchDurableTurnPreflightConfirmation("ack-chat", "ack-message", 7, clear);
		const registrations = vi.mocked(webSocketService.on).mock.calls;
		const callback = [...registrations].reverse().find(([event]) => event === "chat_message_confirmed")?.[1];
		expect(callback).toBeTypeOf("function");
		(callback as (payload: unknown) => void)({ chat_id: "ack-chat", message_id: "ack-message", status: "synced" });
		(callback as (payload: unknown) => void)({ chat_id: "ack-chat", message_id: "ack-message", new_messages_v: 6 });
		(callback as (payload: unknown) => void)({ chat_id: "other-chat", message_id: "ack-message", new_messages_v: 7 });
		expect(clear).not.toHaveBeenCalled();
		(callback as (payload: unknown) => void)({ chat_id: "ack-chat", message_id: "ack-message", new_messages_v: 7 });
		expect(clear).toHaveBeenCalledOnce();
		expect(webSocketService.off).toHaveBeenCalledWith("chat_message_confirmed", callback);
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.embeds.gated-send
	it("keeps the retained embed bundle through legacy ACKs until the exact committed turn", async () => {
		const clear = vi.fn(async () => undefined);
		watchMessageEmbedBundleConfirmation({
			accountId: "owner", chatId: "embed-ack-chat", messageId: "embed-ack-message",
			chatKey: new Uint8Array(32), embeds: [],
		}, 9, clear);
		const callback = [...vi.mocked(webSocketService.on).mock.calls].reverse()
			.find(([event]) => event === "chat_message_confirmed")?.[1];
		expect(callback).toBeTypeOf("function");
		(callback as (payload: unknown) => void)({ chat_id: "embed-ack-chat", message_id: "embed-ack-message" });
		(callback as (payload: unknown) => void)({ chat_id: "embed-ack-chat", message_id: "embed-ack-message", new_messages_v: 8 });
		expect(clear).not.toHaveBeenCalled();
		(callback as (payload: unknown) => void)({ chat_id: "embed-ack-chat", message_id: "embed-ack-message", new_messages_v: 9 });
		expect(clear).toHaveBeenCalledOnce();
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it("reuses exact embed ciphertext for a same-message retry and rejects changed intent", async () => {
		const records = new Map<string, string>();
		const storage = {
			getItem: (key: string) => records.get(key) ?? null,
			setItem: (key: string, value: string) => { records.set(key, value); },
		};
		const identity = {
			accountId: "owner", chatId: "chat", messageId: "message",
			chatKey: new Uint8Array(32).fill(7),
			embeds: [{ embed_id: "embed", type: "code", content: "private source" }],
		};
		const entry = {
			embed_id: "embed", encrypted_type: "type-cipher", encrypted_content: "content-cipher",
			status: "finished", hashed_chat_id: "chat-hash", hashed_message_id: "message-hash",
			hashed_user_id: "owner-hash", created_at: 1, updated_at: 1,
			embed_keys: [
				{ hashed_embed_id: "embed-hash", key_type: "master" as const, hashed_chat_id: null,
					encrypted_embed_key: "master-cipher", hashed_user_id: "owner-hash", created_at: 1 },
				{ hashed_embed_id: "embed-hash", key_type: "chat" as const, hashed_chat_id: "chat-hash",
					encrypted_embed_key: "chat-cipher", hashed_user_id: "owner-hash", created_at: 1 },
			],
		};
		const prepare = vi.fn(async () => [entry]);
		expect(await retainOrReuseEncryptedMessageEmbedBundle(identity, prepare, storage)).toEqual([entry]);
		expect(await retainOrReuseEncryptedMessageEmbedBundle(identity, prepare, storage)).toEqual([entry]);
		expect(prepare).toHaveBeenCalledTimes(1);
		expect([...records.values()][0]).not.toContain("private source");
		const [savedKey, savedValue] = [...records.entries()][0];
		records.set(savedKey, savedValue.replace("content-cipher", "changed-cipher"));
		await expect(retainOrReuseEncryptedMessageEmbedBundle(identity, prepare, storage))
			.rejects.toThrow("changed account, key, scope, content, or ciphertext");
		records.set(savedKey, savedValue);
		await expect(retainOrReuseEncryptedMessageEmbedBundle({
			...identity, embeds: [{ ...identity.embeds[0], content: "changed source" }],
		}, prepare, storage)).rejects.toThrow("changed account, key, scope, content, or ciphertext");
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,message-input.embeds.gated-send
	it("rehydrates a retained embed key after restart before any server preflight commit", async () => {
		const embedId = "local-pending-code-1";
		const hashedEmbedId = await computeSHA256(embedId);
		const wrapped = [
			{ hashed_embed_id: hashedEmbedId, key_type: "master" as const,
				hashed_chat_id: null, encrypted_embed_key: "retained-master-wrapper",
				hashed_user_id: "owner-hash", created_at: 1 },
			{ hashed_embed_id: hashedEmbedId, key_type: "chat" as const,
				hashed_chat_id: "chat-hash", encrypted_embed_key: "retained-chat-wrapper",
				hashed_user_id: "owner-hash", created_at: 1 },
		];
		const entry = {
			embed_id: embedId, encrypted_type: "original-type-cipher",
			encrypted_content: "original-content-cipher", status: "finished",
			hashed_chat_id: "chat-hash", hashed_message_id: "message-hash",
			hashed_user_id: "owner-hash", created_at: 1, updated_at: 1,
			embed_keys: wrapped,
		};
		const persisted = new Map<string, typeof wrapped[number]>();
		const transactionSpy = vi.spyOn(chatDB, "getTransaction").mockImplementation(async (_names, mode) => {
			const transaction = {
				error: null,
				oncomplete: null as (() => void) | null,
				objectStore: () => ({
					put: (value: typeof wrapped[number] & { id: string }) => {
						const request = { onsuccess: null as (() => void) | null,
							onerror: null as (() => void) | null, error: null };
						queueMicrotask(() => {
							persisted.set(value.id, value);
							request.onsuccess?.();
							queueMicrotask(() => transaction.oncomplete?.());
						});
						return request;
					},
					index: () => ({ getAll: (hash: string) => {
						const request = { result: [] as typeof wrapped, error: null,
							onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
						queueMicrotask(() => {
							request.result = [...persisted.values()].filter((key) => key.hashed_embed_id === hash);
							request.onsuccess?.();
						});
						return request;
					} }),
				}),
			};
			if (mode !== "readwrite" && mode !== "readonly") throw new Error("unexpected transaction");
			return transaction as unknown as IDBTransaction;
		});
		const store = new EmbedStore();
		const rawSpy = vi.spyOn(store, "getRawEntry").mockResolvedValue(undefined);
		const unwrappedKey = new Uint8Array(32).fill(11);
		const unwrapSpy = vi.spyOn(cryptoService, "unwrapEmbedKeyWithMasterKey")
			.mockResolvedValue(unwrappedKey);
		try {
			await persistRetainedMessageEmbedKeys([entry], store);
			// No canonical server state was created. Restart clears only memory keys;
			// getEmbedKey must read the retained local master wrapper from IDB.
			store.clearEmbedKeyCache();
			expect(await store.getEmbedKey(embedId, "chat-hash")).toEqual(unwrappedKey);
			expect(unwrapSpy).toHaveBeenCalledWith("retained-master-wrapper", embedId);
			expect([...persisted.values()]).toHaveLength(2);
		} finally {
			transactionSpy.mockRestore();
			rawSpy.mockRestore();
			unwrapSpy.mockRestore();
			store.clearEmbedKeyCache();
		}
		await expect(persistRetainedMessageEmbedKeys([entry], {
			storeEmbedKeys: async () => undefined,
			getEmbedKeyEntries: async () => [],
		})).rejects.toThrow("did not commit locally");
		const cacheOnlyTransaction = {
			objectStore: () => ({ get: () => {
				const request = { result: undefined, error: null,
					onsuccess: null as (() => void) | null, onerror: null as (() => void) | null };
				queueMicrotask(() => request.onsuccess?.());
				return request;
			} }),
		};
		await expect(verifyRetainedMessageEmbedHeads([entry],
			async () => cacheOnlyTransaction as unknown as IDBTransaction))
			.rejects.toThrow("head did not commit locally");
	});

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it("blocks sends when an embed has neither a canonical head nor retained ciphertext", async () => {
		const embed = { embed_id: "missing", type: "code", content: "private source" };
		expect(() => selectRequiredMessageEmbedEntries([embed], [], new Set())).toThrow(
			"has no canonical head or retained encrypted bundle"
		);
		expect(selectRequiredMessageEmbedEntries([embed], [], new Set(["missing"]))).toEqual([]);
		const retained = { embed_id: "missing" } as never;
		expect(selectRequiredMessageEmbedEntries([embed], [retained], new Set(["missing"])))
			.toEqual([retained]);
		const storage = { getItem: () => null, setItem: () => { throw new Error("storage unavailable"); } };
		await expect(retainOrReuseEncryptedMessageEmbedBundle({
			accountId: "owner", chatId: "chat", messageId: "message",
			chatKey: new Uint8Array(32).fill(8), embeds: [embed],
		}, async () => [], storage)).rejects.toThrow("storage unavailable");
	});
	});

	// contract-test: supporting surface=gui.web assertions=code-run.artifacts.chat-bound-versioned
	it("uses persisted profile identity when a new chat has no owner yet", () => {
		expect(requireEmbedOwnerId(undefined, "profile-user")).toBe("profile-user");
	});

	// contract-test: supporting surface=gui.web assertions=code-run.artifacts.chat-bound-versioned
	it("rejects embed persistence without an authenticated owner", () => {
		expect(() => requireEmbedOwnerId(undefined, null)).toThrow(
			"Cannot persist message embeds without an authenticated owner ID"
		);
	});

	// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
	it("keeps ordinary Team turns ciphertext-only", () => {
		const transport = buildTeamMessageTransport({
			message: TEAM_MESSAGE,
			content: "hello team",
			encryptedContent: "encrypted-message",
			encryptedSenderName: "encrypted-sender",
			history: [],
		});

		expect(transport.message).toEqual(expect.objectContaining({
			encrypted_content: "encrypted-message",
			encrypted_sender_name: "encrypted-sender",
		}));
		expect(transport.message).not.toHaveProperty("content");
		expect(transport.teamAIInvocation).toBeUndefined();
	});

	// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,teams.chat.sender-identity-layout
	it("sends attributed history only for an explicit OpenMates invocation", () => {
		const transport = buildTeamMessageTransport({
			message: { ...TEAM_MESSAGE, content: "@OpenMates summarize" },
			content: "@OpenMates summarize",
			encryptedContent: "encrypted-message",
			history: [{
				...TEAM_MESSAGE,
				message_id: "message-1",
				content: "Earlier context",
				created_at: 100,
				sender_name: "Bob",
			}],
		});

		expect(transport.message).not.toHaveProperty("content");
		expect(transport.teamAIInvocation?.history).toEqual([
			expect.objectContaining({ content: "Earlier context", sender_name: "Bob" }),
			expect.objectContaining({ content: "@OpenMates summarize", sender_name: "Alice" }),
		]);
	});

	// contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,teams.context.full-switch-local
	it("puts Team scope on the durable preflight boundary", () => {
		const preflightPayload: Record<string, unknown> = {};

		applyTeamPreflightScope(preflightPayload, "team-1");

		expect(preflightPayload).toEqual({ team_id: "team-1" });
	});
  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("does not extract interactive question protocol blocks as code embeds", () => {
    expect(shouldSkipClientCodeBlockExtraction("interactive_question", "{}"))
      .toBe(true);
    expect(shouldSkipClientCodeBlockExtraction("interactive_response", "{}"))
      .toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=chats.surface.semantic-parity
  it("continues extracting regular code fences", () => {
    expect(shouldSkipClientCodeBlockExtraction("typescript", "const answer = 42;"))
      .toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("uses the server version before the locally saved user message", () => {
    expect(preflightExpectedMessagesVersion(undefined)).toBe(0);
    expect(preflightExpectedMessagesVersion(1)).toBe(0);
    expect(preflightExpectedMessagesVersion(7)).toBe(6);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("only includes encrypted chat metadata on the first local message", () => {
    expect(shouldIncludePreflightChatMetadata(undefined)).toBe(true);
    expect(shouldIncludePreflightChatMetadata(1)).toBe(true);
    expect(shouldIncludePreflightChatMetadata(2)).toBe(false);
    expect(shouldIncludePreflightChatMetadata(7)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("only treats preflight acknowledgement timeouts as retryable", () => {
    expect(
      isPreflightAcknowledgementTimeout(
        new Error("Encrypted chat preflight acknowledgement timed out."),
      ),
    ).toBe(true);
    expect(isPreflightAcknowledgementTimeout(new Error("preflight_mismatch"))).toBe(false);
    expect(isPreflightAcknowledgementTimeout("Encrypted chat preflight acknowledgement timed out.")).toBe(false);
  });

	// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
	it("includes assistant categories in authorized inference history", async () => {
		const incognitoMessage = {
			...TEAM_MESSAGE,
			role: "assistant" as const,
			category: "news",
		};
		expect(await resolveHistoryCategoryForInference(incognitoMessage, true)).toBe("news");

		const savedMessage = {
			...incognitoMessage,
			category: undefined,
			encrypted_category: "encrypted-news",
		};
		expect(
			await resolveHistoryCategoryForInference(
				savedMessage,
				false,
				async (encryptedCategory) => encryptedCategory === "encrypted-news" ? "news" : null,
			)
		).toBe("news");
		expect(await resolveHistoryCategoryForInference(TEAM_MESSAGE, true)).toBeUndefined();
	});
});
