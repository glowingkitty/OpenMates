// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAI.test.ts
// Regression coverage for AI websocket embed handlers.
// These tests focus on event ordering races between embed_update and
// send_embed_data, where the UI can otherwise stay on a loading preview.
// Keep mocks narrow so handler behavior remains visible.

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import { handleEmbedUpdateImpl } from "../chatSyncServiceHandlersAI";

const mockEmbedStore = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  removeFromMemoryCache: vi.fn(),
}));

vi.mock("../embedStore", () => ({
  embedStore: mockEmbedStore,
}));

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
