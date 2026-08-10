// frontend/packages/ui/src/services/__tests__/chatExportService.test.ts
// Focused export-hydration tests for long chat history.
//
// The export service must not serialize only the currently rendered 40-message
// window. These tests use mocked IndexedDB services to guard complete/partial
// metadata and compression checkpoint inclusion without triggering downloads.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Chat, ChatCompressionCheckpoint, Message } from "../../types/chat";

const mocks = vi.hoisted(() => ({
  getMessagesForChat: vi.fn(),
  getChatCompressionCheckpoints: vi.fn(),
  getDecryptedMetadata: vi.fn(),
}));

vi.mock("../db", () => ({
  chatDB: {
    getMessagesForChat: mocks.getMessagesForChat,
    getChatCompressionCheckpoints: mocks.getChatCompressionCheckpoints,
  },
}));

vi.mock("../chatMetadataCache", () => ({
  chatMetadataCache: {
    getDecryptedMetadata: mocks.getDecryptedMetadata,
  },
}));

vi.mock("../embedResolver", () => ({
  extractEmbedReferences: vi.fn(() => []),
  loadEmbeds: vi.fn(async () => []),
  decodeToonContent: vi.fn(async (content: string) => content),
}));

vi.mock("../../components/enter_message/services/piiDetectionService", () => ({
  restorePIIInText: vi.fn((content: string) => content),
}));

vi.mock("../../message_parsing/serializers", () => ({
  tipTapToCanonicalMarkdown: vi.fn(() => ""),
}));

function makeChat(overrides: Partial<Chat> = {}): Chat {
  return {
    chat_id: "chat-export",
    title: "Long Export Chat",
    created_at: 1784700000,
    updated_at: 1784700100,
    messages_v: 101,
    metadata_v: 1,
    ...overrides,
  } as Chat;
}

function makeMessages(count: number, startIndex = 1): Message[] {
  return Array.from({ length: count }, (_, index) => ({
    message_id: `msg-${startIndex + index}`,
    chat_id: "chat-export",
    role: index % 2 === 0 ? "user" : "assistant",
    content: `message ${startIndex + index}`,
    created_at: startIndex + index,
    status: "synced",
  }) as Message);
}

function makeCheckpoint(): ChatCompressionCheckpoint {
  return {
    id: "checkpoint-1",
    chat_id: "chat-export",
    user_id: "user-1",
    created_at: 90,
    compressed_up_to_timestamp: 80,
    compressed_message_count: 80,
    summary: "Older history summary",
    summary_token_estimate: 42,
    status: "active",
  } as ChatCompressionCheckpoint;
}

describe("chatExportService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getDecryptedMetadata.mockResolvedValue({
      title: "Long Export Chat",
      summary: "Export summary",
    });
  });

  it("hydrates beyond the rendered 40-message window before export", async () => {
    const allMessages = makeMessages(101).reverse();
    mocks.getMessagesForChat.mockResolvedValue(allMessages);
    mocks.getChatCompressionCheckpoints.mockResolvedValue([]);

    const { hydrateChatForExport } = await import("../chatExportService");
    const hydrated = await hydrateChatForExport(makeChat(), allMessages.slice(0, 40));

    expect(mocks.getMessagesForChat).toHaveBeenCalledWith("chat-export");
    expect(hydrated.messages).toHaveLength(101);
    expect(hydrated.messages[0]?.message_id).toBe("msg-1");
    expect(hydrated.messages[100]?.message_id).toBe("msg-101");
    expect(hydrated.completeness).toMatchObject({
      status: "complete",
      requested_message_count: 101,
      hydrated_message_count: 101,
      checkpoint_count: 0,
      warnings: [],
    });
  });

  it("marks exports partial when durable rows or forgotten checkpoint messages may be missing", async () => {
    mocks.getMessagesForChat.mockResolvedValue(makeMessages(40, 62));
    mocks.getChatCompressionCheckpoints.mockResolvedValue([makeCheckpoint()]);

    const { hydrateChatForExport } = await import("../chatExportService");
    const hydrated = await hydrateChatForExport(makeChat(), makeMessages(40, 62));

    expect(hydrated.completeness.status).toBe("partial");
    expect(hydrated.completeness.warnings).toEqual([
      "Only 40 of 101 durable messages were available locally.",
      "This chat has compression checkpoints; some forgotten raw messages may require server hydration before export is complete.",
    ]);
  });

  it("marks compressed exports complete when all checkpoint messages are hydrated", async () => {
    const allMessages = makeMessages(101);
    mocks.getMessagesForChat.mockResolvedValue(allMessages);
    mocks.getChatCompressionCheckpoints.mockResolvedValue([makeCheckpoint()]);

    const { hydrateChatForExport } = await import("../chatExportService");
    const hydrated = await hydrateChatForExport(makeChat(), allMessages.slice(61));

    expect(hydrated.messages).toHaveLength(101);
    expect(hydrated.completeness).toMatchObject({
      status: "complete",
      requested_message_count: 101,
      hydrated_message_count: 101,
      checkpoint_count: 1,
      warnings: [],
    });
  });

  it("serializes export completeness and compression checkpoints into YAML", async () => {
    const checkpoint = makeCheckpoint();

    const { convertChatToYaml } = await import("../chatExportService");
    const yaml = await convertChatToYaml(makeChat(), makeMessages(2), false, undefined, {
      messages: makeMessages(2),
      checkpoints: [checkpoint],
      completeness: {
        status: "partial",
        requested_message_count: 101,
        hydrated_message_count: 2,
        checkpoint_count: 1,
        warnings: ["Only 2 of 101 durable messages were available locally."],
      },
    });

    expect(yaml).toContain("export_completeness:");
    expect(yaml).toContain("status: partial");
    expect(yaml).toContain("requested_message_count: 101");
    expect(yaml).toContain("compression_checkpoints:");
    expect(yaml).toContain("id: checkpoint-1");
    expect(yaml).toContain("summary: Older history summary");
  });
});
