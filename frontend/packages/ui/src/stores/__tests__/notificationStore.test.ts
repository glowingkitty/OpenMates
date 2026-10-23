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
    expect(notifications()).toMatchObject([
      { id, message: "Retrying", actionsDisabled: true, count: 2 },
      { dedupeKey: "save-two", count: 1 },
      { dedupeKey: undefined, count: 1 },
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=notifications.web.duplicate-grouping
  it("keeps notification types and chat destinations distinct", () => {
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
    expect(notifications().map(({ count }) => count)).toEqual([1, 1, 2, 1]);
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
    { onAction: () => {} },
    { actionLabel: "Another action" },
    { onSecondaryAction: () => {} },
    { secondaryActionLabel: "Another action" },
    { chatId: "chat-two" },
    { chatTitle: "Other chat" },
    { avatarUrl: "/avatar-two" },
    { category: "software_development" },
    { duration: 0 },
    { dismissible: false },
    { keepOnAction: true },
    { actionsDisabled: true },
    { isProcessing: true },
  ])(
    "does not merge an unkeyed alert with different content or behavior: %j",
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
