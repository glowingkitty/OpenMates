/**
 * frontend/packages/ui/src/services/__tests__/sendersChatMessagesProtocol.test.ts
 *
 * Regression tests for protocol fenced blocks in the client message sender.
 * Interactive question answers are chat protocol, not user-authored code embeds.
 */

import { describe, expect, it, vi } from "vitest";

vi.mock("../websocketService", () => ({
  webSocketService: {
    forceReconnect: vi.fn(),
    off: vi.fn(),
    on: vi.fn(),
    sendMessage: vi.fn(),
  },
}));
import {
	buildTeamMessageTransport,
	applyTeamPreflightScope,
  requireEmbedOwnerId,
  isPreflightAcknowledgementTimeout,
  preflightExpectedMessagesVersion,
  shouldIncludePreflightChatMetadata,
  shouldSkipClientCodeBlockExtraction,
} from "../sendersChatMessages";

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
});
