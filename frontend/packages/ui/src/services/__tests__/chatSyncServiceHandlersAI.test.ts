// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAI.test.ts
// Regression coverage for AI websocket embed handlers.
// These tests focus on event ordering races between embed_update and
// send_embed_data, where the UI can otherwise stay on a loading preview.
// Keep mocks narrow so handler behavior remains visible.

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import {
  handleAIBackgroundResponseCompletedImpl,
  handleEmbedUpdateImpl,
} from "../chatSyncServiceHandlersAI";

const mockEmbedStore = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  removeFromMemoryCache: vi.fn(),
}));

const mockAiTypingStore = vi.hoisted(() => ({
  clearTyping: vi.fn(),
}));

vi.mock("../embedStore", () => ({
  embedStore: mockEmbedStore,
}));

vi.mock("../../stores/aiTypingStore", () => ({
  aiTypingStore: mockAiTypingStore,
}));

describe("handleAIBackgroundResponseCompletedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not send legacy persistence for epoch-one recovery completions", async () => {
    const activeAITasks = new Map([["chat-1", { taskId: "task-1" }]]);
    const service = {
      activeAITasks,
      dispatchEvent: vi.fn(),
      sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAIBackgroundResponseCompletedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      task_id: "task-1",
      full_content: "Recovered content",
      recovery_job_id: "job-1",
      recovery_protocol_version: 1,
    });

    expect(service.sendCompletedAIResponse).not.toHaveBeenCalled();
    expect(activeAITasks.has("chat-1")).toBe(false);
    expect(mockAiTypingStore.clearTyping).toHaveBeenCalledWith(
      "chat-1",
      "assistant-1",
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "aiTaskEnded" }),
    );
  });
});

describe("handleEmbedUpdateImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps placeholder embeds processing until final content arrives", async () => {
    const existingEmbed = {
      embed_id: "embed-1",
      status: "processing",
      content: "app_id: web\nskill_id: search\nstatus: processing",
      chat_id: "chat-1",
      message_id: "message-1",
      embed_ids: [] as string[],
    };
    mockEmbedStore.get.mockResolvedValue(existingEmbed);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleEmbedUpdateImpl(service, {
      type: "embed_update",
      event_for_client: "embed_update",
      embed_id: "embed-1",
      chat_id: "chat-1",
      message_id: "message-1",
      user_id_uuid: "user-1",
      user_id_hash: "hashed-user-1",
      status: "finished",
      child_embed_ids: ["child-1"],
    });

    expect(existingEmbed.status).toBe("processing");
    expect(existingEmbed.embed_ids).toEqual(["child-1"]);
    expect(mockEmbedStore.put).not.toHaveBeenCalled();
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "embedUpdated",
        detail: expect.objectContaining({
          embed_id: "embed-1",
          status: "finished",
          isWaitingForContent: true,
        }),
      }),
    );
  });
});
