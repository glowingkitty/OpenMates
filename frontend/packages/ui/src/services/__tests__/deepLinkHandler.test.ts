import { describe, expect, it, vi } from "vitest";

vi.mock("$app/navigation", () => ({
  replaceState: vi.fn(),
}));
vi.mock('../embedResolver', () => ({ resolveEmbed: vi.fn() }));

import { replaceState } from "$app/navigation";
import { buildChatMessageLink, parseDeepLink, processDeepLink, processSettingsDeepLink, waitForDeepLinkedEmbed } from "../deepLinkHandler";
import { resolveEmbed } from '../embedResolver';
import {
  clearSettingsPathFromHash,
  getSettingsPathFromHash,
  setSettingsPathInHash,
  updateHashParams,
} from "../../utils/settingsHashUtils";

describe("parseDeepLink", () => {
  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
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

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
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

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
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

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
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

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("parses the canonical hide personal data settings link", () => {
    expect(parseDeepLink("#settings/privacy/hide-personal-data"))?.toEqual({
      type: "settings",
      data: {
        path: "privacy/hide-personal-data",
        fullHash: "#settings/privacy/hide-personal-data",
      },
    });
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("parses the privacy pii settings alias", () => {
    expect(parseDeepLink("#settings/privacy/pii"))?.toEqual({
      type: "settings",
      data: {
        path: "privacy/hide-personal-data",
        fullHash: "#settings/privacy/pii",
      },
    });
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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
  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("keeps referral-code hyphenated for the billing settings route", () => {
    const setSettingsDeepLink = vi.fn();

    processSettingsDeepLink("#settings/billing/referral-code", {
      openSettings: vi.fn(),
      setSettingsDeepLink,
    });

    expect(setSettingsDeepLink).toHaveBeenCalledWith("billing/referral-code");
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
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

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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
  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  it('waits through the initial resolver cache miss before opening a cold embed', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(resolveEmbed).mockResolvedValueOnce(null).mockResolvedValueOnce({ embed_id: 'target' } as Awaited<ReturnType<typeof resolveEmbed>>);
      const ready = waitForDeepLinkedEmbed('target', 'source-chat', () => true);
      await vi.advanceTimersByTimeAsync(100);
      expect(await ready).toBe(true);
      expect(resolveEmbed).toHaveBeenLastCalledWith('target', { chatId: 'source-chat' });
    } finally { vi.useRealTimers(); }
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  it('abandons an embed read when navigation changes while its fetch is pending', async () => {
    vi.useFakeTimers();
    try {
      let current = true;
      vi.mocked(resolveEmbed).mockResolvedValue(null);
      const ready = waitForDeepLinkedEmbed('target', 'source-chat', () => current);
      await vi.advanceTimersByTimeAsync(50);
      current = false;
      await vi.advanceTimersByTimeAsync(50);
      expect(await ready).toBe(false);
    } finally { vi.useRealTimers(); }
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  it('settles a persistently missing embed within the bounded detail wait', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(resolveEmbed).mockResolvedValue(null);
      const ready = waitForDeepLinkedEmbed('target', 'source-chat', () => true, 200);
      await vi.advanceTimersByTimeAsync(200);
      expect(await ready).toBe(false);
    } finally { vi.useRealTimers(); }
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
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
      null,
    );
    expect(onSettings).toHaveBeenCalledWith(
      "privacy/hide-personal-data",
      "#settings/privacy/hide-personal-data",
    );
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  it('retains the complete private reminder target until authentication', async () => {
    sessionStorage.clear();
    const hash = '#chat-id=private-chat&embed-id=reminder-card&message-id=source-message&team-id=team-1';
    const onChat = vi.fn();
    const openLogin = vi.fn();
    expect(await processDeepLink(hash, {
      onChat, openLogin, isAuthenticated: () => false,
      chatRequiresAuthentication: async () => true,
    })).toMatchObject({ requiresAuth: true, processed: true });
    expect(sessionStorage.getItem('pendingDeepLink')).toBe(hash);
    expect(openLogin).toHaveBeenCalledOnce();
    expect(onChat).not.toHaveBeenCalled();

    await processDeepLink(sessionStorage.getItem('pendingDeepLink')!, {
      onChat, isAuthenticated: () => true,
      chatRequiresAuthentication: async () => true,
    });
    expect(onChat).toHaveBeenCalledWith('private-chat', 'source-message', false, 'reminder-card', false, 'team-1');
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  it('gates ordinary private chat links without requiring Team context', async () => {
    const onChat = vi.fn();
    const hash = '#chat-id=private-chat&embed-id=reminder-card&scroll=latest-response';
    await processDeepLink(hash, {
      onChat, isAuthenticated: () => false, chatRequiresAuthentication: async () => true,
    });
    expect(sessionStorage.getItem('pendingDeepLink')).toBe(hash);
    expect(onChat).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=notifications.reminder-email.exact-web-target
  it.each(['public', 'shared', 'anonymous', 'draft'])('preserves guest access to %s chat links', async (chatId) => {
    const onChat = vi.fn();
    const openLogin = vi.fn();
    await processDeepLink(`#chat-id=${chatId}&embed-id=card`, {
      onChat, openLogin, isAuthenticated: () => false, chatRequiresAuthentication: async () => false,
    });
    expect(onChat).toHaveBeenCalledWith(chatId, null, false, 'card', false, null);
    expect(openLogin).not.toHaveBeenCalled();
  });
});

describe("settings hash helpers", () => {
  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("extracts settings aliases from combined hashes", () => {
    expect(getSettingsPathFromHash("#chat-id=chat-123&settings=privacy/pii")).toBe(
      "privacy/hide-personal-data",
    );
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("adds settings to an existing chat/embed hash without removing context", () => {
    expect(
      setSettingsPathInHash(
        "#chat-id=chat-123&embed-id=embed-456",
        "privacy/hide-personal-data",
      ),
    ).toBe("#chat-id=chat-123&embed-id=embed-456&settings=privacy/hide-personal-data");
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("removes only settings from a combined hash", () => {
    expect(
      clearSettingsPathFromHash(
        "#chat-id=chat-123&embed-id=embed-456&settings=privacy/hide-personal-data",
      ),
    ).toBe("#chat-id=chat-123&embed-id=embed-456");
  });

  // contract-test: supporting surface=gui.web assertions=settings-ui.shell.lifecycle-and-routing
  it("updates chat while preserving settings", () => {
    expect(
      updateHashParams("#settings/privacy/hide-personal-data", {
        "chat-id": "chat-123",
      }),
    ).toBe("#settings=privacy/hide-personal-data&chat-id=chat-123");
  });
});
