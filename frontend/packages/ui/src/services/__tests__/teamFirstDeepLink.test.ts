import { describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({ goto: vi.fn(), replaceState: vi.fn() }));
vi.mock("$app/environment", () => ({ browser: true }));
vi.mock("../chatUrlService", () => ({ isOnSemanticChatPath: () => false }));

import { parseDeepLink, processDeepLink } from "../deepLinkHandler";
import { getHashParam } from "../../utils/settingsHashUtils";

describe("Team-first chat deep links", () => {
  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
  it("finds chat and message IDs after the Team context parameter", () => {
    const hash = "#team-id=team-1&chat-id=chat-123&message-id=msg-789";
    expect(getHashParam(hash, "chat-id")).toBe("chat-123");
    expect(parseDeepLink(hash)).toEqual({
      type: "chat",
      data: {
        chatId: "chat-123",
        messageId: "msg-789",
        scrollToLatestResponse: false,
        embedId: null,
        autoplayVideo: false,
        teamId: "team-1",
      },
    });
    expect(parseDeepLink("#team-id=team-1")?.type).not.toBe("chat");
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
  it("opens the Team chat when the retained Team context comes first", async () => {
    const onChat = vi.fn().mockResolvedValue(undefined);
    await processDeepLink("#team-id=team-1&chat-id=chat-123", {
      onChat,
      isAuthenticated: () => true,
    });
    expect(onChat).toHaveBeenCalledExactlyOnceWith(
      "chat-123", null, false, null, false, "team-1",
    );
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,teams.cache.bounded-isolated
  it("defers Team hash selection until authorization while retaining Personal hash startup", async () => {
    const originalUrl = window.location.href;
    try {
      window.history.replaceState(null, "", "/#team-id=team-1&chat-id=chat-123");
      vi.resetModules();
      const teamStore = (await import("../../stores/activeChatStore")).activeChatStore;
      expect(teamStore.get()).toBeNull();
      expect(teamStore.getChatIdFromHash()).toBe("chat-123");

      window.history.replaceState(null, "", "/#chat-id=personal-123");
      vi.resetModules();
      const personalStore = (await import("../../stores/activeChatStore")).activeChatStore;
      expect(personalStore.get()).toBe("personal-123");
    } finally {
      window.history.replaceState(null, "", originalUrl);
    }
  });
});
