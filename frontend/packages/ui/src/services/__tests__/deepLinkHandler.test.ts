import { describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({
  replaceState: vi.fn(),
}));

import { replaceState } from "$app/navigation";
import { buildChatMessageLink, parseDeepLink, processDeepLink, processSettingsDeepLink } from "../deepLinkHandler";
import {
  clearSettingsPathFromHash,
  getSettingsPathFromHash,
  setSettingsPathInHash,
  updateHashParams,
} from "../../utils/settingsHashUtils";

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

  it("parses the canonical hide personal data settings link", () => {
    expect(parseDeepLink("#settings/privacy/hide-personal-data"))?.toEqual({
      type: "settings",
      data: {
        path: "privacy/hide-personal-data",
        fullHash: "#settings/privacy/hide-personal-data",
      },
    });
  });

  it("parses the privacy pii settings alias", () => {
    expect(parseDeepLink("#settings/privacy/pii"))?.toEqual({
      type: "settings",
      data: {
        path: "privacy/hide-personal-data",
        fullHash: "#settings/privacy/pii",
      },
    });
  });

  it("keeps chat as primary when a combined hash also contains settings", () => {
    expect(parseDeepLink("#chat-id=chat-123&settings=privacy/pii"))?.toEqual({
      type: "chat",
      data: {
        chatId: "chat-123",
        messageId: null,
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

  it("keeps connected-accounts hyphenated and ignores E2E debug hash params", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink(
      "#settings/privacy/connected-accounts&e2e-debug=run-1&e2e-token=token-1",
      {
        openSettings: vi.fn(),
        setSettingsDeepLink,
      },
    );

    expect(setSettingsDeepLink).toHaveBeenCalledWith(
      "privacy/connected-accounts",
    );
  });

  it("preserves non-E2E settings hash params", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink(
      "#settings/billing&usage&e2e-debug=run-1&e2e-token=token-1",
      {
        openSettings: vi.fn(),
        setSettingsDeepLink,
      },
    );

    expect(setSettingsDeepLink).toHaveBeenCalledWith("billing&usage");
  });

  it("opens the canonical hide personal data settings route", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink("#settings/privacy/hide-personal-data", {
      openSettings: vi.fn(),
      setSettingsDeepLink,
    });

    expect(setSettingsDeepLink).toHaveBeenCalledWith(
      "privacy/hide-personal-data",
    );
  });

  it("maps privacy pii to the hide personal data settings route", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink("#settings/privacy/pii", {
      openSettings: vi.fn(),
      setSettingsDeepLink,
    });

    expect(setSettingsDeepLink).toHaveBeenCalledWith(
      "privacy/hide-personal-data",
    );
  });

  it("extracts settings from a combined chat/settings hash", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink("#chat-id=chat-123&settings=privacy/pii", {
      openSettings: vi.fn(),
      setSettingsDeepLink,
    });

    expect(setSettingsDeepLink).toHaveBeenCalledWith(
      "privacy/hide-personal-data",
    );
  });

  it("keeps the settings hash during OAuth handoff returns", () => {
    const setSettingsDeepLink = vi.fn();
    const originalLocation = window.location;
    vi.mocked(replaceState).mockClear();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        hash: "#settings/apps/calendar",
        pathname: "/",
        search: "?oauth_handoff_id=handoff-test-1",
      },
    });

    try {
      processSettingsDeepLink(window.location.hash, {
        openSettings: vi.fn(),
        setSettingsDeepLink,
      });
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }

    expect(setSettingsDeepLink).toHaveBeenCalledWith("apps/calendar");
    expect(replaceState).not.toHaveBeenCalled();
  });
});

describe("processDeepLink", () => {
  it("opens settings after processing a combined chat/settings hash", async () => {
    const onChat = vi.fn().mockResolvedValue(undefined);
    const onSettings = vi.fn();

    await processDeepLink("#chat-id=chat-123&settings=privacy/pii", {
      onChat,
      onSettings,
    });

    expect(onChat).toHaveBeenCalledWith(
      "chat-123",
      null,
      false,
      null,
      false,
    );
    expect(onSettings).toHaveBeenCalledWith(
      "privacy/hide-personal-data",
      "#settings/privacy/hide-personal-data",
    );
  });
});

describe("settings hash helpers", () => {
  it("extracts settings aliases from combined hashes", () => {
    expect(getSettingsPathFromHash("#chat-id=chat-123&settings=privacy/pii")).toBe(
      "privacy/hide-personal-data",
    );
  });

  it("adds settings to an existing chat/embed hash without removing context", () => {
    expect(
      setSettingsPathInHash(
        "#chat-id=chat-123&embed-id=embed-456",
        "privacy/hide-personal-data",
      ),
    ).toBe("#chat-id=chat-123&embed-id=embed-456&settings=privacy/hide-personal-data");
  });

  it("removes only settings from a combined hash", () => {
    expect(
      clearSettingsPathFromHash(
        "#chat-id=chat-123&embed-id=embed-456&settings=privacy/hide-personal-data",
      ),
    ).toBe("#chat-id=chat-123&embed-id=embed-456");
  });

  it("updates chat while preserving settings", () => {
    expect(
      updateHashParams("#settings/privacy/hide-personal-data", {
        "chat-id": "chat-123",
      }),
    ).toBe("#settings=privacy/hide-personal-data&chat-id=chat-123");
  });
});
