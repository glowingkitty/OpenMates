/**
 * frontend/packages/ui/src/services/__tests__/sendersChatMessagesAIResponse.test.ts
 *
 * Regression coverage for completed AI response persistence sends.
 * A failed ai_response_completed WebSocket send must queue a retry so a locally
 * rendered assistant response is not lost from durable chat storage.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import type { Message } from "../../types/chat";

const mocks = vi.hoisted(() => ({
	chatDB: {
		getChat: vi.fn(),
		getEncryptedFields: vi.fn(),
		getMessageCountForChat: vi.fn(),
		updateChatComponentVersion: vi.fn(),
	},
	chatKeyManager: {
		getKeySync: vi.fn(),
		getKey: vi.fn(),
	},
	ensureChatKeySafeForWrite: vi.fn(),
	webSocketService: {
		on: vi.fn(),
		off: vi.fn(),
		sendMessage: vi.fn(),
	},
	addPendingAIResponse: vi.fn(),
	getTracer: vi.fn(() => ({
		startSpan: vi.fn(() => ({ end: vi.fn() })),
	})),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../websocketService", () => ({ webSocketService: mocks.webSocketService }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: {} }));
vi.mock("../timestampUtils", () => ({ normalizeToUnixSeconds: vi.fn((value) => value) }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: mocks.chatKeyManager }));
vi.mock("../encryption/MessageEncryptor", () => ({
	encryptWithChatKey: vi.fn(),
	decryptWithChatKey: vi.fn(),
}));
vi.mock("../encryption/MetadataEncryptor", () => ({
	decryptChatKeyWithMasterKey: vi.fn(),
	encryptChatKeyWithMasterKey: vi.fn(),
	generateEmbedKey: vi.fn(),
	deriveEmbedKeyFromChatKey: vi.fn(),
	encryptWithEmbedKey: vi.fn(),
	wrapEmbedKeyWithMasterKey: vi.fn(),
	wrapEmbedKeyWithChatKey: vi.fn(),
}));
vi.mock("../tracing/setup", () => ({ getTracer: mocks.getTracer }));
vi.mock("../tracing/wsSpans", () => ({ injectTraceparent: vi.fn() }));
vi.mock("../db/chatCrudOperations", () => ({ addCandidateKey: vi.fn() }));
vi.mock("../chatKeyConsistency", () => ({ encryptedChatKeyMatchesRawKey: vi.fn() }));
vi.mock("../chatKeyWriteGuard", () => ({
	ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite,
}));
vi.mock("../chatErrorReportConsent", () => ({ promptChatErrorReportConsent: vi.fn() }));
vi.mock("svelte/store", () => ({ get: vi.fn() }));
vi.mock("../../stores/serverStatusStore", () => ({
	initializeServerStatus: vi.fn(),
	serverStatusStore: {},
}));
vi.mock("../connectedAccountTokenBrokerService", () => ({
	assertNoConnectedAccountSecretLeak: vi.fn(),
}));
vi.mock("../../utils/chatCompletionRecovery", () => ({
	deriveChatCompletionRecoveryKeypair: vi.fn(),
}));
vi.mock("../../message_parsing/utils", () => ({ generateUUID: vi.fn(() => "generated-id") }));
vi.mock("../pendingAIResponses", () => ({
	addPendingAIResponse: mocks.addPendingAIResponse,
}));

import { sendCompletedAIResponseImpl } from "../sendersChatMessages";

describe("sendCompletedAIResponseImpl", () => {
	function makeService(overrides: Partial<ChatSynchronizationService> = {}) {
		return {
			webSocketConnected_FOR_SENDERS_ONLY: true,
			isMessageSyncing: vi.fn(() => false),
			markMessageSyncing: vi.fn(),
			unmarkMessageSyncing: vi.fn(),
			dispatchEvent: vi.fn(),
			...overrides,
		} as unknown as ChatSynchronizationService;
	}

	function makeAIMessage(overrides: Partial<Message> = {}) {
		return {
			message_id: "assistant-1",
			chat_id: "chat-1",
			role: "assistant",
			created_at: 123,
			status: "synced",
			user_message_id: "user-1",
			...overrides,
		} as Message;
	}

	beforeEach(() => {
		vi.clearAllMocks();
		mocks.chatDB.getChat.mockResolvedValue({
			chat_id: "chat-1",
			messages_v: 3,
		});
		mocks.chatDB.getEncryptedFields.mockResolvedValue({
			encrypted_content: "ciphertext",
			encrypted_category: "category",
			encrypted_model_name: "model",
		});
		mocks.chatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
		mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
	});

	// contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
	it("queues a retry when ai_response_completed send fails", async () => {
		mocks.webSocketService.sendMessage.mockRejectedValue(new Error("socket closed"));

		const service = makeService();
		const aiMessage = makeAIMessage();

		await sendCompletedAIResponseImpl(service, aiMessage);

		expect(mocks.addPendingAIResponse).toHaveBeenCalledWith("assistant-1", "chat-1");
		expect(service.unmarkMessageSyncing).toHaveBeenCalledWith("assistant-1");
	});

	// contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.local-state.precedence
	it("queues a retry when chat metadata is not available yet", async () => {
		mocks.chatDB.getChat.mockResolvedValue(null);
		const service = makeService();
		const aiMessage = makeAIMessage();

		await sendCompletedAIResponseImpl(service, aiMessage);

		expect(mocks.addPendingAIResponse).toHaveBeenCalledWith("assistant-1", "chat-1");
		expect(service.unmarkMessageSyncing).toHaveBeenCalledWith("assistant-1");
		expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
	});

	// contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.sync.key-gated-recovery
	it("queues a retry when the chat key is still recovering", async () => {
		mocks.ensureChatKeySafeForWrite.mockResolvedValue(false);
		const service = makeService();
		const aiMessage = makeAIMessage();

		await sendCompletedAIResponseImpl(service, aiMessage);

		expect(mocks.addPendingAIResponse).toHaveBeenCalledWith("assistant-1", "chat-1");
		expect(service.unmarkMessageSyncing).toHaveBeenCalledWith("assistant-1");
		expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
	});

	// contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.persistence.client-encrypted
	it("does not optimistically persist messages_v before storage confirmation", async () => {
		mocks.webSocketService.sendMessage.mockResolvedValue(undefined);

		const service = makeService();
		const aiMessage = makeAIMessage();

		await sendCompletedAIResponseImpl(service, aiMessage);

		expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
			"ai_response_completed",
			expect.objectContaining({
				versions: {
					messages_v: 4,
					last_edited_overall_timestamp: 123,
				},
			})
		);
		expect(mocks.chatDB.getMessageCountForChat).not.toHaveBeenCalled();
		expect(mocks.chatDB.updateChatComponentVersion).not.toHaveBeenCalled();
	});
});
