import { describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({
  replaceState: vi.fn(),
}));

import { buildChatMessageLink, parseDeepLink, processSettingsDeepLink } from "../deepLinkHandler";

describe("parseDeepLink", () => {
  it("parses chat links with a bare autoplay-video flag", () => {
    expect(
      parseDeepLink("#chat-id=announcements-introducing-openmates-v09&autoplay-video"),
    ).toEqual({
      type: "chat",
      data: {
        chatId: "announcements-introducing-openmates-v09",
        messageId: null,
        scrollToLatestResponse: false,
        embedId: null,
        autoplayVideo: true,
      },
    });
  });

  it("keeps existing chat link params", () => {
    expect(
      parseDeepLink("#chat-id=chat-123&embed-id=embed-456&message-id=msg-789&scroll=latest-response"),
    ).toEqual({
      type: "chat",
      data: {
        chatId: "chat-123",
        messageId: "msg-789",
        scrollToLatestResponse: true,
        embedId: "embed-456",
        autoplayVideo: false,
      },
    });
  });

  it("accepts legacy messageid chat link params", () => {
    expect(parseDeepLink("#chat-id=chat-123&messageid=msg-legacy"))?.toEqual({
      type: "chat",
      data: {
        chatId: "chat-123",
        messageId: "msg-legacy",
        scrollToLatestResponse: false,
        embedId: null,
        autoplayVideo: false,
      },
    });
  });

  it("builds same-origin chat/message links that round-trip through parsing", () => {
    const link = buildChatMessageLink("chat-123", "msg-789", "https://app.example.test/chat");

    expect(link).toBe("https://app.example.test/chat#chat-id=chat-123&message-id=msg-789");
    expect(parseDeepLink(link.slice(link.indexOf("#")))).toEqual({
      type: "chat",
      data: {
        chatId: "chat-123",
        messageId: "msg-789",
        scrollToLatestResponse: false,
        embedId: null,
        autoplayVideo: false,
      },
    });
  });
});

describe("processSettingsDeepLink", () => {
  it("keeps referral-code hyphenated for the billing settings route", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink("#settings/billing/referral-code", {
      openSettings: vi.fn(),
      setSettingsDeepLink,
    });

    expect(setSettingsDeepLink).toHaveBeenCalledWith("billing/referral-code");
  });
});
