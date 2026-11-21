import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import {
  notificationStore,
  NOTIFICATION_OUTRO_DURATION_MS,
  type NotificationOptions,
} from "../notificationStore";

const notifications = () => get(notificationStore).notifications;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", { matchMedia: () => ({ matches: false }) });
  notificationStore.clearAllNotifications();
});

afterEach(() => {
  notificationStore.clearAllNotifications();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping,notifications.web.duplicate-lifecycle
describe("duplicate notification groups", () => {
  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it("groups basic, extended, and convenience triggers under one stable identity", () => {
    const id = notificationStore.addNotification(
      "error",
      "Failed to save",
      10000,
    );
    expect(notifications()[0].count).toBe(1);
    expect(notificationStore.error("Failed to save")).toBe(id);
    expect(
      notificationStore.addNotificationWithOptions("error", {
        message: "Failed to save",
        duration: 10000,
        dismissible: true,
      }),
    ).toBe(id);
    expect(notifications()).toMatchObject([{ id, count: 3 }]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-lifecycle
  it("increments an older card without moving it ahead of newer cards", () => {
    const error = notificationStore.error("Failed to save", 0);
    const other = notificationStore.info("Download ready", 0);
    notificationStore.error("Failed to save", 0);
    expect(notifications().map(({ id, count }) => ({ id, count }))).toEqual([
      { id: error, count: 2 },
      { id: other, count: 1 },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it("preserves explicit-key grouping across updates without mixing key domains", () => {
    const id = notificationStore.error("Failed to save", 0, true, "save-one");
    notificationStore.updateNotification(id, {
      message: "Retrying",
      actionsDisabled: true,
    });
    expect(notifications()[0].count).toBe(1);
    expect(notificationStore.error("Failed to save", 0, true, "save-one")).toBe(
      id,
    );
    notificationStore.error("Failed to save", 0, true, "save-two");
    notificationStore.error("Failed to save", 0);
    // The updated card shows other text; identical text joins one card whatever its key.
    expect(notifications()).toMatchObject([
      { id, message: "Retrying", actionsDisabled: true, count: 2 },
      { dedupeKey: "save-two", count: 2 },
    ]);
  });

  // contract-test: direct surface=gui.web assertions=notifications.web.duplicate-grouping,notifications.web.duplicate-lifecycle
  it("shows the same text fired 10 times as one card with ×10 that one close removes", () => {
    // Each trigger has its own key and action, like one warning per saved result.
    const ids = Array.from({ length: 10 }, (_, index) =>
      notificationStore.addNotificationWithOptions("warning", {
        message: "A saved result has a conflicting revision.",
        duration: 0,
        dedupeKey: `embed-write-conflict:embed-${index}`,
        actionLabel: "Review chat",
        onAction: () => index,
      }));
    expect(new Set(ids).size).toBe(1);
    expect(notifications()).toHaveLength(1);
    expect(notifications()[0]).toMatchObject({ id: ids[0], count: 10 });
    notificationStore.removeNotification(ids[0]);
    vi.advanceTimersByTime(NOTIFICATION_OUTRO_DURATION_MS);
    expect(notifications()).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-lifecycle
  it("keeps a card that stands for several keys until its last key is resolved", () => {
    const id = notificationStore.warning("Review the chat", 0, true, "conflict:a");
    notificationStore.warning("Review the chat", 0, true, "conflict:b");
    notificationStore.removeNotificationsByDedupeKey("conflict:a");
    expect(notifications()).toMatchObject([{ id, count: 2, dedupeKeys: ["conflict:b"] }]);
    expect(notificationStore.warning("Review the chat", 0, true, "conflict:b")).toBe(id);
    notificationStore.removeNotificationsByDedupeKey("conflict:b");
    expect(notifications()).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-lifecycle
  it("keeps a timed card open once an identical trigger must stay until closed", () => {
    const id = notificationStore.error("Failed to save", 5000);
    notificationStore.error("Failed to save", 0);
    vi.advanceTimersByTime(60000);
    expect(notifications()).toMatchObject([{ id, count: 2, duration: 0 }]);
    expect(notifications()[0].isExiting).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it("keeps notification types distinct and merges identical chat cards", () => {
    notificationStore.info("Done", 0);
    notificationStore.error("Done", 0);
    const firstChat = notificationStore.chatMessage(
      "chat-one",
      "Updates",
      "Done",
    );
    notificationStore.chatMessage("chat-two", "Updates", "Done");
    expect(notificationStore.chatMessage("chat-one", "Updates", "Done")).toBe(
      firstChat,
    );
    expect(notifications().map(({ count }) => count)).toEqual([1, 1, 3]);
  });

  const action = () => {};
  const options: NotificationOptions = {
    title: "Notice",
    message: "Please try again",
    messageSecondary: "Details",
    messageLink: { href: "/first", label: "Details" },
    duration: 10000,
    dismissible: true,
    onAction: action,
    actionLabel: "Retry",
    onSecondaryAction: action,
    secondaryActionLabel: "Cancel",
    chatId: "chat-one",
    chatTitle: "Chat",
    avatarUrl: "/avatar-one",
    category: "general",
  };

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it.each<Partial<NotificationOptions>>([
    { title: "Another notice" },
    { message: "Another error" },
    { messageSecondary: "Other details" },
    { messageLink: { href: "/other", label: "Details" } },
    { messageLink: { href: "/first", label: "Other link" } },
    { actionLabel: "Another action" },
    { secondaryActionLabel: "Another action" },
    { chatTitle: "Other chat" },
    { avatarUrl: "/avatar-two" },
    { category: "software_development" },
    { isProcessing: true },
  ])(
    "does not merge an alert with different visible content: %j",
    (changes) => {
      notificationStore.addNotificationWithOptions("info", options);
      notificationStore.addNotificationWithOptions("info", {
        ...options,
        ...changes,
      });
      expect(notifications()).toHaveLength(2);
    },
  );

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it.each<Partial<NotificationOptions>>([
    { onAction: () => {} },
    { onSecondaryAction: () => {} },
    { chatId: "chat-two" },
    { dedupeKey: "other-key" },
    { duration: 0 },
    { dismissible: false },
    { keepOnAction: true },
    { actionsDisabled: true },
  ])("merges identical visible text despite a different source detail: %j", (changes) => {
    const id = notificationStore.addNotificationWithOptions("info", options);
    expect(notificationStore.addNotificationWithOptions("info", { ...options, ...changes })).toBe(id);
    expect(notifications()).toMatchObject([{ id, count: 2 }]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it("compares reference links by value and normalizes inactive boolean options", () => {
    const id = notificationStore.addNotificationWithOptions("info", options);
    expect(
      notificationStore.addNotificationWithOptions("info", {
        ...options,
        messageLink: { ...options.messageLink! },
        keepOnAction: false,
        actionsDisabled: false,
        isProcessing: false,
      }),
    ).toBe(id);
    expect(notifications()[0].count).toBe(2);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-lifecycle
  it("dismisses the whole group once and starts a fresh group during its exit", () => {
    const id = notificationStore.error("Failed to save", 0);
    notificationStore.error("Failed to save", 0);
    notificationStore.removeNotification(id);
    const fresh = notificationStore.error("Failed to save", 0);
    expect(fresh).not.toBe(id);
    expect(notifications()).toMatchObject([
      { id, count: 2, isExiting: true },
      { id: fresh, count: 1 },
    ]);
    vi.advanceTimersByTime(NOTIFICATION_OUTRO_DURATION_MS);
    expect(notifications()).toMatchObject([{ id: fresh, count: 1 }]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.timed-dismissal,notifications.web.duplicate-lifecycle
  it("keeps the original deadline when duplicates arrive and starts fresh after expiry", () => {
    const id = notificationStore.error("Failed to save");
    vi.advanceTimersByTime(4000);
    notificationStore.error("Failed to save");
    vi.advanceTimersByTime(5999);
    expect(notifications()[0]).toMatchObject({ id, count: 2 });
    expect(notifications()[0].isExiting).toBeUndefined();
    vi.advanceTimersByTime(1);
    expect(notifications()[0].isExiting).toBe(true);
    vi.advanceTimersByTime(NOTIFICATION_OUTRO_DURATION_MS);
    expect(notifications()).toEqual([]);
    notificationStore.error("Failed to save");
    expect(notifications()[0]).toMatchObject({ count: 1 });
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-lifecycle
  it("does not restart a paused timer when a duplicate arrives", () => {
    const id = notificationStore.error("Failed to save");
    notificationStore.cancelAutoDismiss(id);
    notificationStore.error("Failed to save");
    vi.advanceTimersByTime(60000);
    expect(notifications()).toMatchObject([{ id, count: 2 }]);
    expect(notifications()[0].isExiting).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-lifecycle
  it("clears counts and old timers when removing by key or clearing all notifications", () => {
    const id = notificationStore.error("Failed to save", 10000, true, "save");
    notificationStore.error("Failed to save", 10000, true, "save");
    notificationStore.removeNotification(id);
    notificationStore.removeNotificationsByDedupeKey("save");
    notificationStore.error("Failed to save", 0, true, "save");
    vi.advanceTimersByTime(20000);
    expect(notifications()).toMatchObject([{ count: 1 }]);
    notificationStore.clearAllNotifications();
    notificationStore.error("Failed to save", 0, true, "save");
    expect(notifications()).toMatchObject([{ count: 1 }]);
  });
});

describe("chat notice summary headline", () => {
  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it("replaces the reply excerpt of a live notice and fills in the mate category", () => {
    notificationStore.chatMessage("chat-1", "Simple recipe web app", "New AI response ready");
    expect(notificationStore.applyChatHeadline("chat-1", "✅ Built a recipe app with search", "software_development")).toBe(true);
    expect(notifications()).toMatchObject([
      { chatTitle: "Simple recipe web app", message: "✅ Built a recipe app with search", category: "software_development" },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it("replaces the placeholder title of a notice raised before the chat had its title", () => {
    notificationStore.chatMessage("chat-1", "New message", "New AI response ready");
    notificationStore.applyChatHeadline("chat-1", "✅ Built a recipe app", undefined, "Simple recipe web app");
    expect(notifications()).toMatchObject([{ chatTitle: "Simple recipe web app", title: "Simple recipe web app", message: "✅ Built a recipe app" }]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it("keeps a category the notice already has and leaves other chats alone", () => {
    notificationStore.chatMessage("chat-1", "One", "excerpt", undefined, "cooking_food");
    notificationStore.chatMessage("chat-2", "Two", "other excerpt");
    notificationStore.applyChatHeadline("chat-1", "ℹ️ Pasta needs 10 minutes", "software_development");
    expect(notifications()).toMatchObject([
      { chatId: "chat-1", message: "ℹ️ Pasta needs 10 minutes", category: "cooking_food" },
      { chatId: "chat-2", message: "other excerpt" },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it("starts a notice created after the headline with that headline, once", () => {
    expect(notificationStore.applyChatHeadline("chat-3", "❓ Which database should it use?")).toBe(false);
    notificationStore.chatMessage("chat-3", "Three", "New AI response ready");
    expect(notifications()[0].message).toBe("❓ Which database should it use?");
    notificationStore.clearAllNotifications();
    notificationStore.chatMessage("chat-3", "Three", "next excerpt");
    expect(notifications()[0].message).toBe("next excerpt");
  });

  // contract-test: supporting surface=gui.web assertions=notifications.delivery.foreground-chat-suppression
  it("drops a pending headline after 30 seconds", () => {
    notificationStore.applyChatHeadline("chat-4", "✅ Done");
    vi.advanceTimersByTime(31_000);
    notificationStore.chatMessage("chat-4", "Four", "excerpt");
    expect(notifications()[0].message).toBe("excerpt");
  });
});
